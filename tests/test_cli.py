"""CLI wiring tests against a synthetic, hermetic fake game bundle.

The fake bundle mirrors the real layout (``<app>/Contents/Resources/game/game``)
with a 2-frame SAN, a 1-glyph NUT and a minimal empty ``DIG.LA1`` (a valid
``LECF``/``LOFF`` with zero rooms, so LA1/AKOS yield zero bitmaps and zero
errors). No real game data is touched.
"""

import json
import struct
from pathlib import Path

from PIL import Image

from digart.cli import main
from tests.fixtures import make_fixtures as fx

PAL = bytes((i * 5) & 0xFF for i in range(768))


chunk = fx.la1_chunk


def empty_la1() -> bytes:
    """A valid LECF/LOFF container with zero rooms: no bitmaps, no errors."""
    return b"LECF" + struct.pack(">I", 17) + b"LOFF" + struct.pack(">I", 8) + b"\x00"


def obim_bomp_la1() -> bytes:
    """One room with a single 2x2 OBIM BOMP object sprite (index 255 transparent).

    The sprite's pixels are ``[255, 5, 6, 255]``; ``_decode_bomp`` reports
    ``transparent0=False`` but a BOMP OBIM's transparent index is 255, so it must
    be emitted RGBA with alpha 0 where the buffer held 255.
    """
    w = h = 2
    row0 = struct.pack("<H", 3) + bytes([2, 255, 5])   # literal run -> [255, 5]
    row1 = struct.pack("<H", 3) + bytes([2, 6, 255])   # literal run -> [6, 255]
    bomp = chunk(b"BOMP", bytes(2) + struct.pack("<HH", w, h) + bytes(4) + row0 + row1)
    imhd = chunk(b"IMHD", struct.pack("<IHHHHHH", 7, 63, 1, 0, 0, w, h))
    obim = chunk(b"OBIM", imhd + chunk(b"IM01", bomp))
    rmhd = chunk(b"RMHD", struct.pack("<IHHH", 7, w, h, 0))
    wrap = chunk(b"WRAP", chunk(b"OFFS", struct.pack("<I", 12)) + chunk(b"APAL", PAL))
    room = chunk(b"ROOM", rmhd + chunk(b"PALS", wrap) + obim)
    loff = chunk(b"LOFF", bytes([1, 1]) + struct.pack("<I", 30))
    return chunk(b"LECF", loff + chunk(b"LFLF", room))


def obim_smap_la1() -> bytes:
    """One room with a single 8x1 OBIM SMAP object sprite (RAW256, opaque).

    A non-transparent SMAP strip leaves ``transparent0=False`` and no transparent
    index, so the sprite must stay opaque RGB.
    """
    width, height = 8, 1
    off = 8 + 4 * (width // 8)
    smap = chunk(b"SMAP", struct.pack("<I", off) + bytes([1])
                 + bytes(range(1, width * height + 1)))
    imhd = chunk(b"IMHD", struct.pack("<IHHHHHH", 7, 63, 1, 0, 0, width, height))
    obim = chunk(b"OBIM", imhd + chunk(b"IM01", smap))
    rmhd = chunk(b"RMHD", struct.pack("<IHHH", 7, width, height, 0))
    wrap = chunk(b"WRAP", chunk(b"OFFS", struct.pack("<I", 12)) + chunk(b"APAL", PAL))
    room = chunk(b"ROOM", rmhd + chunk(b"PALS", wrap) + obim)
    loff = chunk(b"LOFF", bytes([1, 1]) + struct.pack("<I", 30))
    return chunk(b"LECF", loff + chunk(b"LFLF", room))


def akos_cdat_la1() -> bytes:
    """One room with a single 2x2 AKOS codec-5 (CDAT/BOMP) cel.

    The cel's pixels are ``[255, 7, 9, 255]``; its transparent index is 255, so
    it must be emitted RGBA with index 255 normalized to alpha 0.
    """
    row0 = struct.pack("<H", 3) + bytes([2, 255, 7])   # literal run -> [255, 7]
    row1 = struct.pack("<H", 3) + bytes([2, 9, 255])   # literal run -> [9, 255]
    akcd = chunk(b"AKCD", row0 + row1)
    akhd = chunk(b"AKHD", struct.pack("<HHHHHH", 1, 0, 1, 1, 5, 0))
    akpl = chunk(b"AKPL", bytes(16))
    akci = chunk(b"AKCI", struct.pack("<HH", 2, 2))
    akof = chunk(b"AKOF", struct.pack("<I", 0) + struct.pack("<H", 0))
    akos = chunk(b"AKOS", akhd + akpl + akci + akcd + akof)
    loff = chunk(b"LOFF", bytes([1, 1]) + struct.pack("<I", 30))
    return chunk(b"LECF", loff + chunk(b"LFLF", chunk(b"ROOM", b"") + akos))


def make_app(tmp_path: Path, san: bytes, nut: bytes, la1: bytes) -> Path:
    app = tmp_path / "The Dig.app"
    root = app / "Contents" / "Resources" / "game" / "game"
    (root / "VIDEO").mkdir(parents=True)
    (root / "VIDEO" / "SQ1.SAN").write_bytes(san)
    (root / "VIDEO" / "FONT0.NUT").write_bytes(nut)
    (root / "DIG.LA0").write_bytes(b"")
    (root / "DIG.LA1").write_bytes(la1)
    return app


def default_app(tmp_path: Path) -> Path:
    return make_app(
        tmp_path,
        san=fx.san([fx.frame(), fx.frame()], palette=PAL),
        nut=fx.mk_nut([(1, 4, 2, fx.codec1_payload())], PAL),
        la1=empty_la1(),
    )


def read_manifest(out: Path) -> dict:
    return json.loads((out / "manifest.json").read_text())


def test_extract_success_manifest_and_sidecars(tmp_path):
    out = tmp_path / "out"
    app = default_app(tmp_path / "bundle")

    assert main(["extract", "--game", str(app), "--out", str(out), "--jobs", "1"]) == 0

    doc = read_manifest(out)
    ids = [a["id"] for a in doc["assets"]]
    assert {"san:sq1:00000", "san:sq1:00001", "nut:font0:00000"} <= set(ids)
    assert len(ids) == len(set(ids)), "manifest ids must be unique"
    assert doc["counts"] == {
        "san_frames": 2, "nut_images": 1, "la1_bitmaps": 0, "errors": 0,
    }

    for asset in doc["assets"]:
        assert (out / asset["path"]).exists(), asset["path"]
    assert not (out / "_errors.json").exists()

    for h in {a["palette"] for a in doc["assets"]}:
        assert (out / "palettes" / f"{h}.json").exists()
        assert (out / "palettes" / f"{h}.png").exists()


def test_extract_errors_and_preflight(tmp_path, capsys):
    # missing bundle -> exit 2, message names VIDEO
    rc = main(["extract", "--game", str(tmp_path / "nope"), "--out",
               str(tmp_path / "out"), "--jobs", "1"])
    assert rc == 2 and "VIDEO" in capsys.readouterr().err

    # truncated SAN -> exit 1 with an _errors.json entry
    good = fx.san([fx.frame(), fx.frame()], palette=PAL)
    app = make_app(tmp_path / "truncated", san=good[:20],  # cut inside the AHDR chunk
                   nut=fx.mk_nut([(1, 4, 2, fx.codec1_payload())], PAL), la1=empty_la1())
    out = tmp_path / "out"
    assert main(["extract", "--game", str(app), "--out", str(out), "--jobs", "1"]) == 1
    doc = json.loads((out / "_errors.json").read_text())
    assert doc["count"] >= 1 and doc["errors"][0]["source"] == "VIDEO/SQ1.SAN"

    # invalid --only -> exit 2 naming the bad kind
    app = default_app(tmp_path / "bundle")
    rc = main(["extract", "--game", str(app), "--out", str(tmp_path / "out2"),
               "--only", "bogus", "--jobs", "1"])
    assert rc == 2 and "bogus" in capsys.readouterr().err


def test_extract_only_and_determinism(tmp_path):
    app = default_app(tmp_path / "bundle")
    out = tmp_path / "out"
    assert main(["extract", "--game", str(app), "--out", str(out),
                 "--only", "san", "--jobs", "1"]) == 0
    doc = read_manifest(out)
    assert doc["counts"]["san_frames"] == 2 and doc["counts"]["nut_images"] == 0
    assert not (out / "nut").exists()

    a, b = tmp_path / "a", tmp_path / "b"
    assert main(["extract", "--game", str(app), "--out", str(a), "--jobs", "1"]) == 0
    assert main(["extract", "--game", str(app), "--out", str(b), "--jobs", "1"]) == 0
    da, db = read_manifest(a), read_manifest(b)
    assert da["assets"] == db["assets"]
    assert da["counts"] == db["counts"]
    assert da["game_root"] == db["game_root"]
    assert (a / "san/SQ1/00000.png").read_bytes() == (b / "san/SQ1/00000.png").read_bytes()


def test_extract_transparency_and_stale_errors(tmp_path):
    # BOMP OBIM: transparent index 255 -> RGBA with alpha 0
    app = make_app(tmp_path / "bomp", san=b"", nut=b"", la1=obim_bomp_la1())
    out = tmp_path / "out_bomp"
    assert main(["extract", "--game", str(app), "--out", str(out),
                 "--only", "la1", "--jobs", "1"]) == 0
    asset = read_manifest(out)["assets"][0]
    assert asset["id"] == "la1:obj063_01" and asset["has_alpha"] is True
    im = Image.open(out / asset["path"])
    assert im.mode == "RGBA" and im.size == (2, 2)
    assert im.getpixel((0, 0))[3] == 0 and im.getpixel((1, 1))[3] == 0
    assert im.getpixel((1, 0))[3] == 255
    assert im.getpixel((1, 0))[:3] == tuple(PAL[5 * 3:5 * 3 + 3])
    assert im.getpixel((0, 1))[:3] == tuple(PAL[6 * 3:6 * 3 + 3])

    # non-transparent SMAP OBIM stays opaque RGB
    app = make_app(tmp_path / "smap", san=b"", nut=b"", la1=obim_smap_la1())
    out = tmp_path / "out_smap"
    assert main(["extract", "--game", str(app), "--out", str(out),
                 "--only", "la1", "--jobs", "1"]) == 0
    asset = read_manifest(out)["assets"][0]
    assert asset["id"] == "la1:obj063_01" and asset["has_alpha"] is False
    assert Image.open(out / asset["path"]).mode == "RGB"

    # AKOS CDAT cel: index 255 normalized to alpha 0
    app = make_app(tmp_path / "akos", san=b"", nut=b"", la1=akos_cdat_la1())
    out = tmp_path / "out_akos"
    assert main(["extract", "--game", str(app), "--out", str(out),
                 "--only", "akos", "--jobs", "1"]) == 0
    asset = read_manifest(out)["assets"][0]
    assert asset["id"] == "akos:costume001_000" and asset["has_alpha"] is True
    im = Image.open(out / asset["path"])
    assert im.mode == "RGBA" and im.size == (2, 2)
    assert im.getpixel((0, 0))[3] == 0 and im.getpixel((1, 1))[3] == 0
    assert im.getpixel((1, 0))[3] == 255 and im.getpixel((0, 1))[3] == 255

    # a stale _errors.json is removed by a clean run
    app = default_app(tmp_path / "clean")
    out = tmp_path / "out_clean"
    out.mkdir()
    (out / "_errors.json").write_text('{"count": 1, "errors": []}')
    assert main(["extract", "--game", str(app), "--out", str(out), "--jobs", "1"]) == 0
    assert not (out / "_errors.json").exists()
