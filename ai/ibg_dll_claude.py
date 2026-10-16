"""Python equivalent of IBG.DLL (Win16 "IB"/"BM" 256-colour bitmap library).

Mapping of the DLL exports:

    IBG_GETPALETTE(file)                          -> get_palette(path)
    IBG_GETBITMAP(file, hPal)                     -> get_bitmap(path, palette)
    IBG_SHOWBITMAP(hdc,x,y,cx,cy,xs,ys,hbm,hPal)  -> show_bitmap(dest, x, y, cx, cy, xs, ys, bmp, palette)
    IBG_SAVESYSTEMPALETTE(hdc)                    -> save_system_palette()
    IBG_RESTORESYSTEMPALETTE(hdc, h)              -> restore_system_palette(saved)

Like the DLL, the loaders return None on any failure. Unlike the DLL, the RLE
decoder and header reads are bounds-checked, so malformed files fail cleanly
instead of overflowing a buffer.

Palettes are lists of 256 (r, g, b) tuples. Bitmaps and drawing surfaces are
Pillow images: get_bitmap returns a mode-"P" image whose pixel values index
directly into the palette passed in (the DLL overwrites the file's colour
table with that palette).
"""
import struct
import sys

from PIL import Image

FILE_HDR = struct.Struct("<2sIHHI")             # BITMAPFILEHEADER, 14 B
INFO_HDR = struct.Struct("<IiiHHIIiiII")        # BITMAPINFOHEADER, 40 B
MAGICS = (b"IB", b"BM")
N_COLORS = 256
N_SYSCOLORS = 21                                # COLOR_SCROLLBAR..COLOR_BTNHIGHLIGHT


def _read_headers(data):
    if len(data) < FILE_HDR.size + INFO_HDR.size:
        return None
    magic, _size, _r1, _r2, off_bits = FILE_HDR.unpack_from(data, 0)
    if magic not in MAGICS:
        return None
    (_bi_size, width, height, _planes, _bpp, compression,
     *_rest) = INFO_HDR.unpack_from(data, FILE_HDR.size)
    if compression not in (0, 3):               # BI_RGB, or 3 used as an "IB" marker
        return None
    return magic, off_bits, width, height


def _color_table(data):
    # The DLL always reads exactly 256 RGBQUADs right after the 40-byte header,
    # regardless of biSize / biClrUsed / biBitCount.
    start = FILE_HDR.size + INFO_HDR.size
    raw = data[start:start + 4 * N_COLORS]
    if len(raw) < 4 * N_COLORS:
        return None
    return [(raw[i + 2], raw[i + 1], raw[i]) for i in range(0, len(raw), 4)]  # BGR -> RGB


def _image_size(width, height):
    # Rows padded to 4 bytes; one byte per pixel (8 bpp assumed).
    stride = width + (4 - width % 4) % 4
    return stride, stride * height


def decode_rle(data, pos, out_size):
    """Decode the IB run-length stream starting at data[pos].

    Control byte c, terminated by c == 0:
        c & 0x80 -> repeat the next byte (c & 0x7F) times
        else     -> copy the next c bytes literally
    """
    out = bytearray()
    while True:
        if pos >= len(data):
            raise ValueError("RLE stream not terminated")
        c = data[pos]
        pos += 1
        if c == 0:
            break
        if c & 0x80:
            if pos >= len(data):
                raise ValueError("truncated RLE run")
            out += bytes([data[pos]]) * (c & 0x7F)
            pos += 1
        else:
            if pos + c > len(data):
                raise ValueError("truncated RLE literal")
            out += data[pos:pos + c]
            pos += c
        if len(out) > out_size:
            raise ValueError(f"RLE output exceeds image size ({out_size} B)")
    return bytes(out.ljust(out_size, b"\0"))


def get_palette(path):
    """IBG_GETPALETTE: return the file's 256-colour palette, or None."""
    try:
        with open(path, "rb") as f:
            data = f.read(FILE_HDR.size + INFO_HDR.size + 4 * N_COLORS)
    except OSError:
        return None
    if _read_headers(data) is None:
        return None
    return _color_table(data)


def get_bitmap(path, palette):
    """IBG_GETBITMAP: load an IB (RLE) or BM file as a mode-"P" image, or None.

    The file's own colour table is ignored; `palette` is attached instead.
    """
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    hdr = _read_headers(data)
    if hdr is None:
        return None
    magic, off_bits, width, height = hdr
    if width <= 0 or height <= 0:
        return None
    stride, size = _image_size(width, height)
    try:
        if magic == b"IB":
            bits = decode_rle(data, off_bits, size)
        else:
            bits = data[off_bits:off_bits + size]
            if len(bits) < size:
                return None
    except ValueError:
        return None

    # Bottom-up DIB rows -> top-down image, dropping the row padding.
    img = Image.frombuffer("P", (width, height), bits, "raw", "P", stride, -1)
    img = img.copy()
    img.putpalette(_flatten(palette))
    return img


def show_bitmap(dest, x, y, cx, cy, x_src, y_src, bmp, palette):
    """IBG_SHOWBITMAP: blit bmp[x_src:, y_src:] onto `dest` at (x, y), SRCCOPY.

    cx/cy are clamped to the bitmap's width/height (but not to the source
    offset, as in the DLL). Returns False if dest or bmp is None, else True.
    """
    if dest is None or bmp is None:
        return False
    cx = min(cx, bmp.width)
    cy = min(cy, bmp.height)
    if cx <= 0 or cy <= 0:
        return True
    src = bmp.copy()
    src.putpalette(_flatten(palette))           # SelectPalette + RealizePalette
    region = src.crop((x_src, y_src, x_src + cx, y_src + cy))
    if dest.mode != "P":
        region = region.convert(dest.mode)
    dest.paste(region, (x, y))
    return True


def save_system_palette():
    """IBG_SAVESYSTEMPALETTE: switch to SYSPAL_NOSTATIC and save system colours.

    There is no system palette to take over outside 8-bit Windows displays, so
    this only does real work on Windows (via ctypes); elsewhere it returns an
    empty list.
    """
    if sys.platform != "win32":
        return []
    import ctypes
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    hdc = user32.GetDC(None)
    gdi32.SetSystemPaletteUse(hdc, 2)           # SYSPAL_NOSTATIC
    user32.ReleaseDC(None, hdc)
    return [user32.GetSysColor(i) for i in range(N_SYSCOLORS)]


def restore_system_palette(saved):
    """IBG_RESTORESYSTEMPALETTE: SYSPAL_STATIC and restore saved system colours."""
    if saved is None:
        return False
    if sys.platform != "win32" or not saved:
        return True
    import ctypes
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    hdc = user32.GetDC(None)
    gdi32.SetSystemPaletteUse(hdc, 1)           # SYSPAL_STATIC
    user32.ReleaseDC(None, hdc)
    n = len(saved)
    idx = (ctypes.c_int * n)(*range(n))
    rgb = (ctypes.c_uint32 * n)(*saved)
    user32.SetSysColors(n, idx, rgb)
    return True


def _flatten(palette):
    return [c for rgb in palette for c in rgb]


if __name__ == "__main__":
    # Usage: python ibg.py in.ib out.png  -- decode with the file's own palette.
    src, dst = sys.argv[1], sys.argv[2]
    pal = get_palette(src)
    bmp = get_bitmap(src, pal) if pal else None
    if bmp is None:
        sys.exit(f"{src}: not a valid IB/BM file")
    bmp.save(dst)
