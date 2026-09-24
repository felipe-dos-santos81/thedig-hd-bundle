"""NUT glyph/icon extraction.

Transcribed from the vendored, hash-pinned upstream ScummVM sources
``vendor/san-oracle/upstream/engines/scumm/nut_renderer.cpp`` (``loadFont`` and
``codec21``) and ``smush/codec1.cpp`` (``smushDecodeRLE``), which are
authoritative for The Dig's ``.NUT`` fonts.

Container (verified across the 6 bundle fonts): ``ANIM`` (u32BE length; the font
data is the payload after the 8-byte header) -> ``AHDR`` (palette at payload
``[6:774]``, ``numChars`` u16LE at chunk+10) -> one ``FRME`` per glyph, each
containing exactly one ``FOBJ``. No metadata chunk. Codecs: 1 (BOMP rows,
transparency 0) and 44 (the codec21 run format, transparency 2).
"""

import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .bomp import bomp_decode_line
from .errors import DecodeError

_PALETTE_SIZE = 768
_AHDR_MIN = 0x306  # palette offset (6) + 768
_DEFAULT_TRANSPARENT = 0  # kDefaultTransparentColor (codec 1)
_SMUSH44_TRANSPARENT = 2  # kSmush44TransparentColor (codec 44)


@dataclass(frozen=True)
class NutImage:
    name: str
    index: bytes
    width: int
    height: int
    palette: bytes
    transparent: int


def _u16le(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def smush_decode_rle(buf: bytearray, src: bytes, width: int, height: int, pitch: int) -> None:
    """Port of ScummVM ``smushDecodeRLE`` (codec1.cpp) with ``left = top = 0``."""
    src_off = 0
    for row in range(height):
        bomp_decode_line(buf, row * pitch, src, src_off + 2, width, set_zero=False)
        src_off += _u16le(src, src_off) + 2


def nut_codec21(buf: bytearray, src: bytes, width: int, height: int, pitch: int) -> None:
    """Port of the vendored ``NutRenderer::codec21`` body (codec 44).

    A row is a sequence of ``(skip, run)`` pixel spans; ``skip`` advances within
    the row by pixels (not rows). ``src`` is read relative to the glyph data.
    """
    off = 0
    s_off = 0
    for _ in range(height):
        row_next = s_off + 2 + _u16le(src, s_off)
        s_off += 2
        length = width
        o = off
        while True:
            skip = _u16le(src, s_off)
            s_off += 2
            o += skip
            length -= skip
            if length <= 0:
                break
            run = _u16le(src, s_off) + 1
            s_off += 2
            length -= run
            n = run if length >= 0 else run + length
            buf[o:o + n] = src[s_off:s_off + n]
            o += n
            s_off += n
            if length <= 0:
                break
        s_off = row_next
        off += pitch


def iter_images(data: bytes, source: str = "?") -> Iterator[NutImage]:
    if data[:4] != b"ANIM":
        raise DecodeError(source, 0, f"missing ANIM: {data[:4]!r}")
    if len(data) < 8:
        raise DecodeError(source, 0, "truncated ANIM header")
    anim_len = struct.unpack_from(">I", data, 4)[0]
    if anim_len > len(data) - 8:
        raise DecodeError(source, 4, f"ANIM length {anim_len} overruns file")

    font = data[8:]
    font_len = anim_len
    if font_len < 8 or font[:4] != b"AHDR":
        raise DecodeError(source, 8, f"missing AHDR: {font[:4]!r}")
    ahdr_size = struct.unpack_from(">I", font, 4)[0]
    if ahdr_size < _AHDR_MIN or 8 + ahdr_size > font_len:
        raise DecodeError(source, 8, f"bad AHDR chunk size {ahdr_size}")

    palette = bytes(font[8 + 6:8 + 6 + _PALETTE_SIZE])
    num_chars = _u16le(font, 10)
    name_stem = Path(source).stem.lower()

    off = 8 + ahdr_size + (ahdr_size & 1)
    for i in range(num_chars):
        if off + 8 > font_len:
            raise DecodeError(source, off, f"truncated FRME {i}")
        if font[off:off + 4] != b"FRME":
            raise DecodeError(source, off, f"no FRME chunk {i}: {font[off:off + 4]!r}")
        frme_size = struct.unpack_from(">I", font, off + 4)[0]
        fobj = off + 8
        if fobj + 22 > font_len:
            raise DecodeError(source, fobj, f"truncated FOBJ {i}")
        if font[fobj:fobj + 4] != b"FOBJ":
            raise DecodeError(source, fobj, f"no FOBJ chunk in FRME {i}")

        codec = _u16le(font, fobj + 8)
        width = _u16le(font, fobj + 14)
        height = _u16le(font, fobj + 16)
        glyph = font[fobj + 22:]

        if codec == 1:
            transparent = _DEFAULT_TRANSPARENT
        elif codec == 44:
            transparent = _SMUSH44_TRANSPARENT
        else:
            raise DecodeError(source, fobj + 8, f"unknown NUT codec {codec}")

        buf = bytearray(bytes([transparent]) * (width * height))
        if codec == 1:
            smush_decode_rle(buf, glyph, width, height, width)
        else:
            nut_codec21(buf, glyph, width, height, width)

        yield NutImage(
            name=f"{name_stem}:{i:03d}",
            index=bytes(buf),
            width=width,
            height=height,
            palette=palette,
            transparent=transparent,
        )
        off += 8 + frme_size + (frme_size & 1)
