import struct

import pytest

from digart import akos as A
from digart.errors import DecodeError
from tests.fixtures import make_fixtures as fx

chunk = fx.la1_chunk


def mk_akos(byle: bytes, w: int = 2, h: int = 2, codec: int = 1,
            num_colors: int = 16) -> bytes:
    """One room whose AKOS chunk holds a single cel with the given codec data."""
    akhd = chunk(b"AKHD", struct.pack("<HHHHHH", 1, 0, 1, 1, codec, 0))
    akpl = chunk(b"AKPL", bytes(num_colors))
    akci = chunk(b"AKCI", struct.pack("<HH", w, h))
    akcd = chunk(b"AKCD", byle)
    akof = chunk(b"AKOF", fx.le32(0) + fx.le16(0))
    akos = chunk(b"AKOS", akhd + akpl + akci + akcd + akof)
    room = chunk(b"ROOM", b"")
    lflf = chunk(b"LFLF", room + akos)
    loff = chunk(b"LOFF", bytes([1, 1]) + fx.le32(30))
    return chunk(b"LECF", loff + lflf)


def test_akos_cel_decoding_and_errors():
    # Column-major runs: col0 = colours 1,2; col1 = colours 3,3.
    errors: list = []
    cels = list(A.iter_cels(mk_akos(bytes([0x11, 0x21, 0x32])), errors))
    assert errors == []
    assert len(cels) == 1
    cel = cels[0]
    assert cel.name == "costume001_000"
    assert (cel.costume, cel.cel) == (1, 0)
    assert (cel.width, cel.height) == (2, 2)
    assert cel.transparent == 0
    assert cel.index == bytes([1, 3, 2, 3])

    errors = []
    cels = list(A.iter_cels(mk_akos(bytes(4), codec=7), errors))
    assert cels == []
    assert len(errors) == 1
    assert (errors[0].costume, errors[0].cel, errors[0].codec) == (1, 0, 7)

    with pytest.raises(DecodeError):
        list(A.iter_cels(b"NOPE" + fx.be32(4) + bytes(4), []))


@pytest.mark.game
def test_real_la1_cel_count(game_dir):
    la1 = (game_dir / "DIG.LA1").read_bytes()
    errors: list = []
    cels = list(A.iter_cels(la1, errors))
    print(f"DIG.LA1: {len(cels)} costume cels, {len(errors)} errors")
    assert len(cels) == 28490
    assert errors == []
    assert cels[0].name == "costume001_000"
