import struct

import pytest

from digart import san as S
from digart.codec37 import DeltaBlocksDecoder
from digart.errors import DecodeError
from tests.fixtures import make_fixtures as fx

W, H = 320, 200
FRAME = W * H


def codec_header(variant: int, table: int = 0, seq: int = 0,
                 decoded_size: int = 0, mask: int = 0) -> bytes:
    """16-byte codec-37 sub-header: variant, table, seq, size, 4 pad, mask, 3 pad."""
    return (bytes([variant, table]) + struct.pack("<H", seq)
            + struct.pack("<I", decoded_size) + bytes(4)
            + bytes([mask]) + bytes(3))


def fobj(codec: int, w: int, h: int, data: bytes, left: int = 0, top: int = 0,
         objid: int = 0, parm2: int = 0) -> bytes:
    hdr = struct.pack("<HhhHHHH", codec, left, top, w, h, objid, parm2)
    return fx.be(b"FOBJ", hdr + data)


def test_delta_blocks_decoder_variants():
    d = DeltaBlocksDecoder(W, H)

    body = bytes(range(256)) * 250                     # 64000 bytes
    dst = bytearray(FRAME)
    d.decode(dst, codec_header(0, 0, 0, FRAME, 0) + body)
    assert bytes(dst) == body                          # variant 0: raw copy

    dst = bytearray(b"\x55" * FRAME)
    d.decode(dst, codec_header(0, 0, 0, 4, 0) + b"\xAA\xBB\xCC\xDD")
    assert bytes(dst[:4]) == b"\xAA\xBB\xCC\xDD" and bytes(dst[4:]) == bytes(FRAME - 4)

    dst = bytearray(FRAME)
    d.decode(dst, codec_header(2, 0, 0, 8, 0) + bytes([0b0000_1111, 0x77]))
    assert bytes(dst[:8]) == bytes([0x77]) * 8 and bytes(dst[8:]) == bytes(FRAME - 8)

    line = bytes([0xFF, 0x33]) * 500                   # 500 RLE runs of 128 == 64000
    dst = bytearray(FRAME)
    d.decode(dst, codec_header(2, 0, 0, FRAME, 0) + line)
    assert bytes(dst) == bytes([0x33]) * FRAME         # variant 2: BOMP rows

    blocks = 80 * 50
    stream = b"".join(bytes([0xFD, i & 0xFF]) for i in range(blocks))
    dst = bytearray(FRAME)
    d.decode(dst, codec_header(3, 0, 0, len(stream), 4) + stream)
    assert dst[0] == 0 and dst[3] == 0 and dst[320 * 3 + 3] == 0
    assert dst[4] == 1 and dst[320 * 3 + 7] == 1
    assert bytes(dst) != bytes(FRAME)                  # variant 3: FDFE literal 4x4

    dst = bytearray(FRAME)
    d.decode(dst, codec_header(4, 0, 0, len(stream), 4) + stream)
    assert dst[0] == 0 and dst[4] == 1 and dst[7] == 1 and dst[320 * 3 + 7] == 1

    a = DeltaBlocksDecoder(W, H)
    b = DeltaBlocksDecoder(W, H)
    a.decode(bytearray(FRAME), codec_header(0, 0, 0, FRAME, 0) + bytes([0x11]) * FRAME)
    dst = bytearray(FRAME)
    b.decode(dst, codec_header(0, 0, 0, FRAME, 0) + bytes([0x22]) * FRAME)
    assert bytes(dst) == bytes([0x22]) * FRAME         # instances are independent


def _read_one(*subs, palette: bytes = bytes(768)):
    r = S.SanReader(fx.san([fx.frame(*subs)], palette), "synthetic")
    return r, list(r.frames())


def test_sanreader_fobj_guards_and_dispatch():
    payload = fobj(37, 100, 100, codec_header(0, 0, 0, 4, 0) + b"\x01\x02\x03\x04")
    r, frames = _read_one(payload)
    assert frames[0].index == bytes(FRAME) and r.skipped["skip_small"] == 1

    r, frames = _read_one(fobj(37, 400, 200, b""))
    assert frames[0].index == bytes(FRAME) and r.skipped["skip_big"] == 1

    body = bytes([0x5A]) * FRAME
    r, frames = _read_one(fobj(37, W, H, codec_header(0, 0, 0, FRAME, 0) + body))
    assert frames[0].index == body and r.skipped == {}

    with pytest.raises(DecodeError) as exc:
        _read_one(fobj(99, W, H, codec_header(0, 0, 0, FRAME, 0) + bytes(FRAME)))
    assert "unsupported codec 99" in exc.value.reason


def test_sanreader_codec37_is_stateful_across_frames():
    # frame 0 seeds the back buffer; frame 1 must see the persistent decoder state.
    body0 = bytes([0x10]) * FRAME
    f0 = fobj(37, W, H, codec_header(0, 0, 0, FRAME, 0) + body0)
    f1 = fobj(37, W, H, codec_header(0, 0, 0, FRAME, 0) + bytes([0x20]) * FRAME)
    r = S.SanReader(fx.san([fx.frame(f0), fx.frame(f1)]), "synthetic")
    frames = list(r.frames())
    assert frames[0].index == body0
    assert frames[1].index == bytes([0x20]) * FRAME
