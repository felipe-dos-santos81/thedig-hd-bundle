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
import sys
from collections.abc import Iterator
from pathlib import Path

from _oracle import BUNDLE, first_diff, preflight, run_oracle, run_single

CEL_HEADER = 4 + 4 + 2 + 2 + 2 + 1  # AKOS + costume + cel + w + h + transparent
ERROR_SIZE = 5 + 4 + 2 + 2  # AKOSE + costume + cel + codec


def find_la1_file(bundle: Path = BUNDLE) -> Path:
    """Return ``DIG.LA1``, the container decoded by ``iter_cels``."""
    return bundle / "DIG.LA1"


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


def compare_file(la1: Path) -> list[str]:
    """Return human-readable mismatches for DIG.LA1 (empty list == identical)."""
    try:
        from digart import akos as akos_mod

        py_errors: list = []
        py_cels = list(akos_mod.iter_cels(la1.read_bytes(), py_errors))
        oracle = list(parse_oracle(run_oracle("akos", la1)))
        return _compare_streams(la1, py_cels, py_errors, oracle)
    except Exception as exc:  # decode error on either side
        return [f"{la1.name}: {type(exc).__name__}: {exc}"]


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
    rc = preflight()
    if rc is not None:
        return rc
    la1 = find_la1_file()
    if not la1.is_file():
        print(f"missing {la1}", file=sys.stderr)
        return 1
    return run_single(la1, compare_file(la1), f"PASS: {la1.name} AKOS cels byte-identical")


if __name__ == "__main__":
    raise SystemExit(main())
