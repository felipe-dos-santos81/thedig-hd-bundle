import struct

import pytest

from digart import la1 as L
from digart.errors import DecodeError

PAL = bytes((i * 7) & 0xFF for i in range(768))


def be32(n: int) -> bytes:
    return struct.pack(">I", n)


def le32(n: int) -> bytes:
    return struct.pack("<I", n)


def chunk(tag: bytes, payload: bytes) -> bytes:
    """Header-inclusive chunk: tag + u32BE size (8 + payload), no padding."""
    return tag + be32(8 + len(payload)) + payload


def mk_smap(codec: int, strip: bytes, w: int, h: int) -> bytes:
    """SMAP with a single strip whose codec byte sits at payload[offset[0]]."""
    numstrips = w // 8
    off = 8 + 4 * numstrips
    return chunk(b"SMAP", le32(off) + bytes([codec]) + strip)


def mk_la1(pal: bytes = PAL, w: int = 8, h: int = 2, codec: int = 1,
           strip: bytes | None = None, room: int = 1) -> bytes:
    """One room with RMHD + PALS + RMIM/IM00/SMAP (RAW256 by default)."""
    if strip is None:
        strip = bytes(range(1, w * h + 1))
    im00 = chunk(b"IM00", mk_smap(codec, strip, w, h))
    rmim = chunk(b"RMIM", chunk(b"RMIH", bytes(4)) + im00)
    rmhd = chunk(b"RMHD", struct.pack("<IHHH", 7, w, h, 0))
    wrap = chunk(b"WRAP", chunk(b"OFFS", le32(12)) + chunk(b"APAL", pal))
    room_body = chunk(b"ROOM", rmhd + chunk(b"PALS", wrap) + rmim)
    lflf = chunk(b"LFLF", room_body)
    # LECF hdr 8 + LOFF chunk 14 + LFLF hdr 8 == the ROOM (LFLF payload) offset.
    loff = chunk(b"LOFF", bytes([1, room]) + le32(30))
    return chunk(b"LECF", loff + lflf)


def test_raw256_room_bitmap_pixels_and_palette():
    la1 = mk_la1()
    errors: list = []
    bitmaps = list(L.iter_bitmaps(b"", la1, errors))
    assert errors == []
    assert len(bitmaps) == 1
    bmp = bitmaps[0]
    assert bmp.name == "room001"
    assert (bmp.width, bmp.height) == (8, 2)
    assert bmp.palette == PAL
    assert bmp.index == bytes(range(1, 17))
    assert bmp.transparent0 is False


def test_transparent0_is_or_of_strip_flags():
    # Two strips: RAW256 (opaque) then ZIGZAG_VT6 (transparent) -> OR is True.
    w = 16
    vt_strip = bytes([5, 0, 0, 0, 0, 0, 0, 0])
    raw_strip = bytes(range(1, 9))
    numstrips = w // 8
    off0 = 8 + 4 * numstrips
    strip0 = bytes([1]) + raw_strip
    off1 = off0 + len(strip0)
    payload = le32(off0) + le32(off1) + strip0 + bytes([36]) + vt_strip
    smap = chunk(b"SMAP", payload)
    im00 = chunk(b"IM00", smap)
    rmim = chunk(b"RMIM", chunk(b"RMIH", bytes(4)) + im00)
    rmhd = chunk(b"RMHD", struct.pack("<IHHH", 7, w, 1, 0))
    wrap = chunk(b"WRAP", chunk(b"OFFS", le32(12)) + chunk(b"APAL", PAL))
    room_body = chunk(b"ROOM", rmhd + chunk(b"PALS", wrap) + rmim)
    lflf = chunk(b"LFLF", room_body)
    loff = chunk(b"LOFF", bytes([1, 1]) + le32(30))
    la1 = chunk(b"LECF", loff + lflf)

    errors: list = []
    bitmaps = list(L.iter_bitmaps(b"", la1, errors))
    assert errors == []
    assert bitmaps[0].transparent0 is True


def test_unsupported_codec_records_error_and_skips_bitmap():
    # NMAJMIN_H4 (134) maps to the untranscribed drawStripHE -> LA1E.
    la1 = mk_la1(codec=134, strip=bytes(64))
    errors: list = []
    bitmaps = list(L.iter_bitmaps(b"", la1, errors))
    assert bitmaps == []
    assert len(errors) == 1
    # Offset of the IM00 chunk; the oracle emits LA1E at the same offset.
    assert errors[0].offset == 880
    assert errors[0].reason == "unsupported SMAP codec"


def test_obim_bomp_bitmap_pixels_and_name():
    w, h = 8, 1
    bomp_data = bytes([(w - 1) << 1]) + bytes(range(1, w + 1))  # literal run of 8
    row = struct.pack("<H", len(bomp_data)) + bomp_data
    bomp = chunk(b"BOMP", bytes(2) + struct.pack("<HH", w, h) + bytes(4) + row)
    imhd = chunk(b"IMHD", struct.pack("<IHHHHHH", 7, 63, 1, 0, 0, w, h))
    obim = chunk(b"OBIM", imhd + chunk(b"IM01", bomp))
    rmhd = chunk(b"RMHD", struct.pack("<IHHH", 7, w, h, 0))
    wrap = chunk(b"WRAP", chunk(b"OFFS", le32(12)) + chunk(b"APAL", PAL))
    room_body = chunk(b"ROOM", rmhd + chunk(b"PALS", wrap) + obim)
    lflf = chunk(b"LFLF", room_body)
    loff = chunk(b"LOFF", bytes([1, 1]) + le32(30))
    la1 = chunk(b"LECF", loff + lflf)

    errors: list = []
    bitmaps = list(L.iter_bitmaps(b"", la1, errors))
    assert errors == []
    assert len(bitmaps) == 1
    assert bitmaps[0].name == "obj063_01"
    assert bitmaps[0].index == bytes(range(1, 9))
    assert bitmaps[0].transparent0 is False


def test_bad_container_raises():
    with pytest.raises(DecodeError):
        list(L.iter_bitmaps(b"", b"NOPE" + be32(4) + bytes(4), []))


@pytest.mark.game
def test_real_la1_matches_census(game_dir):
    la0 = (game_dir / "DIG.LA0").read_bytes()
    la1 = (game_dir / "DIG.LA1").read_bytes()
    errors: list = []
    bitmaps = list(L.iter_bitmaps(la0, la1, errors))
    assert len(bitmaps) == 753
    assert bitmaps[0].name == "room001"
    assert (bitmaps[0].width, bitmaps[0].height) == (320, 200)
    assert errors == []
