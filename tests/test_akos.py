import struct

import pytest

from digart import akos as A
from digart.errors import DecodeError


def be32(n: int) -> bytes:
    return struct.pack(">I", n)


def le32(n: int) -> bytes:
    return struct.pack("<I", n)


def le16(n: int) -> bytes:
    return struct.pack("<H", n)


def chunk(tag: bytes, payload: bytes) -> bytes:
    """Header-inclusive chunk: tag + u32BE size (8 + payload), no padding."""
    return tag + be32(8 + len(payload)) + payload


def mk_akos(byle: bytes, w: int = 2, h: int = 2, codec: int = 1,
            num_colors: int = 16) -> bytes:
    """One room whose AKOS chunk holds a single cel with the given codec data."""
    akhd = chunk(b"AKHD", struct.pack("<HHHHHH", 1, 0, 1, 1, codec, 0))
    akpl = chunk(b"AKPL", bytes(num_colors))
    akci = chunk(b"AKCI", struct.pack("<HH", w, h))
    akcd = chunk(b"AKCD", byle)
    akof = chunk(b"AKOF", le32(0) + le16(0))
    akos = chunk(b"AKOS", akhd + akpl + akci + akcd + akof)
    room = chunk(b"ROOM", b"")
    lflf = chunk(b"LFLF", room + akos)
    loff = chunk(b"LOFF", bytes([1, 1]) + le32(30))
    return chunk(b"LECF", loff + lflf)


def test_byle_cel_pixels():
    # Column-major runs: col0 = colours 1,2; col1 = colours 3,3.
    la1 = mk_akos(bytes([0x11, 0x21, 0x32]))
    errors: list = []
    cels = list(A.iter_cels(b"", la1, errors))
    assert errors == []
    assert len(cels) == 1
    cel = cels[0]
    assert cel.name == "costume001_000"
    assert (cel.costume, cel.cel) == (1, 0)
    assert (cel.width, cel.height) == (2, 2)
    assert cel.transparent == 0
    assert cel.index == bytes([1, 3, 2, 3])


def test_unknown_codec_records_error():
    la1 = mk_akos(bytes(4), codec=7)
    errors: list = []
    cels = list(A.iter_cels(b"", la1, errors))
    assert cels == []
    assert len(errors) == 1
    assert (errors[0].costume, errors[0].cel, errors[0].codec) == (1, 0, 7)


def test_bad_container_raises():
    with pytest.raises(DecodeError):
        list(A.iter_cels(b"", b"NOPE" + be32(4) + bytes(4), []))


@pytest.mark.game
def test_real_la1_cel_count(game_dir):
    la0 = (game_dir / "DIG.LA0").read_bytes()
    la1 = (game_dir / "DIG.LA1").read_bytes()
    errors: list = []
    cels = list(A.iter_cels(la0, la1, errors))
    print(f"DIG.LA1: {len(cels)} costume cels, {len(errors)} errors")
    assert len(cels) == 28490
    assert errors == []
    assert cels[0].name == "costume001_000"
