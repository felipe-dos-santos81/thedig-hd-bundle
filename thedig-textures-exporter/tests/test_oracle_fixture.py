"""Differential test of the Python codec-37 port against the vendored C++ oracle.

Skipped when ``vendor/san-oracle/san-oracle`` has not been built (``make oracle``).
Every synthetic SAN is decoded by both sides and must agree on frame count,
palette bytes, and indexed pixels.
"""

import struct
import subprocess
from pathlib import Path

import pytest

from digart import san as S
from tests.fixtures import make_fixtures as fx

REPO = Path(__file__).resolve().parent.parent
ORACLE = REPO / "vendor" / "san-oracle" / "san-oracle"

pytestmark = pytest.mark.skipif(not ORACLE.exists(), reason="san-oracle binary not built")

W, H = 320, 200
FRAME = W * H
BLOCKS = (W // 4) * (H // 4)
PAL = bytes([(i * 7) & 0xFF for i in range(768)])
codec_header = fx.codec_header
fobj = fx.fobj


def raw_frame(color: int, seq: int = 0) -> bytes:
    return raw_body_frame(bytes([color]) * FRAME, seq)


def raw_body_frame(body: bytes, seq: int = 0) -> bytes:
    assert len(body) == FRAME
    return fobj(37, W, H, codec_header(0, 0, seq, FRAME, 0) + body)


def bomp_frame(seq: int = 0) -> bytes:
    line = bytes([0xFF, 0x33]) * 500
    return fobj(37, W, H, codec_header(2, 0, seq, FRAME, 0) + line)


def proc1_frame(seq: int = 0) -> bytes:
    # Each 4x4 block: [0x01, 0xFF, 0x1F, color] -> a 16-pixel fill of `color`.
    stream = b"".join(bytes([0x01, 0xFF, 0x1F, i & 0xFF]) for i in range(BLOCKS))
    return fobj(37, W, H, codec_header(1, 0, seq, len(stream), 1) + stream)


def proc1_copy_frame(seq: int = 0) -> bytes:
    # filling=0 run header (0x00) then copy code 0; offsetTable[0] == 0, so each
    # block is copied from the same position in the other delta buffer.
    stream = bytes([0x00, 0x00]) * BLOCKS
    return fobj(37, W, H, codec_header(1, 0, seq, len(stream), 1) + stream)


def proc3_fdfe_frame(seq: int = 0) -> bytes:
    stream = b"".join(bytes([0xFD, i & 0xFF]) for i in range(BLOCKS))
    return fobj(37, W, H, codec_header(3, 0, seq, len(stream), 4) + stream)


def proc4_fdfe_frame(seq: int = 0) -> bytes:
    stream = b"".join(bytes([0xFD, i & 0xFF]) for i in range(BLOCKS))
    return fobj(37, W, H, codec_header(4, 0, seq, len(stream), 4) + stream)


def proc4_plain_frame(seq: int = 0) -> bytes:
    # 0xFF = literal 1x1: sixteen source bytes become the 16 pixels (4 per row).
    stream = b"".join(bytes([0xFF]) + bytes([i & 0xFF]) * 16 for i in range(BLOCKS))
    return fobj(37, W, H, codec_header(4, 0, seq, len(stream), 0) + stream)


def oracle_frames(path: Path):
    proc = subprocess.run([str(ORACLE), "dump", str(path)], capture_output=True)
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    data = proc.stdout
    p, n = 0, len(data)
    while p < n:
        assert data[p:p + 4] == b"FRMK"
        w, h = struct.unpack_from("<HH", data, p + 4)
        pal = data[p + 8:p + 8 + 768]
        idx_off = p + 8 + 768
        idx = data[idx_off:idx_off + w * h]
        yield w, h, pal, idx
        p = idx_off + w * h


def assert_matches(frames: list[bytes], tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_bytes(fx.san([fx.frame(f) for f in frames], PAL))
    py = list(S.iter_frames(path.read_bytes(), name))
    orc = list(oracle_frames(path))
    assert len(py) == len(orc)
    for i, (pf, (w, h, opal, oidx)) in enumerate(zip(py, orc)):
        assert (w, h) == (W, H)
        assert pf.palette == opal, f"frame {i} palette"
        assert pf.index == oidx, f"frame {i} index"


def test_oracle_matches_python(tmp_path):
    for name, frame in [
        ("v0", raw_frame(0x10)),
        ("v1", proc1_frame()),
        ("v2", bomp_frame()),
        ("v3", proc3_fdfe_frame()),
        ("v4fdfe", proc4_fdfe_frame()),
        ("v4plain", proc4_plain_frame()),
    ]:
        assert_matches([frame], tmp_path, f"{name}.SAN")

    body = bytes((i * 13 + 7) & 0xFF for i in range(FRAME))
    frames = [raw_body_frame(body, seq=0), proc1_copy_frame(seq=1)]
    assert_matches(frames, tmp_path, "copy.SAN")
    path = tmp_path / "copy2.SAN"
    path.write_bytes(fx.san([fx.frame(f) for f in frames], PAL))
    out = list(S.iter_frames(path.read_bytes(), "copy2.SAN"))
    assert out[0].index == body
    assert out[1].index == body                          # frame 1 copies frame 0

    multi = [
        proc3_fdfe_frame(seq=0),
        proc3_fdfe_frame(seq=1),
        proc1_frame(seq=2),
        bomp_frame(seq=3),
        raw_frame(0x44, seq=4),
        proc4_fdfe_frame(seq=5),
    ]
    assert_matches(multi, tmp_path, "multi.SAN")
