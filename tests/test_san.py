import struct
from digart import san as S
from digart.errors import DecodeError
from tests.fixtures import make_fixtures as fx

PAL_A = bytes([1, 2, 3] * 256)
PAL_B = bytes([4, 5, 6] * 256)

def frames_of(*subs_per_frame):
    data = fx.san([fx.frame(*subs) for subs in subs_per_frame], PAL_A)
    return list(S.iter_frames(data))

def test_frame_repeats_without_drawing():
    fs = frames_of((), ())
    assert len(fs) == 2
    assert fs[0].index == bytes(64000) and fs[0].palette == PAL_A
    assert fs[1].index == fs[0].index

def test_npal_replaces_palette_before_snapshot():
    fs = frames_of((fx.npal(PAL_B),))
    assert fs[0].palette == PAL_B

def test_xpal_full_replace():
    delta = struct.pack("<h", 0) * 768
    fs = frames_of((fx.xpal(512, delta, PAL_B),))
    assert fs[0].palette == PAL_B

def test_xpal_delta_accumulates_and_shifts():
    # start from base color 100<<7=12800, delta +128 -> (12800+128)>>7 == 101
    init = fx.npal(bytes([100] * 768))
    setup = fx.frame(init)
    fs_reader = S.SanReader(fx.san([setup]), "?")
    it = fs_reader.frames(); next(it)                 # frame 0: pal=100
    fs_reader._xpal(struct.pack("<HH", 0, 0) + struct.pack("<h", 128) * 768)   # cmd 0: store delta
    fs_reader._xpal(struct.pack("<HHH", 0, 256, 0))                            # cmd 256: apply
    assert fs_reader.pal[0] == 101
    fs_reader._xpal(struct.pack("<HH", 0, 0) + struct.pack("<h", -128) * 768)  # shifted=101<<7 again
    fs_reader._xpal(struct.pack("<HHH", 0, 256, 0))
    assert fs_reader.pal[0] == 100                    # (12928-128)>>7 == 100

def test_unknown_subchunk_recorded_not_fatal():
    data = fx.san([fx.frame(fx.be(b"ZZZZ", b"\x01\x02\x03\x04"))])
    r = S.SanReader(data)
    assert len(list(r.frames())) == 1
    assert r.skipped["ZZZZ"] == 1

def test_bad_container_raises():
    try:
        list(S.iter_frames(b"NUTS" + struct.pack(">I", 4) + b"\x00" * 4))
        assert False
    except DecodeError as e:
        assert e.offset == 0 and "ANIM" in e.reason

def test_odd_chunk_sizes_advance_with_pad():
    data = fx.san([fx.frame(fx.npal(PAL_B + b"\x00")), fx.frame()], PAL_A)
    # npal payload 768 even; force an odd one via unknown subchunk of 3 bytes
    data = fx.san([fx.frame(fx.be(b"PSAD", b"\x01\x02\x03"), fx.npal(PAL_B))], PAL_A)
    fs = list(S.iter_frames(data))
    assert fs[0].palette == PAL_B                     # after the odd-size chunk
