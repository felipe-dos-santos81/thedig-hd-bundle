"""Differential gate: ``digart.nut.iter_images`` vs the vendored C++ oracle.

For every ``.NUT`` file in The Dig bundle, decode with both the Python reader and
``vendor/san-oracle/san-oracle nut`` and assert identical glyph count, dimensions,
transparency index, palette bytes, and indexed glyph bytes.

Exit 0 when every file matches (or when the game bundle is absent, nothing to
verify); exit 1 on any mismatch or decode failure. This is the acceptance gate
for the NUT port: until ``digart.nut`` decodes codecs 1/44 it is expected to fail.
"""

from __future__ import annotations

import struct
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ORACLE = REPO / "vendor" / "san-oracle" / "san-oracle"
BUNDLE = (
    Path.home()
    / "Documents"
    / "The Dig®.app"
    / "Contents"
    / "Resources"
    / "game"
    / "game"
)
PALETTE_SIZE = 768
RECORD_HEADER = 4 + 4 + 1 + PALETTE_SIZE  # "NUTG" + u16LE(w,h) + u8 transparency + palette


def find_nut_files(bundle: Path = BUNDLE) -> list[Path]:
    return sorted(bundle.rglob("*.NUT"))


def parse_oracle(data: bytes) -> Iterator[tuple[int, int, int, bytes, bytes]]:
    """Yield ``(w, h, transparency, palette, index)`` from a ``san-oracle nut`` stream."""
    p, n = 0, len(data)
    while p < n:
        if data[p : p + 4] != b"NUTG":
            raise ValueError(f"bad record magic at offset {p}: {data[p : p + 4]!r}")
        w, h = struct.unpack_from("<HH", data, p + 4)
        transparency = data[p + 8]
        pal = data[p + 9 : p + 9 + PALETTE_SIZE]
        index_off = p + RECORD_HEADER
        index = data[index_off : index_off + w * h]
        if len(pal) != PALETTE_SIZE or len(index) != w * h:
            raise ValueError(f"truncated record at offset {p}")
        yield w, h, transparency, pal, index
        p = index_off + w * h


def first_diff(a: bytes, b: bytes) -> int:
    limit = min(len(a), len(b))
    for i in range(limit):
        if a[i] != b[i]:
            return i
    return limit


def compare_file(path: Path) -> list[str]:
    """Return human-readable mismatches for one file (empty list == identical)."""
    from digart import nut

    try:
        py_images = nut.iter_images(path.read_bytes(), str(path))
        oracle_images = parse_oracle(_run_oracle(path))
        return _compare_streams(path, py_images, oracle_images)
    except Exception as exc:  # decode error on either side
        return [f"{path.name}: {type(exc).__name__}: {exc}"]


def _run_oracle(path: Path) -> bytes:
    proc = subprocess.run([str(ORACLE), "nut", str(path)], capture_output=True)
    if proc.returncode != 0:
        msg = proc.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"oracle exit {proc.returncode}: {msg}")
    return proc.stdout


def _compare_streams(
    path: Path,
    py_images: Iterator,
    oracle_images: Iterator[tuple[int, int, int, bytes, bytes]],
) -> list[str]:
    errors: list[str] = []
    index = 0
    while True:
        py = next(py_images, None)
        orc = next(oracle_images, None)
        if py is None and orc is None:
            break
        if py is None or orc is None:
            errors.append(f"{path.name}: glyph count mismatch (diverged at glyph {index})")
            break
        w, h, transparency, opal, oidx = orc
        if (w, h) != (py.width, py.height):
            errors.append(
                f"{path.name} glyph {index}: dimensions {w}x{h} != {py.width}x{py.height}"
            )
        elif transparency != py.transparent:
            errors.append(
                f"{path.name} glyph {index}: transparency {transparency} != {py.transparent}"
            )
        elif py.palette != opal:
            errors.append(
                f"{path.name} glyph {index}: palette differs at byte {first_diff(py.palette, opal)}"
            )
        elif py.index != oidx:
            errors.append(
                f"{path.name} glyph {index}: index differs at offset {first_diff(py.index, oidx)}"
            )
        index += 1
    return errors


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not ORACLE.exists():
        print(f"oracle binary missing: {ORACLE}\nrun `make oracle` first", file=sys.stderr)
        return 1
    if not BUNDLE.is_dir():
        print(f"game bundle not found: {BUNDLE}; nothing to verify", file=sys.stderr)
        return 0

    files = find_nut_files()
    if not files:
        print(f"no .NUT files under {BUNDLE}", file=sys.stderr)
        return 1

    total_errors = 0
    matched = 0
    for path in files:
        errors = compare_file(path)
        if errors:
            total_errors += len(errors)
            for line in errors[:5]:
                print(line, file=sys.stderr)
            if len(errors) > 5:
                print(f"{path.name}: ... {len(errors) - 5} more mismatch(es)", file=sys.stderr)
        else:
            matched += 1

    if total_errors:
        print(f"FAIL: {total_errors} mismatch(es) across {len(files)} files", file=sys.stderr)
        return 1
    print(f"PASS: {matched}/{len(files)} files byte-identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
