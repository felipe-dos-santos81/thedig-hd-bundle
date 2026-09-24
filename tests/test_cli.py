"""CLI wiring tests against a synthetic, hermetic fake game bundle.

The fake bundle mirrors the real layout (``<app>/Contents/Resources/game/game``)
with a 2-frame SAN, a 1-glyph NUT and a minimal empty ``DIG.LA1`` (a valid
``LECF``/``LOFF`` with zero rooms, so LA1/AKOS yield zero bitmaps and zero
errors). No real game data is touched.
"""

import json
import struct
from pathlib import Path

from digart.cli import main
from tests.fixtures import make_fixtures as fx

PAL = bytes((i * 5) & 0xFF for i in range(768))


def codec1_payload() -> bytes:
    """Two rows for a 4x2 glyph (literal run, then an RLE run)."""
    row0 = struct.pack("<H", 5) + bytes([0x06, 5, 6, 7, 8])
    row1 = struct.pack("<H", 2) + bytes([0x07, 3])
    return row0 + row1


def empty_la1() -> bytes:
    """A valid LECF/LOFF container with zero rooms: no bitmaps, no errors."""
    return b"LECF" + struct.pack(">I", 17) + b"LOFF" + struct.pack(">I", 8) + b"\x00"


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
        nut=fx.mk_nut([(1, 4, 2, codec1_payload())], PAL),
        la1=empty_la1(),
    )


def read_manifest(out: Path) -> dict:
    return json.loads((out / "manifest.json").read_text())


def test_extract_success_manifest_ids_and_paths(tmp_path):
    app = default_app(tmp_path)
    out = tmp_path / "out"

    assert main(["extract", "--game", str(app), "--out", str(out), "--jobs", "1"]) == 0

    doc = read_manifest(out)
    ids = [a["id"] for a in doc["assets"]]
    assert "san:sq1:00000" in ids
    assert "san:sq1:00001" in ids
    assert "nut:font0:00000" in ids
    assert len(ids) == len(set(ids)), "manifest ids must be unique"

    assert doc["counts"]["san_frames"] == 2
    assert doc["counts"]["nut_images"] == 1
    assert doc["counts"]["la1_bitmaps"] == 0
    assert doc["counts"]["errors"] == 0

    for asset in doc["assets"]:
        assert (out / asset["path"]).exists(), asset["path"]
    assert not (out / "_errors.json").exists()


def test_extract_writes_palette_sidecars(tmp_path):
    app = default_app(tmp_path)
    out = tmp_path / "out"
    assert main(["extract", "--game", str(app), "--out", str(out), "--jobs", "1"]) == 0

    doc = read_manifest(out)
    palettes = {a["palette"] for a in doc["assets"]}
    for h in palettes:
        assert (out / "palettes" / f"{h}.json").exists()
        assert (out / "palettes" / f"{h}.png").exists()


def test_missing_bundle_exit_2_mentions_video(tmp_path, capsys):
    rc = main(["extract", "--game", str(tmp_path / "nope"), "--out",
               str(tmp_path / "out"), "--jobs", "1"])
    assert rc == 2
    assert "VIDEO" in capsys.readouterr().err


def test_truncated_san_records_error_and_exit_1(tmp_path):
    good = fx.san([fx.frame(), fx.frame()], palette=PAL)
    app = make_app(tmp_path, san=good[:20],  # cut inside the AHDR chunk
                   nut=fx.mk_nut([(1, 4, 2, codec1_payload())], PAL),
                   la1=empty_la1())
    out = tmp_path / "out"

    assert main(["extract", "--game", str(app), "--out", str(out), "--jobs", "1"]) == 1

    doc = json.loads((out / "_errors.json").read_text())
    assert doc["count"] >= 1
    assert doc["errors"][0]["source"] == "VIDEO/SQ1.SAN"


def test_only_limits_extraction(tmp_path):
    app = default_app(tmp_path)
    out = tmp_path / "out"
    assert main(["extract", "--game", str(app), "--out", str(out),
                 "--only", "san", "--jobs", "1"]) == 0

    doc = read_manifest(out)
    assert doc["counts"]["san_frames"] == 2
    assert doc["counts"]["nut_images"] == 0
    assert not (out / "nut").exists()


def test_invalid_only_exit_2(tmp_path, capsys):
    app = default_app(tmp_path)
    rc = main(["extract", "--game", str(app), "--out", str(tmp_path / "out"),
               "--only", "bogus", "--jobs", "1"])
    assert rc == 2
    assert "bogus" in capsys.readouterr().err


def test_extract_is_deterministic(tmp_path):
    app = default_app(tmp_path)
    a, b = tmp_path / "a", tmp_path / "b"
    assert main(["extract", "--game", str(app), "--out", str(a), "--jobs", "1"]) == 0
    assert main(["extract", "--game", str(app), "--out", str(b), "--jobs", "1"]) == 0

    da, db = read_manifest(a), read_manifest(b)
    assert da["assets"] == db["assets"]
    assert da["counts"] == db["counts"]
    assert da["game_root"] == db["game_root"]
    assert (a / "san/SQ1/00000.png").read_bytes() == (b / "san/SQ1/00000.png").read_bytes()
