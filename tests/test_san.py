import struct

from digart import san as S
from digart.errors import DecodeError
from tests.fixtures import make_fixtures as fx

PAL_A = bytes([1, 2, 3] * 256)
PAL_B = bytes([4, 5, 6] * 256)


def frames_of(*subs_per_frame):
    data = fx.san([fx.frame(*subs) for subs in subs_per_frame], PAL_A)
    return list(S.iter_frames(data))


def test_san_palette_state_machine():
    fs = frames_of((), ())
    assert len(fs) == 2
    assert fs[0].index == bytes(64000) and fs[0].palette == PAL_A
    assert fs[1].index == fs[0].index                       # repeat without drawing

    assert frames_of((fx.npal(PAL_B),))[0].palette == PAL_B  # NPAL replaces

    delta = struct.pack("<h", 0) * 768
    assert frames_of((fx.xpal(512, delta, PAL_B),))[0].palette == PAL_B  # XPAL cmd 512

    # cmd 0 stores deltas; cmd 256 applies (shifted += delta), pal = clip(shifted>>7)
    reader = S.SanReader(fx.san([fx.frame(fx.npal(bytes([100] * 768)))]), "?")
    next(reader.frames())
    reader._xpal(struct.pack("<HH", 0, 0) + struct.pack("<h", 128) * 768)
    reader._xpal(struct.pack("<HHH", 0, 256, 0))
    assert reader.pal[0] == 101
    reader._xpal(struct.pack("<HH", 0, 0) + struct.pack("<h", -128) * 768)
    reader._xpal(struct.pack("<HHH", 0, 256, 0))
    assert reader.pal[0] == 100


def test_san_container_errors_and_odd_chunks():
    data = fx.san([fx.frame(fx.be(b"ZZZZ", b"\x01\x02\x03\x04"))])
    r = S.SanReader(data)
    assert len(list(r.frames())) == 1
    assert r.skipped["ZZZZ"] == 1                           # unknown sub-chunk logged

    try:
        list(S.iter_frames(b"NUTS" + struct.pack(">I", 4) + b"\x00" * 4))
        assert False
    except DecodeError as e:
        assert e.offset == 0 and "ANIM" in e.reason

    # a 3-byte sub-chunk must not desync the walk (SAN pads to even)
    data = fx.san([fx.frame(fx.be(b"PSAD", b"\x01\x02\x03"), fx.npal(PAL_B))], PAL_A)
    assert list(S.iter_frames(data))[0].palette == PAL_B
