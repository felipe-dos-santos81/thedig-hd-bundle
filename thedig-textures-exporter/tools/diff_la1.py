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
import sys
from collections.abc import Iterator
from pathlib import Path

from _oracle import BUNDLE, PALETTE_SIZE, first_diff, preflight, run_oracle, run_single

BITMAP_HEADER = 4 + 4 + 1 + PALETTE_SIZE  # "LA1B" + u16LE(w,h) + u8 transparent + palette
MAGICS = (b"LA1B", b"LA1E")


def find_la1_file(bundle: Path = BUNDLE) -> Path:
    """Return ``DIG.LA1``, the container decoded by ``iter_bitmaps``."""
    return bundle / "DIG.LA1"


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


def compare_file(la1: Path) -> list[str]:
    """Return human-readable mismatches for DIG.LA1 (empty list == identical)."""
    from digart import la1 as la1_mod

    try:
        py_errors: list = []
        py_bitmaps = list(la1_mod.iter_bitmaps(la1.read_bytes(), py_errors))
        oracle = list(parse_oracle(run_oracle("la1", la1)))
        return _compare_streams(la1, py_bitmaps, py_errors, oracle)
    except Exception as exc:  # decode error on either side
        return [f"{la1.name}: {type(exc).__name__}: {exc}"]


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
    rc = preflight()
    if rc is not None:
        return rc
    la1 = find_la1_file()
    if not la1.is_file():
        print(f"missing {la1}", file=sys.stderr)
        return 1
    return run_single(la1, compare_file(la1), f"PASS: {la1.name} byte-identical")


if __name__ == "__main__":
    raise SystemExit(main())
