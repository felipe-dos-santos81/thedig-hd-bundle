"""Differential gate: ``digart.la1.iter_bitmaps`` vs the vendored C++ oracle.

Decode ``DIG.LA1`` with both the Python reader and ``vendor/san-oracle/san-oracle
la1`` and assert identical bitmap count, dimensions, transparent-strip flag,
palette bytes, and indexed pixel bytes, plus an identical undecodable-resource
set (``LA1E`` records vs the Python ``errors`` list).

Exit 0 when the file matches (or when the game bundle is absent, nothing to
verify); exit 1 on any mismatch or decode failure. This is the acceptance gate
for the LA1 SMAP/BOMP port: until ``digart.la1`` decodes the codec set it is
expected to fail.
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
BITMAP_HEADER = 4 + 4 + 1 + PALETTE_SIZE  # "LA1B" + u16LE(w,h) + u8 transparent + palette
MAGICS = (b"LA1B", b"LA1E")


def find_la1_files(bundle: Path = BUNDLE) -> tuple[Path, Path]:
    """Return ``(DIG.LA0, DIG.LA1)``; both are inputs to ``iter_bitmaps``."""
    return bundle / "DIG.LA0", bundle / "DIG.LA1"


def parse_oracle(
    data: bytes,
) -> Iterator[tuple[str, int, int, int, bytes, bytes] | tuple[str, int, bytes]]:
    """Yield oracle records from a ``san-oracle la1`` stream.

    A bitmap record is ``("bitmap", w, h, transparent, palette, index)``; an
    error record is ``("error", offset, reason)``. ``LA1E`` carries no reason
    length, so the reason runs to the next record magic (mirrors the C++ writer).
    """
    p, n = 0, len(data)
    while p < n:
        magic = data[p : p + 4]
        if magic == b"LA1B":
            w, h = struct.unpack_from("<HH", data, p + 4)
            transparent = data[p + 8]
            pal = data[p + 9 : p + 9 + PALETTE_SIZE]
            index_off = p + BITMAP_HEADER
            index = data[index_off : index_off + w * h]
            if len(pal) != PALETTE_SIZE or len(index) != w * h:
                raise ValueError(f"truncated LA1B record at offset {p}")
            yield ("bitmap", w, h, transparent, pal, index)
            p = index_off + w * h
        elif magic == b"LA1E":
            off = struct.unpack_from("<I", data, p + 4)[0]
            q = p + 8
            while q < n and data[q : q + 4] not in MAGICS:
                q += 1
            yield ("error", off, data[p + 8 : q])
            p = q
        else:
            raise ValueError(f"bad record magic at offset {p}: {magic!r}")


def first_diff(a: bytes, b: bytes) -> int:
    limit = min(len(a), len(b))
    for i in range(limit):
        if a[i] != b[i]:
            return i
    return limit


def compare_file(la0: Path, la1: Path) -> list[str]:
    """Return human-readable mismatches for DIG.LA1 (empty list == identical)."""
    from digart import la1 as la1_mod

    try:
        py_errors: list = []
        py_bitmaps = list(
            la1_mod.iter_bitmaps(la0.read_bytes(), la1.read_bytes(), py_errors)
        )
        oracle = list(parse_oracle(_run_oracle(la1)))
        return _compare_streams(la1, py_bitmaps, py_errors, oracle)
    except Exception as exc:  # decode error on either side
        return [f"{la1.name}: {type(exc).__name__}: {exc}"]


def _run_oracle(path: Path) -> bytes:
    proc = subprocess.run([str(ORACLE), "la1", str(path)], capture_output=True)
    if proc.returncode != 0:
        msg = proc.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"oracle exit {proc.returncode}: {msg}")
    return proc.stdout


def _compare_streams(path: Path, py_bitmaps: list, py_errors: list, oracle: list) -> list[str]:
    errors: list[str] = []
    oracle_bitmaps = [r for r in oracle if r[0] == "bitmap"]
    oracle_errors = [r for r in oracle if r[0] == "error"]

    if len(py_bitmaps) != len(oracle_bitmaps):
        errors.append(
            f"{path.name}: bitmap count {len(py_bitmaps)} != oracle {len(oracle_bitmaps)}"
        )
    for i, (py, orc) in enumerate(zip(py_bitmaps, oracle_bitmaps)):
        _, w, h, transparent, opal, oidx = orc
        if (w, h) != (py.width, py.height):
            errors.append(
                f"{path.name} bitmap {i}: dimensions {w}x{h} != {py.width}x{py.height}"
            )
        elif int(bool(py.transparent0)) != transparent:
            errors.append(
                f"{path.name} bitmap {i}: transparent {transparent} != {py.transparent0}"
            )
        elif py.palette != opal:
            errors.append(
                f"{path.name} bitmap {i}: palette differs at byte {first_diff(py.palette, opal)}"
            )
        elif py.index != oidx:
            errors.append(
                f"{path.name} bitmap {i}: index differs at offset {first_diff(py.index, oidx)}"
            )

    if len(py_errors) != len(oracle_errors):
        errors.append(
            f"{path.name}: error count {len(py_errors)} != oracle {len(oracle_errors)}"
        )
    else:
        for i, (pe, oe) in enumerate(zip(py_errors, oracle_errors)):
            if getattr(pe, "offset", None) != oe[1]:
                errors.append(
                    f"{path.name} error {i}: offset {oe[1]} != {getattr(pe, 'offset', None)}"
                )
    return errors


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not ORACLE.exists():
        print(f"oracle binary missing: {ORACLE}\nrun `make oracle` first", file=sys.stderr)
        return 1
    if not BUNDLE.is_dir():
        print(f"game bundle not found: {BUNDLE}; nothing to verify", file=sys.stderr)
        return 0

    la0, la1 = find_la1_files()
    if not la0.is_file() or not la1.is_file():
        print(f"missing {la0} or {la1}", file=sys.stderr)
        return 1

    errors = compare_file(la0, la1)
    if errors:
        for line in errors[:5]:
            print(line, file=sys.stderr)
        if len(errors) > 5:
            print(f"{la1.name}: ... {len(errors) - 5} more mismatch(es)", file=sys.stderr)
        print(f"FAIL: {len(errors)} mismatch(es)", file=sys.stderr)
        return 1
    print(f"PASS: {la1.name} byte-identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
