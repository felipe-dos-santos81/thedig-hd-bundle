"""SCUMM v7 LA1 room/object bitmap extraction.

Transcribed from the vendored upstream ScummVM sources
``vendor/san-oracle/upstream/engines/scumm/gfx.cpp`` (``Gdi::decompressBitmap``
and the strip decoders ``drawStripRaw``/``drawStripBasicV``/``drawStripBasicH``/
``drawStripComplex`` including ``MajMinCodec``) and ``bomp.cpp``
(``bompDecodeLine``), which are authoritative for The Dig's ``DIG.LA1``.

Container (verified in ``docs/la1-census.txt`` and by the oracle in
``vendor/san-oracle/oracle_main.cpp``): ``LECF`` -> ``LOFF`` (u8 count, then
``count`` x (u8 room, u32LE offset)) -> each offset is an ``LFLF`` payload =
``ROOM``. Chunk sizes are header-inclusive with **no odd padding**:
``next = start + size``. Per room: dimensions from ``RMHD``, transparent colour
from ``TRNS``, palette from ``PALS -> WRAP -> OFFS + APAL`` (active index 0).
``RMIM -> IM00 -> SMAP``; ``OBIM -> IMHD + IM01..IM0E`` where each ``IMxx``
payload is ``SMAP`` or ``BOMP``. Script/audio/auxiliary chunks are skipped.

An image whose codec is outside the transcribed set records a ``DecodeError``
instead of yielding a bitmap (the oracle's ``LA1E`` record). ``transparent0`` is
the OR of the per-strip ``transpStrip`` flag across the image's strips.
"""

import struct
from collections.abc import Iterator
from dataclasses import dataclass

from .bomp import bomp_decode_rows
from .errors import DecodeError

_PALETTE_SIZE = 768
_DEFAULT_TRANSPARENT = 255  # gfx.cpp: transparentColor when a room has no TRNS

# gfx.h BMCOMP_* ids the transcribed decoders cover (see la1_codec_supported).
BMCOMP_RAW256 = 1
_ZIGZAG_V = frozenset(range(14, 19))    # BMCOMP_ZIGZAG_V4..V8
_ZIGZAG_H = frozenset(range(24, 29))    # BMCOMP_ZIGZAG_H4..H8
_ZIGZAG_VT = frozenset(range(34, 39))   # BMCOMP_ZIGZAG_VT4..VT8
_ZIGZAG_HT = frozenset(range(44, 49))   # BMCOMP_ZIGZAG_HT4..HT8
_MAJMIN_H = frozenset(range(64, 69))    # BMCOMP_MAJMIN_H4..H8
_MAJMIN_HT = frozenset(range(84, 89))   # BMCOMP_MAJMIN_HT4..HT8
_RMAJMIN_H = frozenset(range(104, 109))  # BMCOMP_RMAJMIN_H4..H8
_RMAJMIN_HT = frozenset(range(124, 129))  # BMCOMP_RMAJMIN_HT4..HT8
_SUPPORTED = (
    frozenset({BMCOMP_RAW256})
    | _ZIGZAG_V | _ZIGZAG_H | _ZIGZAG_VT | _ZIGZAG_HT
    | _MAJMIN_H | _MAJMIN_HT | _RMAJMIN_H | _RMAJMIN_HT
)


@dataclass(frozen=True)
class La1Bitmap:
    name: str
    index: bytes
    width: int
    height: int
    palette: bytes
    # The decoder's transparent colour index, or None for an opaque bitmap:
    # 0 for a transparent SMAP strip (RMIM/OBIM), 255 for a BOMP OBIM object
    # sprite.
    transparent: int | None

    @property
    def transparent0(self) -> bool:
        """The oracle's per-strip transparent flag: exactly ``transparent == 0``."""
        return self.transparent == 0


def _be32(data: bytes, off: int) -> int:
    return struct.unpack_from(">I", data, off)[0]


def _le32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def _le16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def _is_tag(data: bytes, off: int) -> bool:
    tag = data[off:off + 4]
    return len(tag) == 4 and all(0x20 <= b <= 0x7E for b in tag)


def _children(data: bytes, start: int, end: int) -> Iterator[tuple[bytes, int, int]]:
    """Yield ``(tag, offset, size)`` for each valid child chunk in ``[start, end)``.

    Walks ``start + 8`` onward with the header-inclusive stride ``next = offset +
    size`` (no odd padding), stopping at the first non-tag or out-of-bounds chunk.
    This is the single walk behind ``_find_child`` and the room/OBIM/AKOS scans.
    """
    c = start + 8
    while c + 8 <= end:
        if not _is_tag(data, c):
            return
        size = _be32(data, c + 4)
        if size < 8 or c + size > end:
            return
        yield data[c:c + 4], c, size
        c += size


def _find_child(data: bytes, start: int, start_size: int, tag: bytes) -> int | None:
    """Offset of the first child chunk ``tag`` within ``start``'s header-inclusive size."""
    end = start + start_size
    return next((off for t, off, _ in _children(data, start, end) if t == tag), None)


def _room_palette(data: bytes, pals: int) -> bytes | None:
    """PALS -> WRAP -> OFFS; the active palette is at OFFS payload + OFFS[0]."""
    wrap = _find_child(data, pals, _be32(data, pals + 4), b"WRAP")
    if wrap is None:
        return None
    offs = _find_child(data, wrap, _be32(data, wrap + 4), b"OFFS")
    if offs is None:
        return None
    offs_payload = offs + 8
    apal = offs_payload + _le32(data, offs_payload)
    return bytes(data[apal:apal + _PALETTE_SIZE])


def _draw_strip_raw(dst: bytearray, dst_off: int, dst_pitch: int, src: bytes,
                    src_off: int, height: int, transp_check: bool,
                    transparent_color: int) -> None:
    """Gdi::drawStripRaw (gfx.cpp:4220), non-GF_OLD256 arm."""
    for _ in range(height):
        for x in range(8):
            color = src[src_off]
            src_off += 1
            if not transp_check or color != transparent_color:
                dst[dst_off + x] = color
        dst_off += dst_pitch


def _draw_strip_basic_h(dst: bytearray, dst_off: int, dst_pitch: int, src: bytes,
                        src_off: int, height: int, decomp_shr: int,
                        decomp_mask: int, transp_check: bool,
                        transparent_color: int) -> None:
    """Gdi::drawStripBasicH (gfx.cpp:4122), verbatim READ_BIT/FILL_BITS order."""
    color = src[src_off]
    src_off += 1
    bits = src[src_off]
    src_off += 1
    cl = 8
    inc = -1
    h = height
    while True:
        x = 8
        while True:
            if cl <= 8:
                bits |= src[src_off] << cl
                src_off += 1
                cl += 8
            if not transp_check or color != transparent_color:
                dst[dst_off] = color
            dst_off += 1
            cl -= 1
            bit = bits & 1
            bits >>= 1
            if bit:
                cl -= 1
                bit = bits & 1
                bits >>= 1
                if not bit:
                    if cl <= 8:
                        bits |= src[src_off] << cl
                        src_off += 1
                        cl += 8
                    color = bits & decomp_mask
                    bits >>= decomp_shr
                    cl -= decomp_shr
                    inc = -1
                else:
                    cl -= 1
                    bit = bits & 1
                    bits >>= 1
                    if not bit:
                        color = (color + inc) & 0xFF
                    else:
                        inc = -inc
                        color = (color + inc) & 0xFF
            x -= 1
            if x == 0:
                break
        dst_off += dst_pitch - 8
        h -= 1
        if h == 0:
            break


def _draw_strip_basic_v(dst: bytearray, dst_off: int, dst_pitch: int, src: bytes,
                        src_off: int, height: int, decomp_shr: int,
                        decomp_mask: int, vert_strip_next_inc: int,
                        transp_check: bool, transparent_color: int) -> None:
    """Gdi::drawStripBasicV (gfx.cpp:4154), verbatim READ_BIT/FILL_BITS order."""
    color = src[src_off]
    src_off += 1
    bits = src[src_off]
    src_off += 1
    cl = 8
    inc = -1
    x = 8
    while True:
        h = height
        while True:
            if cl <= 8:
                bits |= src[src_off] << cl
                src_off += 1
                cl += 8
            if not transp_check or color != transparent_color:
                dst[dst_off] = color
            dst_off += dst_pitch
            cl -= 1
            bit = bits & 1
            bits >>= 1
            if bit:
                cl -= 1
                bit = bits & 1
                bits >>= 1
                if not bit:
                    if cl <= 8:
                        bits |= src[src_off] << cl
                        src_off += 1
                        cl += 8
                    color = bits & decomp_mask
                    bits >>= decomp_shr
                    cl -= decomp_shr
                    inc = -1
                else:
                    cl -= 1
                    bit = bits & 1
                    bits >>= 1
                    if not bit:
                        color = (color + inc) & 0xFF
                    else:
                        inc = -inc
                        color = (color + inc) & 0xFF
            h -= 1
            if h == 0:
                break
        dst_off -= vert_strip_next_inc
        x -= 1
        if x == 0:
            break


class _MajMinCodec:
    """MajMinCodec (gfx.cpp:5010-5074): run-length + bit-packed colour deltas."""

    __slots__ = ("repeat_mode", "repeat_count", "color", "shift", "bits",
                 "num_bits", "data_ptr")

    def __init__(self, shift: int, src: bytes, src_off: int):
        self.repeat_mode = False
        self.repeat_count = 0
        self.num_bits = 16
        self.shift = shift
        self.color = src[src_off]
        self.bits = src[src_off + 1] | (src[src_off + 2] << 8)
        self.data_ptr = src_off + 3

    def _read_bits(self, n: int, src: bytes) -> int:
        if self.num_bits <= 8:
            self.bits |= src[self.data_ptr] << self.num_bits
            self.data_ptr += 1
            self.num_bits += 8
        value = self.bits & ((1 << n) - 1)
        self.num_bits -= n
        self.bits >>= n
        return value

    def decode_line(self, buf: bytearray, buf_off: int, numbytes: int,
                    direction: int, src: bytes) -> None:
        while numbytes:
            buf[buf_off] = self.color
            buf_off += direction
            if not self.repeat_mode:
                if self._read_bits(1, src):
                    if self._read_bits(1, src):
                        diff = self._read_bits(3, src)
                        if diff != 4:
                            self.color = (self.color + diff - 4) & 0xFF
                        else:
                            self.repeat_mode = True
                            self.repeat_count = self._read_bits(8, src) - 1
                    else:
                        self.color = self._read_bits(self.shift, src)
            else:
                self.repeat_count -= 1
                if self.repeat_count == 0:
                    self.repeat_mode = False
            numbytes -= 1


def _draw_strip_complex(dst: bytearray, dst_off: int, dst_pitch: int, src: bytes,
                        src_off: int, height: int, decomp_shr: int,
                        transp_check: bool, transparent_color: int) -> None:
    """Gdi::drawStripComplex (gfx.cpp:4101)."""
    majmin = _MajMinCodec(decomp_shr, src, src_off)
    line = bytearray(8)
    for _ in range(height):
        majmin.decode_line(line, 0, 8, 1, src)
        for i in range(8):
            color = line[i]
            if not transp_check or color != transparent_color:
                dst[dst_off] = color
            dst_off += 1
        dst_off += dst_pitch - 8


def _decompress_bitmap(dst: bytearray, dst_off: int, dst_pitch: int, src: bytes,
                       src_off: int, num_lines: int,
                       transparent_color: int) -> bool:
    """Gdi::decompressBitmap (gfx.cpp:2963), returning the transpStrip flag."""
    code = src[src_off]
    src_off += 1
    transp_strip = False
    decomp_shr = code % 10
    decomp_mask = 0xFF >> (8 - decomp_shr)

    if code == BMCOMP_RAW256:
        _draw_strip_raw(dst, dst_off, dst_pitch, src, src_off, num_lines,
                        False, transparent_color)
    elif code in _ZIGZAG_V:
        _draw_strip_basic_v(dst, dst_off, dst_pitch, src, src_off, num_lines,
                            decomp_shr, decomp_mask, num_lines * dst_pitch - 1,
                            False, transparent_color)
    elif code in _ZIGZAG_H:
        _draw_strip_basic_h(dst, dst_off, dst_pitch, src, src_off, num_lines,
                            decomp_shr, decomp_mask, False, transparent_color)
    elif code in _ZIGZAG_VT:
        transp_strip = True
        _draw_strip_basic_v(dst, dst_off, dst_pitch, src, src_off, num_lines,
                            decomp_shr, decomp_mask, num_lines * dst_pitch - 1,
                            True, transparent_color)
    elif code in _ZIGZAG_HT:
        transp_strip = True
        _draw_strip_basic_h(dst, dst_off, dst_pitch, src, src_off, num_lines,
                            decomp_shr, decomp_mask, True, transparent_color)
    elif code in _MAJMIN_H or code in _RMAJMIN_H:
        _draw_strip_complex(dst, dst_off, dst_pitch, src, src_off, num_lines,
                            decomp_shr, False, transparent_color)
    elif code in _MAJMIN_HT or code in _RMAJMIN_HT:
        transp_strip = True
        _draw_strip_complex(dst, dst_off, dst_pitch, src, src_off, num_lines,
                            decomp_shr, True, transparent_color)
    else:  # pragma: no cover - callers gate on _SUPPORTED first
        raise DecodeError("LA1", src_off - 1, f"unsupported codec {code}")
    return transp_strip


def _decode_smap(data: bytes, smap: int, w: int, h: int, palette: bytes,
                 transparent_color: int, res_off: int, source: str, name: str,
                 errors: list) -> La1Bitmap | None:
    smaplen = _be32(data, smap + 4)
    buf = bytearray(w * h)
    transp = False
    for s in range(w // 8):
        if s * 4 + 8 >= smaplen:
            errors.append(DecodeError(source, res_off, "SMAP strip table overrun"))
            return None
        off = _le32(data, smap + s * 4 + 8)
        if off >= smaplen:
            errors.append(DecodeError(source, res_off, "SMAP strip offset out of range"))
            return None
        code = data[smap + off]
        if code not in _SUPPORTED:
            errors.append(DecodeError(source, res_off, "unsupported SMAP codec"))
            return None
        if _decompress_bitmap(buf, s * 8, w, data, smap + off, h, transparent_color):
            transp = True
    return La1Bitmap(name, bytes(buf), w, h, palette, 0 if transp else None)


def _decode_bomp(data: bytes, bomp: int, w: int, h: int, palette: bytes,
                 res_off: int, source: str, name: str,
                 errors: list) -> La1Bitmap | None:
    body = bomp + 8
    bw = _le16(data, body + 2)
    bh = _le16(data, body + 4)
    if bw != w or bh != h:
        errors.append(DecodeError(source, res_off, "BOMP dimensions disagree with IMHD"))
        return None
    buf = bytearray(w * h)
    bomp_decode_rows(buf, w, data, body + 10, bw, bh, set_zero=True)
    return La1Bitmap(name, bytes(buf), w, h, palette, 255)


def _process_room(data: bytes, room_off: int, room: int, errors: list,
                  source: str) -> Iterator[La1Bitmap]:
    room_size = _be32(data, room_off + 4)
    room_end = room_off + room_size

    rw = rh = 0
    rmhd = _find_child(data, room_off, room_size, b"RMHD")
    if rmhd is not None:
        rw = _le16(data, rmhd + 8 + 4)
        rh = _le16(data, rmhd + 8 + 6)

    trns = _find_child(data, room_off, room_size, b"TRNS")
    transparent_color = data[trns + 8] if trns is not None else _DEFAULT_TRANSPARENT

    pals = _find_child(data, room_off, room_size, b"PALS")
    palette = _room_palette(data, pals) if pals is not None else None
    if palette is None:
        palette = bytes(_PALETTE_SIZE)

    for tag, c, size in _children(data, room_off, room_end):
        if tag == b"RMIM":
            im00 = _find_child(data, c, size, b"IM00")
            if im00 is not None:
                smap = _find_child(data, im00, _be32(data, im00 + 4), b"SMAP")
                if smap is not None:
                    bmp = _decode_smap(data, smap, rw, rh, palette, transparent_color,
                                       im00, source, f"room{room:03d}", errors)
                    if bmp is not None:
                        yield bmp
        elif tag == b"OBIM":
            imhd = _find_child(data, c, size, b"IMHD")
            if imhd is not None:
                obj_id = _le16(data, imhd + 8 + 4)
                ow = _le16(data, imhd + 8 + 12)
                oh = _le16(data, imhd + 8 + 14)
                for itag, ic, _ in _children(data, c, c + size):
                    if not (itag[:2] == b"IM" and itag[2] != 0x48):
                        continue
                    name = f"obj{obj_id:03d}_{itag[2:4].decode('latin1')}"
                    payload = ic + 8
                    if data[payload:payload + 4] == b"SMAP":
                        bmp = _decode_smap(data, payload, ow, oh, palette,
                                           transparent_color, ic, source, name, errors)
                    elif data[payload:payload + 4] == b"BOMP":
                        bmp = _decode_bomp(data, payload, ow, oh, palette,
                                           ic, source, name, errors)
                    else:
                        errors.append(DecodeError(source, ic, "unknown OBIM image container"))
                        bmp = None
                    if bmp is not None:
                        yield bmp


def _iter_rooms(la1: bytes, source: str) -> Iterator[tuple[int, int]]:
    """Yield ``(room, room_off)`` for each validated ``LOFF`` entry of ``DIG.LA1``.

    Shared container walk for the RMIM/OBIM bitmaps and the AKOS costume cels.
    """
    if len(la1) < 16 or la1[:4] != b"LECF":
        raise DecodeError(source, 0, f"missing LECF: {la1[:4]!r}")
    lecf_size = _be32(la1, 4)
    if lecf_size > len(la1):
        raise DecodeError(source, 4, f"LECF size {lecf_size} overruns file")
    if la1[8:12] != b"LOFF":
        raise DecodeError(source, 8, f"missing LOFF: {la1[8:12]!r}")

    loff = 16
    for i in range(la1[loff]):
        room = la1[loff + 1 + 5 * i]
        room_off = _le32(la1, loff + 2 + 5 * i)
        if room_off < 8 or room_off + 8 > len(la1):
            raise DecodeError(source, room_off, f"room {room} offset out of range")
        if la1[room_off:room_off + 4] != b"ROOM":
            raise DecodeError(source, room_off, f"room {room} is not ROOM")
        yield room, room_off


def iter_bitmaps(la1: bytes, errors: list,
                 source: str = "LA1") -> Iterator[La1Bitmap]:
    """Yield every decodable RMIM/OBIM bitmap from ``DIG.LA1`` in file order.

    Undecodable resources append a ``DecodeError`` to ``errors`` (the oracle's
    ``LA1E`` records) and yield no bitmap.
    """
    for room, room_off in _iter_rooms(la1, source):
        yield from _process_room(la1, room_off, room, errors, source)
