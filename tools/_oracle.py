"""Shared harness for the ``tools/diff_*.py`` differential gates.

Owns the repo/oracle/bundle paths, the oracle subprocess call, the first-diff
helper, and the common preflight/error reporting, so each gate keeps only its
record parser and comparison.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
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


def run_oracle(mode: str, path: Path) -> bytes:
    """Run ``san-oracle <mode> <path>`` and return stdout, raising on failure."""
    proc = subprocess.run([str(ORACLE), mode, str(path)], capture_output=True)
    if proc.returncode != 0:
        msg = proc.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"oracle exit {proc.returncode}: {msg}")
    return proc.stdout


def first_diff(a: bytes, b: bytes) -> int:
    limit = min(len(a), len(b))
    for i in range(limit):
        if a[i] != b[i]:
            return i
    return limit


def preflight() -> int | None:
    """Return an exit code when the gate cannot run (``0`` = nothing to verify)."""
    if not ORACLE.exists():
        print(f"oracle binary missing: {ORACLE}\nrun `make oracle` first", file=sys.stderr)
        return 1
    if not BUNDLE.is_dir():
        print(f"game bundle not found: {BUNDLE}; nothing to verify", file=sys.stderr)
        return 0
    return None


def _print_errors(path: Path, errors: list[str]) -> bool:
    """Print the first mismatches for ``path``; return True when there were any."""
    if not errors:
        return False
    for line in errors[:5]:
        print(line, file=sys.stderr)
    if len(errors) > 5:
        print(f"{path.name}: ... {len(errors) - 5} more mismatch(es)", file=sys.stderr)
    return True


def run_files(files: list[Path], compare: Callable[[Path], list[str]]) -> int:
    """Compare every file and print the PASS/FAIL summary (the SAN/NUT gates)."""
    total_errors = 0
    matched = 0
    for path in files:
        errors = compare(path)
        if _print_errors(path, errors):
            total_errors += len(errors)
        else:
            matched += 1
    if total_errors:
        print(f"FAIL: {total_errors} mismatch(es) across {len(files)} files", file=sys.stderr)
        return 1
    print(f"PASS: {matched}/{len(files)} files byte-identical")
    return 0


def run_single(path: Path, errors: list[str], label: str) -> int:
    """Report one file's comparison result (the LA1/AKOS gates)."""
    if _print_errors(path, errors):
        print(f"FAIL: {len(errors)} mismatch(es)", file=sys.stderr)
        return 1
    print(label)
    return 0
