# IBG convert

Reverse-engineered converter for a long-lost IBG image format. 

To my knowledge it is only used in a "Invitation au voyage" CD-ROM
related to this exhibition:

> Invitation au voyage. La photographie humaniste française et la
> photogrphie neoréaliste italienne. Napoli, Castel Sant'Elmo, 23
> Gennaio - 7 Novembre, 1993.

The format appears to be a BMP V3 format with a different signature. 
Regardless of the [header](https://docs.microsoft.com/it-it/windows/win32/api/wingdi/ns-wingdi-bitmapinfo),
however, the data section appears to be
compressed with a non-standard algorithm analog to PackBits.
All of the available examples are 8-bit RGB indexed.
The format seems related to a Windows 3.1 DLL named `ibg.dll`. 

The reverse-engineered algorithm decodes to an equivalent indexed PNG
using Pillow. Succeeds with 950/959 files, so that there
may still be some edge cases left. However, the missing files are not decoded
by the native application, either.

## Requirements

`numpy` and [Pillow](https://pypi.org/project/pillow/).

## Usage

    python ibg.py input.ibg

# AVS (Intel DVI) convert

> **Warning:** Claude generated on 16/10/2026. The AVS converter and this
> section were reverse-engineered by Claude from two sample files and have
> not been checked against Intel documentation.

The same CD-ROM also carries `.AVS` video clips in Intel's DVI "AVSS"
format (ActionMedia era), with RTV 2.0 video and "ADPCM4E" audio, which
FFmpeg does not read. `avs.py` demuxes the file, decodes both streams and
pipes them to `ffmpeg` (H.264 + FLAC in Matroska):

    python avs.py input.AVS [output.mkv]

Findings, documented at the top of `avs.py`:

* **Video** is an early Indeo 2: same symbols and delta table as FFmpeg's
  `indeo2` decoder, but each frame defines its own code (8 group widths
  of a unary-prefix + fixed-length code). A header flag marks luma stored
  at half the declared width (128x240 for 256x240); either way the output is
  rescaled to 320x240 (4:3). Only intra frames have been seen.
* **Audio** is mono DVI/IMA ADPCM in blocks of 154/156 bytes, each with a
  2-byte header (step index, predictor high byte). Nibbles are packed in
  big-endian 16-bit words. The sample rate (31160 Hz for the sample file)
  is derived from A/V sync.

Requires `numpy` and `ffmpeg`.
