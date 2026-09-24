"""Deterministic manifest and palette-sidecar generation."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .pngout import write_palette_png

TOOL = "thedig-textures"

_COUNT_KEYS = {
    "san_frame": "san_frames",
    "nut_image": "nut_images",
    "la1_bitmap": "la1_bitmaps",
}


def rec_id(kind: str, source: str, frame: int) -> str:
    stem = Path(source).stem.lower()
    return f"{kind}:{stem}:{frame:05d}"


def palette_hash(pal: bytes) -> str:
    return hashlib.sha256(pal).hexdigest()


@dataclass
class AssetRecord:
    id: str
    kind: str
    source: str
    frame: int | None
    name: str | None
    width: int
    height: int
    has_alpha: bool
    palette: str
    path: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "source": self.source,
            "frame": self.frame,
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "has_alpha": self.has_alpha,
            "palette": self.palette,
            "path": self.path,
        }


class ManifestBuilder:
    """Collects asset records and writes ``manifest.json`` + palette sidecars."""

    def __init__(self, out_dir: Path):
        self.out_dir = Path(out_dir)
        self.assets: list[AssetRecord] = []
        self._palettes: set[str] = set()

    def record_palette(self, pal: bytes) -> str:
        h = palette_hash(pal)
        if h in self._palettes:
            return h
        self._palettes.add(h)
        pal_dir = self.out_dir / "palettes"
        pal_dir.mkdir(parents=True, exist_ok=True)
        colors = [[pal[i * 3], pal[i * 3 + 1], pal[i * 3 + 2]] for i in range(256)]
        (pal_dir / f"{h}.json").write_text(
            json.dumps(colors, indent=2) + "\n", encoding="utf-8"
        )
        write_palette_png(pal_dir / f"{h}.png", pal)
        return h

    def add(self, rec: AssetRecord) -> None:
        self.assets.append(rec)

    def finalize(self, extracted_at: str, game_root_hash: str,
                 error_count: int = 0) -> None:
        counts = {"san_frames": 0, "nut_images": 0, "la1_bitmaps": 0,
                  "errors": error_count}
        for rec in self.assets:
            counts[_COUNT_KEYS[rec.kind]] += 1
        doc = {
            "tool": TOOL,
            "tool_version": __version__,
            "extracted_at": extracted_at,
            "game_root": game_root_hash,
            "counts": counts,
            "assets": [r.to_dict() for r in self.assets],
        }
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "manifest.json").write_text(
            json.dumps(doc, indent=2) + "\n", encoding="utf-8"
        )
