"""Differential gate: ``digart.akos.iter_cels`` vs the vendored C++ oracle.

Decode ``DIG.LA1`` with both the Python reader and ``vendor/san-oracle/san-oracle
akos`` and assert an identical cel count, costume/cel ordinals, dimensions,
transparent index, and indexed pixel bytes, plus an identical undecodable-cel
set (``AKOSE`` records vs the Python ``errors`` list).

The oracle stream is a sequence of variable-length records::

    b"AKOS" + u32LE(costume) + u16LE(cel) + u16LE(w) + u16LE(h)
            + u8 transparent + index[w*h]
    b"AKOSE" + u32LE(costume) + u16LE(cel) + u16LE(codec)   # unknown codec

``AKOSE`` is a prefix extension of ``AKOS`` (an ``AKOS`` record whose costume
low byte is 0x45 spells ``AKOSE``), so the parser prefers the cel record and
falls back to the error record only when the cel record would overrun the
stream; DIG.LA1 contains no error records.

Exit 0 when the file matches (or when the game bundle is absent, nothing to
verify); exit 1 on any mismatch or decode failure. This is the acceptance gate
for the AKOS costume-cel port: until ``digart.akos`` decodes the codec set it is
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
CEL_HEADER = 4 + 4 + 2 + 2 + 2 + 1  # AKOS + costume + cel + w + h + transparent
ERROR_SIZE = 5 + 4 + 2 + 2  # AKOSE + costume + cel + codec


def find_la1_files(bundle: Path = BUNDLE) -> tuple[Path, Path]:
    """Return ``(DIG.LA0, DIG.LA1)``; both are inputs to ``iter_cels``."""
    return bundle / "DIG.LA0", bundle / "DIG.LA1"


def parse_oracle(
    data: bytes,
) -> Iterator[tuple[str, int, int, int, int, int, bytes] | tuple[str, int, int, int]]:
    """Yield oracle records from a ``san-oracle akos`` stream.

    A cel record is ``("cel", costume, cel, w, h, transparent, index)``; an error
    record is ``("error", costume, cel, codec)``.
    """
    p, n = 0, len(data)
    while p < n:
        if data[p : p + 4] != b"AKOS":
            raise ValueError(f"bad record magic at offset {p}: {data[p:p + 5]!r}")
        costume, cel, w, h = struct.unpack_from("<IHHH", data, p + 4)
        transparent = data[p + 14]
        index_off = p + CEL_HEADER
        index = data[index_off : index_off + w * h]
        if len(index) == w * h:
            yield ("cel", costume, cel, w, h, transparent, index)
            p = index_off + w * h
        elif data[p : p + 5] == b"AKOSE":
            e_costume, e_cel, codec = struct.unpack_from("<IHH", data, p + 5)
            yield ("error", e_costume, e_cel, codec)
            p += ERROR_SIZE
        else:
            raise ValueError(f"truncated AKOS record at offset {p}")


def first_diff(a: bytes, b: bytes) -> int:
    limit = min(len(a), len(b))
    for i in range(limit):
        if a[i] != b[i]:
            return i
    return limit


def compare_file(la0: Path, la1: Path) -> list[str]:
    """Return human-readable mismatches for DIG.LA1 (empty list == identical)."""
    try:
        from digart import akos as akos_mod

        py_errors: list = []
        py_cels = list(akos_mod.iter_cels(la0.read_bytes(), la1.read_bytes(), py_errors))
        oracle = list(parse_oracle(_run_oracle(la1)))
        return _compare_streams(la1, py_cels, py_errors, oracle)
    except Exception as exc:  # decode error on either side
        return [f"{la1.name}: {type(exc).__name__}: {exc}"]


def _run_oracle(path: Path) -> bytes:
    proc = subprocess.run([str(ORACLE), "akos", str(path)], capture_output=True)
    if proc.returncode != 0:
        msg = proc.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"oracle exit {proc.returncode}: {msg}")
    return proc.stdout


def _compare_streams(path: Path, py_cels: list, py_errors: list, oracle: list) -> list[str]:
    errors: list[str] = []
    oracle_cels = [r for r in oracle if r[0] == "cel"]
    oracle_errors = [r for r in oracle if r[0] == "error"]

    if len(py_cels) != len(oracle_cels):
        errors.append(
            f"{path.name}: cel count {len(py_cels)} != oracle {len(oracle_cels)}"
        )
    for i, (py, orc) in enumerate(zip(py_cels, oracle_cels)):
        _, costume, cel, w, h, transparent, oidx = orc
        if (costume, cel) != (py.costume, py.cel):
            errors.append(
                f"{path.name} cel {i}: ({costume},{cel}) != ({py.costume},{py.cel})"
            )
        elif (w, h) != (py.width, py.height):
            errors.append(
                f"{path.name} cel {i}: dimensions {w}x{h} != {py.width}x{py.height}"
            )
        elif transparent != py.transparent:
            errors.append(
                f"{path.name} cel {i}: transparent {transparent} != {py.transparent}"
            )
        elif py.index != oidx:
            errors.append(
                f"{path.name} cel {i}: index differs at offset {first_diff(py.index, oidx)}"
            )

    if len(py_errors) != len(oracle_errors):
        errors.append(
            f"{path.name}: error count {len(py_errors)} != oracle {len(oracle_errors)}"
        )
    else:
        for i, (pe, oe) in enumerate(zip(py_errors, oracle_errors)):
            if (getattr(pe, "costume", None), getattr(pe, "cel", None)) != (oe[1], oe[2]):
                errors.append(
                    f"{path.name} error {i}: ({oe[1]},{oe[2]}) != "
                    f"({getattr(pe, 'costume', None)},{getattr(pe, 'cel', None)})"
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
    print(f"PASS: {la1.name} AKOS cels byte-identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
