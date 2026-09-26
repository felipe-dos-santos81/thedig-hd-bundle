import json
from pathlib import Path

import digart
from PIL import Image

from digart.manifest import AssetRecord, ManifestBuilder, palette_hash, rec_id
from digart.pngout import write_indexed_png

W, H = 320, 200


def make_pal() -> bytes:
    return bytes(v for i in range(256) for v in (i, (i * 3) % 256, (i * 7) % 256))


def make_index() -> bytes:
    return bytes((x * 7 + y * 13) % 256 for y in range(H) for x in range(W))


def rgb_of(index: bytes, pal: bytes) -> bytes:
    return bytes(v for p in index for v in (pal[p * 3], pal[p * 3 + 1], pal[p * 3 + 2]))


def rgba_of(index: bytes, pal: bytes) -> bytes:
    return bytes(
        v
        for p in index
        for v in (pal[p * 3], pal[p * 3 + 1], pal[p * 3 + 2], 0 if p == 0 else 255)
    )


def san_record(pal_hash: str, frame: int) -> AssetRecord:
    return AssetRecord(
        id=rec_id("san", "SQ1.SAN", frame),
        kind="san_frame",
        source="VIDEO/SQ1.SAN",
        frame=frame,
        name=None,
        width=W,
        height=H,
        has_alpha=False,
        palette=pal_hash,
        path=f"san/SQ1/{frame:05d}.png",
    )


def test_manifest_schema_counts_and_palette_sidecars(tmp_path):
    pal = make_pal()
    h = palette_hash(pal)
    b = ManifestBuilder(tmp_path)
    assert b.record_palette(pal) == h
    assert b.record_palette(pal) == h                    # idempotent
    b.add(san_record(h, 0))
    b.add(san_record(h, 1))
    b.finalize("2026-09-24T12:00:00Z", "deadbeef", error_count=3)

    doc = json.loads((tmp_path / "manifest.json").read_text())
    assert list(doc) == [
        "tool", "tool_version", "extracted_at", "game_root", "counts", "assets",
    ]
    assert doc["tool"] == "thedig-textures"
    assert doc["tool_version"] == digart.__version__
    assert doc["extracted_at"] == "2026-09-24T12:00:00Z"
    assert doc["game_root"] == "deadbeef"
    assert doc["counts"] == {
        "san_frames": 2, "nut_images": 0, "la1_bitmaps": 0, "errors": 3,
    }
    assert doc["assets"][0]["id"] == "san:sq1:00000"
    assert list(doc["assets"][0]) == [
        "id", "kind", "source", "frame", "name", "width", "height",
        "has_alpha", "palette", "path",
    ]
    assert doc["assets"][1]["id"] == "san:sq1:00001"
    assert rec_id("san", "SQ1.SAN", 0) == "san:sq1:00000"
    assert rec_id("nut", "ROOM.NUT", 12) == "nut:room:00012"

    names = sorted(p.name for p in (tmp_path / "palettes").iterdir())
    assert names == [f"{h}.json", f"{h}.png"]

    colors = json.loads((tmp_path / "palettes" / f"{h}.json").read_text())
    assert len(colors) == 256
    assert all(len(c) == 3 for c in colors)
    assert colors[7] == [7, 21, 49]

    strip = Image.open(tmp_path / "palettes" / f"{h}.png")
    assert strip.size == (256, 1)
    assert strip.getpixel((7, 0)) == (7, 21, 49)

    obj = AssetRecord(id="la1:obj063_01", kind="la1_bitmap", source="DIG.LA1", frame=None,
                      name="obj063_01", width=8, height=4, has_alpha=True, palette=h,
                      path="la1/obj063_01.png", room=3, x=-8, y=16).to_dict()
    assert list(obj)[-4:] == ["path", "room", "x", "y"]
    assert (obj["room"], obj["x"], obj["y"]) == (3, -8, 16)
    assert "room" not in san_record(h, 0).to_dict()


def test_png_writers(tmp_path):
    pal, index = make_pal(), make_index()
    write_indexed_png(tmp_path, Path("san/SQ1/00000.png"), index, W, H, pal, False)
    im = Image.open(tmp_path / "san/SQ1/00000.png")
    assert im.mode == "RGB" and im.size == (W, H)
    assert im.tobytes() == rgb_of(index, pal)            # opaque PNG is lossless RGB

    write_indexed_png(tmp_path, Path("la1/room.png"), index, W, H, pal, transparent0=True)
    im = Image.open(tmp_path / "la1/room.png")
    assert im.mode == "RGBA"
    assert im.tobytes() == rgba_of(index, pal)
    assert index[0] == 0 and im.getpixel((0, 0))[3] == 0
    pos = next(i for i, p in enumerate(index) if p != 0)
    assert im.getpixel((pos % W, pos // W))[3] == 255

    write_indexed_png(tmp_path, Path("nut/room/img_000.png"), index, W, H, pal, transparent0=False)
    im = Image.open(tmp_path / "nut/room/img_000.png")
    assert im.mode == "RGB" and im.tobytes() == rgb_of(index, pal)


def test_determinism_byte_identical(tmp_path):
    pal, index = make_pal(), make_index()
    h = palette_hash(pal)
    for name in ("a", "b"):
        d = tmp_path / name
        b = ManifestBuilder(d)
        assert b.record_palette(pal) == h
        write_indexed_png(d, Path("san/SQ1/00000.png"), index, W, H, pal, False)
        b.add(san_record(h, 0))
        b.finalize("2026-09-24T12:00:00Z", "deadbeef")

    a, bb = tmp_path / "a", tmp_path / "b"
    for rel in (
        "manifest.json",
        "san/SQ1/00000.png",
        f"palettes/{h}.json",
        f"palettes/{h}.png",
    ):
        assert (a / rel).read_bytes() == (bb / rel).read_bytes(), rel
