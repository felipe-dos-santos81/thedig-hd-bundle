"""Command-line entry point: full-bundle extraction and differential verify.

``extract`` walks the read-only game bundle, decodes every SAN frame, NUT glyph,
LA1 room/object bitmap and AKOS costume cel, writes deterministic PNGs under
``--out``, and emits ``manifest.json`` (+ ``_errors.json`` when anything could
not be decoded). ``verify`` runs the four differential gates against the vendored
C++ oracle.

Exit codes (spec §6): ``0`` success with zero errors, ``1`` errors recorded,
``2`` usage/preflight failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .akos import iter_cels
from .errors import DecodeError
from .la1 import La1Bitmap, iter_bitmaps
from .manifest import AssetRecord, ManifestBuilder, palette_hash, rec_id
from .nut import iter_images
from .pngout import write_indexed_png, write_san_png
from .san import FRAME_H, FRAME_W, iter_frames

GAME_DEFAULT = str(Path.home() / "Documents" / "The Dig®.app")
GAME_SUBPATH = Path("Contents") / "Resources" / "game" / "game"
KINDS = ("san", "nut", "la1", "akos")
REQUIRED = ("VIDEO", "DIG.LA0", "DIG.LA1")
DIFFERENTIALS = ("diff_oracle.py", "diff_nut.py", "diff_la1.py", "diff_akos.py")
# Manifest `kind` per extraction family; LA1 bitmaps and AKOS cels share one kind
# (the schema's fixed counts dict has no separate akos bucket) and are told apart
# by their `id` prefix (`la1:` / `akos:`).
_KIND_OF = {"san": "san_frame", "nut": "nut_image",
            "la1": "la1_bitmap", "akos": "la1_bitmap"}

# spec §6: full runs (any SAN) need 15 GiB; nut/la1-only runs need 1 GiB.
_DISK_SAN = 15 << 30
_DISK_OTHER = 1 << 30


# ── Preflight / helpers ──────────────────────────────────────────────────────


def game_root(game: Path) -> Path:
    return Path(game) / GAME_SUBPATH


def missing_required(root: Path) -> list[str]:
    return [rel for rel in REQUIRED if not (root / rel).exists()]


def disk_free(path: Path) -> int:
    """Free bytes on the filesystem that would hold ``path`` (walks up to exist)."""
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


def parse_only(value: str | None) -> tuple[str, ...] | None:
    """Parse ``--only`` into canonical kind order; ``None`` on an unknown kind."""
    if value is None:
        return KINDS
    parts = {p.strip().lower() for p in value.split(",") if p.strip()}
    if not parts or not parts <= set(KINDS):
        return None
    return tuple(k for k in KINDS if k in parts)


def find_sources(root: Path, kinds: tuple[str, ...]) -> list[tuple[str, Path]]:
    """Deterministic ``(kind, path)`` task list for the selected kinds."""
    tasks: list[tuple[str, Path]] = []
    if "san" in kinds:
        tasks += [("san", p) for p in sorted(root.rglob("*.SAN"))]
    if "nut" in kinds:
        tasks += [("nut", p) for p in sorted(root.rglob("*.NUT"))]
    if "la1" in kinds:
        tasks.append(("la1", root / "DIG.LA1"))
    if "akos" in kinds:
        tasks.append(("akos", root / "DIG.LA1"))
    return tasks


def game_root_hash(root: Path) -> str:
    """sha256 over sorted ``(relative path, size)`` pairs of the game directory."""
    h = hashlib.sha256()
    entries = sorted(
        (p.relative_to(root).as_posix(), p.stat().st_size)
        for p in root.rglob("*")
        if p.is_file()
    )
    for rel, size in entries:
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(str(size).encode("ascii"))
        h.update(b"\0")
    return h.hexdigest()


def _stream(gen: Iterator, errors: list[dict]) -> Iterator:
    """Yield from ``gen``, converting a raised ``DecodeError`` into a record."""
    it = iter(gen)
    while True:
        try:
            item = next(it)
        except StopIteration:
            return
        except DecodeError as exc:
            errors.append(exc.to_dict())
            return
        yield item


def _record(family: str, source: str, frame: int | None, name: str | None,
            width: int, height: int, has_alpha: bool, palette: bytes,
            path: Path) -> dict:
    return {
        "id": _asset_id(family, source, frame, name),
        "kind": _KIND_OF[family],
        "source": source,
        "frame": frame,
        "name": name,
        "width": width,
        "height": height,
        "has_alpha": has_alpha,
        "palette": palette_hash(palette),
        "path": path.as_posix(),
        "_palette_bytes": palette,
    }


def _asset_id(family: str, source: str, frame: int | None, name: str | None) -> str:
    if family in ("san", "nut"):
        return rec_id(family, source, frame or 0)
    return f"{family}:{name}"


# ── Per-file workers (module-level so ProcessPoolExecutor can pickle them) ────


def _extract_one(task: tuple[str, str, str, str]) -> tuple[list[dict], list[dict]]:
    kind, path_str, out_str, root_str = task
    path, out, root = Path(path_str), Path(out_str), Path(root_str)
    source = path.relative_to(root).as_posix()
    data = path.read_bytes()
    records: list[dict] = []
    errors: list[dict] = []

    if kind == "san":
        _extract_san(data, source, path.stem, out, records, errors)
    elif kind == "nut":
        _extract_nut(data, source, path.stem, out, records, errors)
    elif kind == "la1":
        _extract_la1((root / "DIG.LA0").read_bytes(), data, source, out, records, errors)
    elif kind == "akos":
        _extract_akos((root / "DIG.LA0").read_bytes(), data, source, out, records, errors)
    else:  # pragma: no cover - callers only build known kinds
        raise ValueError(f"unknown kind {kind!r}")
    return records, errors


def _extract_san(data: bytes, source: str, stem: str, out: Path,
                 records: list[dict], errors: list[dict]) -> None:
    for i, frame in enumerate(_stream(iter_frames(data, source), errors)):
        rel = Path("san") / stem / f"{i:05d}.png"
        write_san_png(out, rel, frame)
        records.append(_record("san", source, i, None, FRAME_W, FRAME_H,
                               False, frame.palette, rel))


def _normalize_transparent(index: bytes, palette: bytes, t: int) -> tuple[bytes, bytes]:
    """Swap colour ``t`` with index 0 so an index-0-alpha writer makes it transparent."""
    if t == 0:
        return index, palette
    table = bytearray(range(256))
    table[0], table[t] = t, 0
    pal = bytearray(palette)
    for c in range(3):
        pal[c], pal[t * 3 + c] = palette[t * 3 + c], palette[c]
    return bytes(index.translate(bytes(table))), bytes(pal)


def _write_bitmap(out: Path, rel: Path, index: bytes, width: int, height: int,
                  palette: bytes, transparent: int | None) -> tuple[bytes, bool]:
    """Write an indexed bitmap, normalizing its transparent index to palette 0.

    ``transparent`` is the decoder's transparent colour index, or ``None`` for an
    opaque bitmap. When set, the index is swapped with 0 in both the pixel buffer
    and the palette (leaving every non-transparent pixel's RGB unchanged) and the
    PNG is written RGBA with alpha 0 at that index. Returns the palette actually
    written (for the manifest/sidecar) and the ``has_alpha`` flag.
    """
    if transparent is None:
        write_indexed_png(out, rel, index, width, height, palette, False)
        return palette, False
    index, palette = _normalize_transparent(index, palette, transparent)
    write_indexed_png(out, rel, index, width, height, palette, True)
    return palette, True


def _la1_transparent_index(bmp: La1Bitmap) -> int | None:
    """Transparent colour index of a DIG.LA1 bitmap, or ``None`` when opaque.

    ``OBIM`` object sprites carry index 0 as transparent (both the SMAP and BOMP
    variants); ``RMIM`` room backdrops are opaque unless their SMAP strip codec
    was a transparent variant, in which case index 0 is transparent too. The
    names are the decoder's contract (``digart.la1._process_room``): ``room<NNN>``
    for RMIM, ``obj<NNN>_<state>`` for OBIM.
    """
    if bmp.name.startswith("obj"):
        return 0
    return 0 if bmp.transparent0 else None


def _extract_nut(data: bytes, source: str, stem: str, out: Path,
                 records: list[dict], errors: list[dict]) -> None:
    for i, img in enumerate(_stream(iter_images(data, source), errors)):
        rel = Path("nut") / stem / f"img_{i:03d}.png"
        palette, has_alpha = _write_bitmap(out, rel, img.index, img.width,
                                           img.height, img.palette, img.transparent)
        records.append(_record("nut", source, i, img.name, img.width,
                               img.height, has_alpha, palette, rel))


def _extract_la1(la0: bytes, la1: bytes, source: str, out: Path,
                 records: list[dict], errors: list[dict]) -> None:
    local: list[DecodeError] = []
    for bmp in _stream(iter_bitmaps(la0, la1, local, source), errors):
        rel = Path("la1") / f"{bmp.name}.png"
        palette, has_alpha = _write_bitmap(out, rel, bmp.index, bmp.width,
                                           bmp.height, bmp.palette,
                                           _la1_transparent_index(bmp))
        records.append(_record("la1", source, None, bmp.name, bmp.width,
                               bmp.height, has_alpha, palette, rel))
    errors.extend(e.to_dict() for e in local)


def _extract_akos(la0: bytes, la1: bytes, source: str, out: Path,
                  records: list[dict], errors: list[dict]) -> None:
    local: list[DecodeError] = []
    for cel in _stream(iter_cels(la0, la1, local, source), errors):
        rel = Path("la1") / f"{cel.name}.png"
        palette, has_alpha = _write_bitmap(out, rel, cel.index, cel.width,
                                           cel.height, cel.palette,
                                           cel.transparent)
        records.append(_record("akos", source, None, cel.name, cel.width,
                               cel.height, has_alpha, palette, rel))
    errors.extend(e.to_dict() for e in local)


# ── Commands ─────────────────────────────────────────────────────────────────


def cmd_extract(args: argparse.Namespace) -> int:
    root = game_root(Path(args.game))
    missing = missing_required(root)
    if missing:
        print(f"preflight failed: missing under {root}: {', '.join(missing)}",
              file=sys.stderr)
        return 2

    kinds = parse_only(args.only)
    if kinds is None:
        print(f"invalid --only {args.only!r}; choose from {', '.join(KINDS)}",
              file=sys.stderr)
        return 2

    jobs = args.jobs if args.jobs is not None else min(4, os.cpu_count() or 1)
    if jobs < 1:
        print(f"invalid --jobs {jobs}; must be >= 1", file=sys.stderr)
        return 2

    out = Path(args.out)
    need = _DISK_SAN if "san" in kinds else _DISK_OTHER
    free = disk_free(out)
    if free < need and not args.force:
        print(f"insufficient disk at {out}: need {need >> 30} GiB, "
              f"free {free >> 30} GiB (--force to override)", file=sys.stderr)
        return 2

    out.mkdir(parents=True, exist_ok=True)
    (out / "_errors.json").unlink(missing_ok=True)  # drop any stale error report
    tasks = find_sources(root, kinds)
    task_args = [(kind, str(path), str(out), str(root)) for kind, path in tasks]
    if jobs == 1:
        results = [_extract_one(t) for t in task_args]
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            results = list(pool.map(_extract_one, task_args))

    records = [rec for recs, _ in results for rec in recs]
    errors = [err for _, errs in results for err in errs]
    records.sort(key=lambda r: (
        r["source"], r["frame"] if r["frame"] is not None else -1, r["id"],
    ))
    errors.sort(key=lambda e: (e.get("source", ""), e.get("offset", 0)))

    builder = ManifestBuilder(out)
    for rec in records:
        builder.record_palette(rec.pop("_palette_bytes"))
        builder.add(AssetRecord(**rec))
    builder.finalize(
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        game_root_hash(root),
        error_count=len(errors),
    )

    if errors:
        (out / "_errors.json").write_text(
            json.dumps({"count": len(errors), "errors": errors}, indent=2) + "\n",
            encoding="utf-8",
        )

    total_bytes = sum((out / rec["path"]).stat().st_size for rec in records)
    by_family = {f: sum(1 for r in records if r["id"].split(":", 1)[0] == f)
                 for f in KINDS}
    print(f"extracted {len(records)} assets "
          f"(san {by_family['san']}, nut {by_family['nut']}, "
          f"la1 {by_family['la1']}, akos {by_family['akos']}) "
          f"-> {total_bytes} bytes")
    print(f"manifest: {out / 'manifest.json'}")
    if errors:
        print(f"errors: {len(errors)} (see {out / '_errors.json'})", file=sys.stderr)
        return 1
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    repo = Path(__file__).resolve().parent.parent
    oracle = repo / "vendor" / "san-oracle" / "san-oracle"
    if not oracle.exists():
        print(f"oracle binary missing: {oracle}\nrun `make oracle` first",
              file=sys.stderr)
        return 2
    if not game_root(Path(GAME_DEFAULT)).is_dir():
        print(f"game bundle not found: {game_root(Path(GAME_DEFAULT))}",
              file=sys.stderr)
        return 2

    failed = 0
    for tool in DIFFERENTIALS:
        if subprocess.run([sys.executable, str(repo / "tools" / tool)], cwd=repo).returncode:
            failed += 1
    if failed:
        print(f"verify FAILED: {failed}/{len(DIFFERENTIALS)} differentials mismatched",
              file=sys.stderr)
        return 1
    print(f"verify PASS: {len(DIFFERENTIALS)}/{len(DIFFERENTIALS)} differentials byte-exact")
    return 0


# ── Entry point ──────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="thedig-textures",
        description="Extract every texture from GOG's The Dig into PNGs + a manifest.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    extract = sub.add_parser("extract", help="decode the bundle into --out")
    extract.add_argument("--game", default=GAME_DEFAULT, help="path to The Dig®.app")
    extract.add_argument("--out", default="out", help="output directory")
    extract.add_argument("--only", default=None,
                         help=f"comma-separated subset of {','.join(KINDS)}")
    extract.add_argument("--jobs", type=int, default=None, help="worker processes")
    extract.add_argument("--force", action="store_true",
                         help="skip the free-disk preflight")
    extract.set_defaults(func=cmd_extract)

    verify = sub.add_parser("verify", help="run the differential oracle gates")
    verify.add_argument("--out", default="out", help="(unused) output directory")
    verify.set_defaults(func=cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
