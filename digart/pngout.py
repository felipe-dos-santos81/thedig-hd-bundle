"""Deterministic PNG output for indexed bitmaps and palette strips."""

from pathlib import Path

from PIL import Image

from .san import FRAME_H, FRAME_W, SanFrame


def _save_rgb(path: Path, index: bytes, w: int, h: int, pal: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.frombytes("P", (w, h), index)
    im.putpalette(pal)
    im.convert("RGB").save(path, optimize=False)


def _save_rgba(path: Path, index: bytes, w: int, h: int, pal: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.frombytes("P", (w, h), index)
    im.putpalette(pal)
    rgba = im.convert("RGBA")
    alpha = index.translate(bytes(0 if i == 0 else 255 for i in range(256)))
    rgba.putalpha(Image.frombytes("L", (w, h), alpha))
    rgba.save(path, optimize=False)


def write_san_png(out_dir: Path, rel: Path, frame: SanFrame) -> None:
    """Write an opaque SAN back-buffer frame (index 0 is not transparent)."""
    _save_rgb(Path(out_dir) / rel, frame.index, FRAME_W, FRAME_H, frame.palette)


def write_indexed_png(out_dir: Path, rel: Path, index: bytes, w: int, h: int,
                      pal: bytes, transparent0: bool) -> None:
    """Write an indexed bitmap; index 0 is alpha 0 when ``transparent0``."""
    path = Path(out_dir) / rel
    if transparent0:
        _save_rgba(path, index, w, h, pal)
    else:
        _save_rgb(path, index, w, h, pal)


def write_palette_png(path: Path, pal: bytes) -> None:
    """Write the 256x1 palette strip used for visual conditioning."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.frombytes("P", (256, 1), bytes(range(256)))
    im.putpalette(pal)
    im.convert("RGB").save(path, optimize=False)
