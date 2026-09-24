import struct, zlib
from digart import san as S
from tests.fixtures import make_fixtures as fx

def runs(color: int, num: int) -> bytes:           # RLE opcodes covering num pixels (BOMP max run = 128)
    out = bytearray()
    while num:
        n = min(num, 128)
        out += bytes([((n - 1) << 1) | 1, color])
        num -= n
    return bytes(out)

def lit_zeros(n: int) -> bytes:                    # literal run of n zero bytes (BOMP max run = 128)
    return bytes([((n - 1) << 1)]) + bytes(n)

def fobj_payload(codec: int, left: int, top: int, w: int, h: int, rows: bytes) -> bytes:
    return struct.pack("<HhhHHHH", codec, left, top, w, h, 0, 0) + rows

def full_rows(color: int) -> bytes:
    enc = runs(color, 320)
    return b"".join(struct.pack("<H", len(enc)) + enc for _ in range(200))

def fullscreen(codec: int = 1, color: int = 0x42) -> bytes:
    if codec == 1:
        return fx.fsub(b"FOBJ", fobj_payload(1, 0, 0, 320, 200, full_rows(color)))
    raw = struct.pack("<HhhHHHH", 20, 0, 0, 320, 200, 0, 0) + bytes([color]) * 64000
    return fx.fsub(b"FOBJ", raw)

def test_rle_fill_then_snapshot():
    fs = list(S.iter_frames(fx.san([fx.frame(fx.npal(bytes(768))), fx.frame(fullscreen(1, 0x42))])))
    assert fs[1].index[0] == 0x42 and fs[1].index[-1] == 0x42

def test_index_zero_rows_keep_previous():
    # frame1: full 0x11; frame2: rows 0-1 = 0x22, row2 = literal zeros (keep), rows 3-199 = RLE 0x00 (keep)
    enc22, enc00 = runs(0x22, 320), runs(0x00, 320)
    zero_lit = lit_zeros(128) + lit_zeros(128) + lit_zeros(64)
    rows = (struct.pack("<H", len(enc22)) + enc22) * 2 + \
           struct.pack("<H", len(zero_lit)) + zero_lit + \
           b"".join(struct.pack("<H", len(enc00)) + enc00 for _ in range(197))
    f2 = fx.fsub(b"FOBJ", fobj_payload(1, 0, 0, 320, 200, rows))
    data = fx.san([fx.frame(fx.npal(bytes(768))),
                   fx.frame(fx.fsub(b"FOBJ", fobj_payload(1, 0, 0, 320, 200, full_rows(0x11)))),
                   fx.frame(f2)])
    fs = list(S.iter_frames(data))
    assert fs[1].index[:320] == bytes([0x11]) * 320
    assert fs[2].index[:320] == bytes([0x22]) * 320          # explicit rows
    assert fs[2].index[640:960] == bytes([0x11]) * 320       # literal-zero row keeps 0x11
    assert fs[2].index[960:] == bytes([0x11]) * (64000 - 960) # RLE color-0 rows keep 0x11

def test_small_obj_skipped():
    small = fx.fsub(b"FOBJ", fobj_payload(1, 0, 0, 300, 200, b""))
    r = S.SanReader(fx.san([fx.frame(small)]))
    fs = list(r.frames())
    assert fs[0].index == bytes(64000) and r.skipped["skip_small"] == 1

def test_codec20_uncompressed():
    fs = list(S.iter_frames(fx.san([fx.frame(fx.npal(bytes(768))), fx.frame(fullscreen(20, 0x33))])))
    assert fs[1].index[0] == 0x33 and fs[1].index[-1] == 0x33

def test_zfb_roundtrip():
    inner = fobj_payload(1, 0, 0, 320, 200, full_rows(0x55))
    z = struct.pack(">I", len(inner)) + zlib.compress(inner, 9)
    fs = list(S.iter_frames(fx.san([fx.frame(fx.fsub(b"ZFOB", z))])))
    assert fs[0].index[0] == 0x55
