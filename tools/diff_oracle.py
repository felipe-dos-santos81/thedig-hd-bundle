"""Differential gate: ``digart.san.iter_frames`` vs the vendored C++ oracle.

For every ``.SAN`` file in The Dig bundle, decode with both the Python reader and
``vendor/san-oracle/san-oracle dump`` and assert identical frame count,
dimensions, palette bytes, and indexed pixel bytes.

Exit 0 when every file matches (or when the game bundle is absent, nothing to
verify); exit 1 on any mismatch or decode failure. This is the acceptance gate
for the codec-37 port: until ``digart`` decodes codec 37 it is expected to fail.
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
FRAME_W, FRAME_H = 320, 200
PALETTE_SIZE = 768
RECORD_HEADER = 8 + PALETTE_SIZE  # "FRMK" + u16LE(w) + u16LE(h) + palette


def find_san_files(bundle: Path = BUNDLE) -> list[Path]:
    return sorted(bundle.rglob("*.SAN"))


def parse_oracle(data: bytes) -> Iterator[tuple[int, int, bytes, bytes]]:
    """Yield ``(w, h, palette, index)`` from a ``san-oracle dump`` stream."""
    p, n = 0, len(data)
    while p < n:
        if data[p : p + 4] != b"FRMK":
            raise ValueError(f"bad record magic at offset {p}: {data[p : p + 4]!r}")
        w, h = struct.unpack_from("<HH", data, p + 4)
        pal = data[p + 8 : p + 8 + PALETTE_SIZE]
        index_off = p + RECORD_HEADER
        index = data[index_off : index_off + w * h]
        if len(pal) != PALETTE_SIZE or len(index) != w * h:
            raise ValueError(f"truncated record at offset {p}")
        yield w, h, pal, index
        p = index_off + w * h


def first_diff(a: bytes, b: bytes) -> int:
    limit = min(len(a), len(b))
    for i in range(limit):
        if a[i] != b[i]:
            return i
    return limit


def compare_file(path: Path) -> list[str]:
    """Return human-readable mismatches for one file (empty list == identical)."""
    from digart import san

    try:
        py_frames = san.iter_frames(path.read_bytes(), str(path))
        oracle_frames = parse_oracle(_run_oracle(path))
        return _compare_streams(path, py_frames, oracle_frames)
    except Exception as exc:  # decode error on either side
        return [f"{path.name}: {type(exc).__name__}: {exc}"]


def _run_oracle(path: Path) -> bytes:
    proc = subprocess.run([str(ORACLE), "dump", str(path)], capture_output=True)
    if proc.returncode != 0:
        msg = proc.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"oracle exit {proc.returncode}: {msg}")
    return proc.stdout


def _compare_streams(
    path: Path,
    py_frames: Iterator,
    oracle_frames: Iterator[tuple[int, int, bytes, bytes]],
) -> list[str]:
    errors: list[str] = []
    index = 0
    while True:
        py = next(py_frames, None)
        orc = next(oracle_frames, None)
        if py is None and orc is None:
            break
        if py is None or orc is None:
            errors.append(f"{path.name}: frame count mismatch (diverged at frame {index})")
            break
        w, h, opal, oidx = orc
        if (w, h) != (FRAME_W, FRAME_H):
            errors.append(f"{path.name} frame {index}: oracle dimensions {w}x{h}")
        elif py.palette != opal:
            errors.append(
                f"{path.name} frame {index}: palette differs at byte {first_diff(py.palette, opal)}"
            )
        elif py.index != oidx:
            errors.append(
                f"{path.name} frame {index}: index differs at offset {first_diff(py.index, oidx)}"
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

    files = find_san_files()
    if not files:
        print(f"no .SAN files under {BUNDLE}", file=sys.stderr)
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
