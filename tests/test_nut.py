import struct

import pytest

from digart import nut as N
from digart.errors import DecodeError
from tests.fixtures import make_fixtures as fx

PAL = bytes([1, 2, 3] * 256)


def codec44_payload() -> bytes:
    """Two rows for a 4x2 glyph: a full run, then a run after a 1-pixel skip."""
    body0 = struct.pack("<H", 0) + struct.pack("<H", 3) + bytes([10, 11, 12, 13])
    body1 = struct.pack("<H", 1) + struct.pack("<H", 2) + bytes([30, 31, 32])
    return struct.pack("<H", len(body0)) + body0 + struct.pack("<H", len(body1)) + body1


def test_nut_glyph_decoding_and_names():
    imgs = list(N.iter_images(fx.mk_nut([(1, 4, 2, fx.codec1_payload())], PAL), "/x/FONT0.NUT"))
    assert len(imgs) == 1
    img = imgs[0]
    assert img.name == "font0:000"
    assert (img.width, img.height) == (4, 2)
    assert img.palette == PAL
    assert img.transparent == 0
    assert img.index == bytes([5, 6, 7, 8, 3, 3, 3, 3])

    imgs = list(N.iter_images(fx.mk_nut([(44, 4, 2, codec44_payload())], PAL), "SMLFONT.NUT"))
    assert len(imgs) == 1
    img = imgs[0]
    assert img.name == "smlfont:000"
    assert (img.width, img.height) == (4, 2)
    assert img.palette == PAL
    assert img.transparent == 2
    # index 0 is skipped, so it keeps the codec-44 transparency fill (2)
    assert img.index == bytes([10, 11, 12, 13, 2, 30, 31, 32])

    data = fx.mk_nut([(1, 4, 2, fx.codec1_payload()), (44, 4, 2, codec44_payload())], PAL)
    names = [img.name for img in N.iter_images(data, "/x/FONT0.NUT")]
    assert names == ["font0:000", "font0:001"]


def test_nut_errors():
    data = fx.mk_nut([(7, 2, 2, bytes(4))])
    with pytest.raises(DecodeError) as exc:
        list(N.iter_images(data, "bad.nut"))
    assert "codec 7" in exc.value.reason

    with pytest.raises(DecodeError) as exc:
        list(N.iter_images(b"NUTS" + struct.pack(">I", 4) + bytes(4), "bad.nut"))
    assert exc.value.offset == 0 and "ANIM" in exc.value.reason

    data = bytearray(fx.mk_nut([(1, 4, 2, fx.codec1_payload())]))
    frme_off = 8 + 8 + 0x31A            # ANIM header + font AHDR chunk (even size)
    data[frme_off:frme_off + 4] = b"XXXX"
    with pytest.raises(DecodeError) as exc:
        list(N.iter_images(bytes(data), "bad.nut"))
    assert "FRME" in exc.value.reason
