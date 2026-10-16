"""Converter for Intel DVI "AVSS" (.AVS) files with RTV 2.0 video and ADPCM4E audio.

Container (little-endian):
    file header      "IVDV" ... "SSVA", stream headers ("MRTS"), frame count
                     at 0x40, offset of first frame at 0x48
    frame header     u32 frame no., u32 offset of previous frame, u32 checksum,
                     u32 size of each stream (video, audio)
    frame payload    the stream chunks, back to back

RTV 2.0 video (an early Indeo 2):
    32-byte header; bytes 0x18..0x1F give the bit widths of the 8 code groups.
    A code is a unary prefix k (k ones, then a zero) followed by width[k] bits;
    its index runs through the Indeo 2 symbol list (as in FFmpeg's indeo2data.h).
    Bits are read LSB-first. Planes Y, V, U are coded as in Indeo 2 intra frames
    (first line absolute, then vertical deltas from table 0). Chroma is
    subsampled 4x4. If bit 0x100 of the u16 at 0x10 is set, luma is stored at
    half the width declared in the headers (128x240 for 256x240).

ADPCM4E audio (DVI ADPCM, i.e. IMA ADPCM, 1 channel):
    The audio chunks form one continuous byte stream: 2 leading bytes, then
    blocks of [index | 0x80 if long][predictor >> 8 (signed)][154 or 156 bytes].
    Data is in big-endian 16-bit words, high nibble first. The predictor is
    reset from the header at each block.
"""
import struct
import subprocess
import sys

import numpy as np

# Indeo 2 symbols in code order: 0x01..0x7F are delta pairs, 0x81..0x90 runs.
SYMS = [
    0x01, 0x02, 0x80, 0x03, 0x04, 0x81, 0x05, 0x06, 0x82, 0x83, 0x07, 0x08,
    0x84, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x85, 0x0F, 0x10, 0x86, 0x87,
    0x11, 0x12, 0x13, 0x14, 0x88, 0x15, 0x16, 0x89, 0x17, 0x18, 0x8A, 0x19,
    0x1A, 0x8B, 0x1B, 0x1C, 0x8C, 0x1D, 0x1E, 0x8D, 0x1F, 0x20, 0x8E, 0x21,
    0x22, 0x8F, 0x23, 0x24] + list(range(0x25, 0x80))

# Indeo 2 delta table 0 (FFmpeg ir2_delta_table[0]): 128 pairs.
DELTA0 = bytes.fromhex(
    "808084847c7c7f85817b857f7b818c8c7474838d7d738d83737d778989778977"
    "77898c95746b958c6b747c908470907c708496966a6a82987e689882687e97a2"
    "695ea2975e69a2a25e5e8ba3755da38b5d7571958f6b95716b8f789d88639d78"
    "63887fa78159a77f5981a4b15c4fb1a44f5c96b16a4fb1964f6ab2b24e4e659b"
    "9b659b65659b89b4774cb4894c776aa3965da36a5d9673ac8d54ac73548db4c3"
    "4c3dc3b43d4ca4c35c3dc3a43d5cc4c43c3c96c66a3ac6963a6a7cba8446ba7c"
    "46845baba555ab5b55a563b49d4cb4634c9d86ca7a36ca86367ab6d74a29d7b6"
    "294ac8d73829d7c82938a4d85c28d8a4285c6cc1943fc16c3f94d9d927278080"
)

STEP = [
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41,
    45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190,
    209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796,
    876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749,
    3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630,
    9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623,
    27086, 29794, 32767]
INDEX_ADJ = [-1, -1, -1, -1, 2, 4, 6, 8]


def read_frames(data):
    """Return a list of (video_chunk, audio_chunk) per frame."""
    if data[0:4] != b"IVDV" or data[12:16] != b"SSVA":
        raise ValueError("not an Intel DVI AVSS file")
    n_frames = struct.unpack_from("<H", data, 0x40)[0]
    off = struct.unpack_from("<I", data, 0x48)[0]
    frames, prev = [], 0
    while len(frames) < n_frames and off + 20 <= len(data):
        fn, back, _chk, vs, as_ = struct.unpack_from("<5I", data, off)
        if fn != len(frames) or back != prev:
            raise ValueError(f"broken frame chain at 0x{off:x}")
        p = off + 20
        frames.append((data[p:p + vs], data[p + vs:p + vs + as_]))
        prev, off = off, p + vs + as_
    return frames


_lut_cache = {}


def _code_lut(widths):
    """Lookup table: 14-bit LSB-first peek -> (symbol, code length)."""
    key = bytes(widths)
    if key in _lut_cache:
        return _lut_cache[key]
    lut = [None] * (1 << 14)
    idx = 0
    for k, w in enumerate(widths):
        for v in range(1 << w):
            if idx < len(SYMS):
                # Bits in stream order: k ones, a zero, then v MSB-first.
                bits = [1] * k + [0] + [(v >> (w - 1 - j)) & 1 for j in range(w)]
                n = len(bits)
                if n <= 14:
                    code = sum(b << j for j, b in enumerate(bits))
                    for hi in range(1 << (14 - n)):
                        lut[code | (hi << n)] = (SYMS[idx], n)
            idx += 1
    _lut_cache[key] = lut
    return lut


def _decode_plane(buf, pos, end, lut, w, h):
    out = np.empty((h, w), np.int16)
    row = [0] * w
    prev = None
    for y in range(h):
        x = 0
        while x < w:
            if pos >= end:
                raise ValueError("out of data")
            p = pos >> 3
            peek = (int.from_bytes(buf[p:p + 3], "little") >> (pos & 7)) & 0x3FFF
            e = lut[peek]
            if e is None:
                raise ValueError("invalid code")
            c, n = e
            pos += n
            if c >= 0x80:
                run = (c - 0x7F) * 2
                if x + run > w:
                    raise ValueError("run past end of line")
                for i in range(x, x + run):
                    row[i] = 0x80 if prev is None else prev[i]
                x += run
            else:
                d0, d1 = DELTA0[2 * c], DELTA0[2 * c + 1]
                if prev is None:
                    row[x], row[x + 1] = d0, d1
                else:
                    row[x] = min(255, max(0, prev[x] + d0 - 128))
                    row[x + 1] = min(255, max(0, prev[x + 1] + d1 - 128))
                x += 2
        out[y] = row
        prev = row[:]
    return out.astype(np.uint8), pos


def decode_video_frame(chunk):
    """Decode one RTV 2.0 frame to (Y, U, V) planes."""
    h, w, flags = struct.unpack_from("<HHH", chunk, 0x0C)
    if flags & 0x100:                            # luma stored at half width
        w //= 2
    buf = chunk + b"\0\0\0"
    end = len(chunk) * 8
    lut = _code_lut(chunk[0x18:0x20])
    pos = 0x20 * 8
    y, pos = _decode_plane(buf, pos, end, lut, w, h)
    v, pos = _decode_plane(buf, pos, end, lut, w // 4, h // 4)
    u, pos = _decode_plane(buf, pos, end, lut, w // 4, h // 4)
    return y, u, v


def decode_audio(chunks):
    """Decode the ADPCM4E stream to int16 mono samples."""
    s = b"".join(chunks) + b"\0\0"
    out = []
    pos = 2
    while pos + 2 < len(s) - 2:
        hdr = s[pos]
        pred = struct.unpack_from("<b", s, pos + 1)[0] << 8
        idx = min(hdr & 0x7F, 88)
        n = 156 if hdr & 0x80 else 154
        block = s[pos + 2:pos + 2 + n]
        pos += 2 + n
        for i in range(0, len(block) - 1, 2):
            word = (block[i + 1] << 8) | block[i]  # big-endian 16-bit words
            for sh in (12, 8, 4, 0):
                nib = (word >> sh) & 15
                step = STEP[idx]
                diff = step >> 3
                if nib & 4:
                    diff += step
                if nib & 2:
                    diff += step >> 1
                if nib & 1:
                    diff += step >> 2
                pred = pred - diff if nib & 8 else pred + diff
                pred = max(-32768, min(32767, pred))
                idx = max(0, min(88, idx + INDEX_ADJ[nib & 7]))
                out.append(pred)
    return np.array(out, np.int16)


def main(path, outpath=None):
    data = open(path, "rb").read()
    frames = read_frames(data)
    fps = struct.unpack_from("<H", data, 0x204)[0] or 25
    outpath = outpath or path.rsplit(".", 1)[0] + ".mkv"

    audio = decode_audio([a for _, a in frames])
    rate = round(len(audio) * fps / len(frames))   # keeps A/V in sync
    wav = outpath + ".pcm"
    audio.astype("<i2").tofile(wav)
    print(f"{path}: {len(frames)} frames @ {fps} fps, "
          f"audio {len(audio)} samples @ {rate} Hz")

    y, _, _ = decode_video_frame(frames[0][0])
    h, w = y.shape
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "yuv410p", "-s", f"{w}x{h}",
           "-r", str(fps), "-i", "-",
           "-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", wav,
           "-vf", "scale=320:240:flags=lanczos,setsar=1",
           "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
           "-c:a", "flac", outpath]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for n, (v, _) in enumerate(frames):
        try:
            planes = decode_video_frame(v)
        except (ValueError, IndexError) as e:
            print(f"frame {n}: {e}; repeating previous frame")
        ff.stdin.write(b"".join(p.tobytes() for p in planes))
        if n % 100 == 0:
            print(f"  frame {n}/{len(frames)}", flush=True)
    ff.stdin.close()
    ff.wait()
    import os
    os.remove(wav)
    print(f"wrote {outpath}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
