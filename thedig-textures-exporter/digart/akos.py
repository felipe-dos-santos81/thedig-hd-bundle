"""AKOS costume-cel extraction.

Transcribed from the vendored upstream ScummVM sources
``vendor/san-oracle/upstream/engines/scumm/akos.cpp``
(``AkosRenderer::setCostume``/``drawLimb`` cel enumeration and
``majMinCodecDecompress``) and ``base-costume.cpp``
(``paintCelByleRLECommon``/``byleRLEDecode``), which are authoritative for The
Dig's ``DIG.LA1`` costume cels. The C++ oracle's ``akos`` mode
(``vendor/san-oracle/oracle_main.cpp`` + the generated ``akos_core.cpp``) is the
exact behaviour mirrored here.

An ``AKOS`` chunk is a room resource addressed by a room-relative offset inside
the enclosing ``LFLF`` (it sits after the ``ROOM`` chunk, not among its
children), so the walk starts at ``ROOM + 8`` and runs to the ``LFLF`` end. The
cel tables are read exactly as ``AkosRenderer::setCostume``/``drawLimb`` do:
``AKHD`` carries ``celsCount`` (@6) and ``celCompressionCodec`` (@8); ``AKOF``
is ``celsCount`` x ``{ u32 akcd; u16 akci }`` (6 bytes); the cel width/height
are the first two ``u16`` of ``AKCI`` at ``akci``; the cel data is
``AKCD + akcd``; ``AKPL``'s payload size is ``numColors`` for the Byle codec.

Codecs 1 (Byle RLE), 5 (CDAT/BOMP) and 16 (MajMin) are decoded, each into a
buffer pre-filled with the codec's transparent index (0 for Byle, 255 for
CDAT/MajMin). Any other codec, or a non-positive dimension, records a
``DecodeError`` (the oracle's ``AKOSE`` record) and yields no cel.
"""

from collections.abc import Iterator
from dataclasses import dataclass

from .bomp import bomp_decode_rows
from .errors import DecodeError
from .la1 import (La1Bitmap, _MajMinCodec, _be32, _children, _find_child,
                  _iter_rooms, _le16, _le32)

_BYLE_RLE_CODEC = 1
_CDAT_RLE_CODEC = 5
_RUN_MAJMIN_CODEC = 16
_CODECS = frozenset({_BYLE_RLE_CODEC, _CDAT_RLE_CODEC, _RUN_MAJMIN_CODEC})
_TRANSPARENT_BYLE = 0
_TRANSPARENT_BOMP = 255
_PALETTE_SIZE = 768


@dataclass(frozen=True)
class AkosCel(La1Bitmap):
    """A costume cel; ``transparent`` is the codec's transparent colour index."""

    costume: int
    cel: int
    transparent: int


def _byle_rle_decode(buf: bytearray, w: int, h: int, data: bytes, src_off: int,
                     num_colors: int) -> None:
    """``BaseCostumeRenderer::byleRLEDecode`` under the oracle's fixed state.

    Unscaled (``_scaleX = _scaleY = 255``), drawn to the right, ``_akosRendering``
    with an identity palette and shadow mode 0, an all-zero mask, and the bounds
    rectangle equal to the cel. Pixels are written column-major (``buf[y*w + x]``)
    with runs whose length is the low nibble/2 bits of each control byte (a zero
    run length takes the following byte). Zero-valued pixels are skipped; the
    destination is pre-filled with the transparent index 0.
    """
    if num_colors == 32:
        mask, shr = 7, 3
    elif num_colors == 64:
        mask, shr = 3, 2
    else:
        mask, shr = 15, 4

    p = src_off
    x = 0
    dst = 0
    height = h
    skip_width = w
    while True:
        run = data[p]
        p += 1
        color = run >> shr
        run &= mask
        if run == 0:
            run = data[p]
            p += 1
        while True:
            if color:
                buf[dst] = color
            dst += w
            height -= 1
            if height == 0:
                skip_width -= 1
                if skip_width == 0:
                    return
                height = h
                x += 1
                if x >= w:
                    return
                dst = x
            run = (run - 1) & 0xFF
            if run == 0:
                break


def _cdat_decode(buf: bytearray, w: int, h: int, data: bytes, src_off: int) -> None:
    """``Scumm::decompressBomp`` (bomp.cpp:42): one BOMP row per cel row."""
    bomp_decode_rows(buf, w, data, src_off, w, h, set_zero=True)


def _majmin_decode(buf: bytearray, w: int, h: int, data: bytes, src_off: int) -> None:
    """``AkosRenderer::majMinCodecDecompress`` for dir 1, no skips, transparency 255.

    ``setupBitReader(*src, src + 1)``: the cel's first byte is the colour shift
    and the bit stream starts one byte later. The zeroed mask and shadow mode 0
    reduce the per-row commit to writing every non-transparent pixel.
    """
    majmin = _MajMinCodec(data[src_off], data, src_off + 1)
    line = bytearray(w)
    for y in range(h):
        majmin.decode_line(line, 0, w, 1, data)
        row = y * w
        for i in range(w):
            color = line[i]
            if color != _TRANSPARENT_BOMP:
                buf[row + i] = color


def _process_costume(data: bytes, akos: int, costume: int, errors: list,
                     source: str) -> Iterator[AkosCel]:
    akos_size = _be32(data, akos + 4)
    akhd = _find_child(data, akos, akos_size, b"AKHD")
    akof = _find_child(data, akos, akos_size, b"AKOF")
    akci = _find_child(data, akos, akos_size, b"AKCI")
    akcd = _find_child(data, akos, akos_size, b"AKCD")
    akpl = _find_child(data, akos, akos_size, b"AKPL")
    if akhd is None or akof is None or akci is None or akcd is None:
        return

    cels = _le16(data, akhd + 8 + 6)
    codec = _le16(data, akhd + 8 + 8)
    num_colors = _be32(data, akpl + 4) - 8 if akpl is not None else 0

    for cel in range(cels):
        akcd_off = _le32(data, akof + 8 + 6 * cel)
        akci_off = _le16(data, akof + 8 + 6 * cel + 4)
        w = _le16(data, akci + 8 + akci_off)
        h = _le16(data, akci + 8 + akci_off + 2)
        if w <= 0 or h <= 0 or codec not in _CODECS:
            err = DecodeError(source, akos, f"unsupported AKOS codec {codec}")
            err.costume = costume
            err.cel = cel
            err.codec = codec
            errors.append(err)
            continue

        transparent = _TRANSPARENT_BYLE if codec == _BYLE_RLE_CODEC else _TRANSPARENT_BOMP
        buf = bytearray([transparent]) * (w * h)
        src_off = akcd + 8 + akcd_off
        if codec == _BYLE_RLE_CODEC:
            _byle_rle_decode(buf, w, h, data, src_off, num_colors)
        elif codec == _CDAT_RLE_CODEC:
            _cdat_decode(buf, w, h, data, src_off)
        else:
            _majmin_decode(buf, w, h, data, src_off)

        yield AkosCel(
            name=f"costume{costume:03d}_{cel:03d}",
            index=bytes(buf),
            width=w,
            height=h,
            palette=bytes(_PALETTE_SIZE),
            costume=costume,
            cel=cel,
            transparent=transparent,
        )


def iter_cels(la1: bytes, errors: list,
              source: str = "AKOS") -> Iterator[La1Bitmap]:
    """Yield every decodable costume cel from ``DIG.LA1`` in file order.

    Undecodable cels append a ``DecodeError`` (with ``costume``/``cel``/``codec``
    attributes, the oracle's ``AKOSE`` record) to ``errors`` and yield no cel.
    """
    costume = 0
    for _room, room_off in _iter_rooms(la1, source):
        # The AKOS chunk is a room resource addressed inside the enclosing LFLF,
        # so the walk runs from the ROOM header to the LFLF end.
        lflf_off = room_off - 8
        lflf_end = lflf_off + _be32(la1, lflf_off + 4)
        for tag, c, _size in _children(la1, room_off, lflf_end):
            if tag == b"AKOS":
                costume += 1
                yield from _process_costume(la1, c, costume, errors, source)
