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
import sys
from collections.abc import Iterator
from pathlib import Path

from _oracle import BUNDLE, PALETTE_SIZE, first_diff, preflight, run_files, run_oracle

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


def compare_file(path: Path) -> list[str]:
    """Return human-readable mismatches for one file (empty list == identical)."""
    from digart import nut

    try:
        py_images = nut.iter_images(path.read_bytes(), str(path))
        oracle_images = parse_oracle(run_oracle("nut", path))
        return _compare_streams(path, py_images, oracle_images)
    except Exception as exc:  # decode error on either side
        return [f"{path.name}: {type(exc).__name__}: {exc}"]


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
    rc = preflight()
    if rc is not None:
        return rc
    files = find_nut_files()
    if not files:
        print(f"no .NUT files under {BUNDLE}", file=sys.stderr)
        return 1
    return run_files(files, compare_file)


if __name__ == "__main__":
    raise SystemExit(main())
