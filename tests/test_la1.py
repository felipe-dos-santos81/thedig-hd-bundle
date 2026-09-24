import struct

import pytest

from digart import la1 as L
from digart.errors import DecodeError
from tests.fixtures import make_fixtures as fx

PAL = bytes((i * 7) & 0xFF for i in range(768))
chunk = fx.la1_chunk


def mk_smap(codec: int, strip: bytes, w: int, h: int) -> bytes:
    """SMAP with a single strip whose codec byte sits at payload[offset[0]]."""
    numstrips = w // 8
    off = 8 + 4 * numstrips
    return chunk(b"SMAP", fx.le32(off) + bytes([codec]) + strip)


def mk_la1(pal: bytes = PAL, w: int = 8, h: int = 2, codec: int = 1,
           strip: bytes | None = None, room: int = 1) -> bytes:
    """One room with RMHD + PALS + RMIM/IM00/SMAP (RAW256 by default)."""
    if strip is None:
        strip = bytes(range(1, w * h + 1))
    im00 = chunk(b"IM00", mk_smap(codec, strip, w, h))
    rmim = chunk(b"RMIM", chunk(b"RMIH", bytes(4)) + im00)
    rmhd = chunk(b"RMHD", struct.pack("<IHHH", 7, w, h, 0))
    wrap = chunk(b"WRAP", chunk(b"OFFS", fx.le32(12)) + chunk(b"APAL", pal))
    room_body = chunk(b"ROOM", rmhd + chunk(b"PALS", wrap) + rmim)
    lflf = chunk(b"LFLF", room_body)
    # LECF hdr 8 + LOFF chunk 14 + LFLF hdr 8 == the ROOM (LFLF payload) offset.
    loff = chunk(b"LOFF", bytes([1, room]) + fx.le32(30))
    return chunk(b"LECF", loff + lflf)


def _wrap_room(room_body: bytes) -> bytes:
    loff = chunk(b"LOFF", bytes([1, 1]) + fx.le32(30))
    return chunk(b"LECF", loff + chunk(b"LFLF", room_body))


def test_la1_room_and_object_bitmaps():
    errors: list = []
    bitmaps = list(L.iter_bitmaps(mk_la1(), errors))
    assert errors == []
    assert len(bitmaps) == 1
    bmp = bitmaps[0]
    assert bmp.name == "room001"
    assert (bmp.width, bmp.height) == (8, 2)
    assert bmp.palette == PAL
    assert bmp.index == bytes(range(1, 17))
    assert bmp.transparent0 is False                    # RAW256 is opaque

    # two strips: RAW256 (opaque) then ZIGZAG_VT6 (transparent) -> OR is True
    w = 16
    numstrips = w // 8
    off0 = 8 + 4 * numstrips
    strip0 = bytes([1]) + bytes(range(1, 9))
    off1 = off0 + len(strip0)
    payload = fx.le32(off0) + fx.le32(off1) + strip0 + bytes([36]) + bytes([5, 0, 0, 0, 0, 0, 0, 0])
    rmim = chunk(b"RMIM", chunk(b"RMIH", bytes(4)) + chunk(b"IM00", chunk(b"SMAP", payload)))
    rmhd = chunk(b"RMHD", struct.pack("<IHHH", 7, w, 1, 0))
    wrap = chunk(b"WRAP", chunk(b"OFFS", fx.le32(12)) + chunk(b"APAL", PAL))
    errors = []
    room = _wrap_room(chunk(b"ROOM", rmhd + chunk(b"PALS", wrap) + rmim))
    bitmaps = list(L.iter_bitmaps(room, errors))
    assert errors == []
    assert bitmaps[0].transparent0 is True

    # one room with a single 8x1 OBIM BOMP object sprite -> name obj063_01
    w, h = 8, 1
    bomp_data = bytes([(w - 1) << 1]) + bytes(range(1, w + 1))  # literal run of 8
    row = struct.pack("<H", len(bomp_data)) + bomp_data
    bomp = chunk(b"BOMP", bytes(2) + struct.pack("<HH", w, h) + bytes(4) + row)
    imhd = chunk(b"IMHD", struct.pack("<IHHHHHH", 7, 63, 1, 0, 0, w, h))
    obim = chunk(b"OBIM", imhd + chunk(b"IM01", bomp))
    rmhd = chunk(b"RMHD", struct.pack("<IHHH", 7, w, h, 0))
    errors = []
    room = _wrap_room(chunk(b"ROOM", rmhd + chunk(b"PALS", wrap) + obim))
    bitmaps = list(L.iter_bitmaps(room, errors))
    assert errors == []
    assert len(bitmaps) == 1
    assert bitmaps[0].name == "obj063_01"
    assert bitmaps[0].index == bytes(range(1, 9))
    assert bitmaps[0].transparent0 is False


def test_la1_errors():
    # NMAJMIN_H4 (134) maps to the untranscribed drawStripHE -> LA1E.
    errors: list = []
    bitmaps = list(L.iter_bitmaps(mk_la1(codec=134, strip=bytes(64)), errors))
    assert bitmaps == []
    assert len(errors) == 1
    assert errors[0].offset == 880                      # offset of the IM00 chunk
    assert errors[0].reason == "unsupported SMAP codec"

    with pytest.raises(DecodeError):
        list(L.iter_bitmaps(b"NOPE" + fx.be32(4) + bytes(4), []))


@pytest.mark.game
def test_real_la1_matches_census(game_dir):
    la1 = (game_dir / "DIG.LA1").read_bytes()
    errors: list = []
    bitmaps = list(L.iter_bitmaps(la1, errors))
    assert len(bitmaps) == 753
    assert bitmaps[0].name == "room001"
    assert (bitmaps[0].width, bitmaps[0].height) == (320, 200)
    assert errors == []
