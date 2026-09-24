# The Dig Texture Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `thedig-textures`, a Python CLI that extracts every SAN frame, NUT glyph/icon, and SCUMM v7 LA1 bitmap from the GOG *The Dig* `.app` into PNGs + a manifest, pixel-identical to what ScummVM's shipped SmushPlayer renders.

**Architecture:** Pure-Python ports of the upstream ScummVM decode paths (BOMP row RLE, SMUSH `ANIM/AHDR/FRME/NPAL/XPAL/FOBJ/ZFOB`, NUT font walker, LECF/ROOM index), plus a small vendored C++ oracle harness built from the *actual* upstream `bomp.cpp`/`codec1.cpp`, used for byte-exact differential verification on all 55 `.SAN` files.

**Tech Stack:** Python 3.12, Pillow (only runtime dep), pytest (dev), stdlib `zlib`, clang++ (oracle build only).

**Spec:** `docs/superpowers/specs/2026-09-24-thedig-textures-design.md`. Read §4 (formats) before any task; it encodes format facts already verified against the bundle and upstream code.

## Global Constraints

- Python >= 3.12; runtime dependency: `pillow` only; dev dependency: `pytest`.
- License: GPL-3.0-or-later. Vendored upstream files keep their original headers; the sed-extracted regions in the oracle are verbatim (no re-typing).
- The game bundle (`~/Documents/The Dig®.app`) is opened **read-only, always**; nothing is ever written under it.
- Screen model for The Dig SANs: 320×200 (`FRAME_W = 320`, `FRAME_H = 200`). Palettes are 768-byte 8-bit RGB, used verbatim (no 6-bit scaling).
- SAN frames are opaque (index 0 = "keep previous pixel"); NUT/LA1 glyph/costume bitmaps map index 0 to alpha 0 in the PNG writer.
- Output must be deterministic: no timestamps in PNGs or manifest; entries in sorted source-file order with zero-padded frame indices.
- `make check` (unit tests only, game-marked tests deselected) must be green at every commit; `make verify` additionally runs the 55-file oracle differential.
- Commit per task with conventional messages (`feat:`/`test:`/`chore:`).

## File Structure

```
pyproject.toml                     package metadata, console script, pytest config
Makefile                           check / oracle / verify targets
.gitignore
README.md                          usage (final in Task 9)
digart/__init__.py                 __version__
digart/errors.py                   DecodeError(source, offset, reason)
digart/bomp.py                     bomp_decode_line — port of engines/scumm/bomp.cpp
digart/san.py                      SanFrame, iter_frames — SmushPlayer frame state machine
digart/nut.py                      NutImage, iter_images — port of NutRenderer::loadFont
digart/la1.py                      La1Bitmap, iter_bitmaps — LECF/LOFF/ROOM walker
digart/manifest.py                 AssetRecord, ManifestBuilder, palette_hash
digart/pngout.py                   deterministic PNG + palette-strip writers
digart/cli.py                      extract/verify, preflight, --jobs orchestration
tools/diff_oracle.py               python-vs-C++ differential over all .san files
tools/la1_census.py                DIG.LA1 chunk-tag census (Task 8 Step 1)
vendor/san-oracle/UPSTREAM.txt     pinned scummvm commit SHA + file hashes
vendor/san-oracle/bomp.h bomp.cpp codec1.cpp nut_renderer.cpp   verbatim upstream
vendor/san-oracle/shim.h           minimal byte/READ_* typedefs
vendor/san-oracle/bomp_core.cpp codec1_core.cpp     sed-extracted upstream regions
vendor/san-oracle/oracle_main.cpp  transcribed Dig-path SMUSH walk + FRMK emitter
vendor/san-oracle/build.sh
tests/conftest.py                  bundle fixture + game skip
tests/fixtures/make_fixtures.py    synthetic SAN/NUT/ROOM builders
tests/test_bomp.py test_san.py test_san_draw.py test_nut.py test_la1.py
tests/test_manifest.py test_cli.py test_oracle_fixture.py
docs/la1-census.txt                produced by Task 8 (committed real-file census)
docs/proofs/                       first-frame PNGs + proof README (Task 9)
```

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`, `Makefile`, `.gitignore`, `README.md`, `digart/__init__.py`, `digart/errors.py`, `digart/{bomp,san,nut,la1,manifest,pngout,cli}.py` (empty stubs), `tools/`, `tests/conftest.py`, `tests/fixtures/__init__.py`, `tests/test_scaffold.py`

**Interfaces:**
- Produces: `digart.errors.DecodeError(source: str, offset: int, reason: str)` with `.to_dict() -> dict`; `digart.__version__: str`; working `make check`.

- [ ] **Step 1: Create files.**

`pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "thedig-textures"
version = "0.1.0"
description = "Extract every texture from GOG's The Dig for AI regeneration"
requires-python = ">=3.12"
license = { text = "GPL-3.0-or-later" }
dependencies = ["pillow>=10"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
thedig-textures = "digart.cli:main"

[tool.setuptools.packages.find]
include = ["digart*"]

[tool.pytest.ini_options]
markers = ["game: needs The Dig bundle"]
addopts = ["-m", "not game"]
```

`Makefile`:
```make
PY      ?= python3
VENV    := .venv
BIN     := $(VENV)/bin

$(VENV)/bin/python:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -e ".[dev]"

.PHONY: check oracle verify
check:
	$(BIN)/pytest

oracle:
	bash vendor/san-oracle/build.sh

verify: check oracle
	$(BIN)/python tools/diff_oracle.py
```

`.gitignore`:
```
.venv/
out/
vendor/san-oracle/san-oracle
vendor/san-oracle/*_core.cpp
__pycache__/
*.pyc
.pytest_cache/
```

`README.md` (placeholder, final in Task 9):
```markdown
# thedig-textures
Extract all textures (SAN frames, NUT glyphs/icons, SCUMM v7 LA1 bitmaps) from
GOG's The Dig.app into PNGs + manifest.json for AI regeneration.
See docs/superpowers/specs/. Commands: `make verify`, `thedig-textures extract`.
```

`digart/__init__.py`:
```python
__version__ = "0.1.0"
```

`digart/errors.py`:
```python
class DecodeError(Exception):
    def __init__(self, source: str, offset: int, reason: str):
        super().__init__(f"{source}@{offset:#x}: {reason}")
        self.source, self.offset, self.reason = source, offset, reason

    def to_dict(self) -> dict:
        return {"source": self.source, "offset": self.offset, "reason": self.reason}
```

`tests/conftest.py`:
```python
from pathlib import Path
import pytest

BUNDLE = Path.home() / "Documents" / "The Dig®.app" / "Contents" / "Resources" / "game" / "game"
HAS_GAME = BUNDLE.is_dir()

def pytest_runtest_setup(item):
    if "game" in item.keywords and not HAS_GAME:
        pytest.skip("game bundle not found")

@pytest.fixture(scope="session")
def game_dir() -> Path:
    if not HAS_GAME:
        pytest.skip("game bundle not found")
    return BUNDLE
```

`tests/test_scaffold.py`:
```python
import digart

def test_version():
    assert digart.__version__ == "0.1.0"
```

- [ ] **Step 2:** Run `make check` → expect venv bootstrap, 1 passed.
- [ ] **Step 3:** `git add -A && git commit -m "chore: scaffold thedig-textures package"`

---

### Task 2: BOMP row decoder

**Files:**
- Create: `digart/bomp.py`, `tests/test_bomp.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `bomp_decode_line(dst: bytearray, dst_off: int, src: bytes, src_off: int, size: int, set_zero: bool = True) -> None` — decodes exactly `size` pixels of one BOMP line into `dst` at `dst_off`. Offsets (not slices) preserve C pass-by-value semantics: the caller's row cursor advances by the row, never by what the line wrote.

Upstream C (authoritative; vendored verbatim in Task 5):
```c
while (len > 0) {
    code = *src++;  num = (code >> 1) + 1;
    if (num > len) num = len;
    len -= num;
    if (code & 1) {                       // RLE run
        color = *src++;
        if (setZero || color) memset(dst, color, num);
        dst += num;
    } else {                              // literal run
        if (setZero) { memcpy(dst, src, num); src += num; dst += num; }
        else while (num--) { color = *src++; if (color) *dst = color; dst++; }
    }
}
```

- [ ] **Step 1: Write failing tests** `tests/test_bomp.py`:

```python
from digart.bomp import bomp_decode_line

def test_rle_run_fills():
    dst = bytearray(6)
    src = bytes([0b0000_1001, 0x42, 0b0000_0000, 0x00])  # RLE 5x0x42, then literal 1x0x00
    bomp_decode_line(dst, 0, src, 0, 6)
    assert dst == bytearray(b"\x42" * 5 + b"\x00")

def test_rle_run_clamped_to_size():
    dst = bytearray(3)
    src = bytes([0b0000_1111, 0x99])          # num=8 -> clamped to 3
    bomp_decode_line(dst, 0, src, 0, 3)
    assert dst == bytearray(b"\x99" * 3)

def test_literal_run_copy():
    dst = bytearray(4)
    src = bytes([0b0000_0100]) + b"\x11\x22\x33\x44"   # literal num=3
    bomp_decode_line(dst, 0, src, 0, 3)
    assert dst == bytearray(b"\x11\x22\x33\x00")

def test_set_zero_false_literal_zero_keeps_previous():
    dst = bytearray(b"\xAA" * 3)
    src = bytes([0b0000_0100, 0x00, 0x01, 0x02])
    bomp_decode_line(dst, 0, src, 0, 3, set_zero=False)
    assert dst == bytearray(b"\xAA\x01\x02")

def test_set_zero_false_rle_zero_keeps_previous():
    dst = bytearray(b"\xAA" * 3)
    src = bytes([0b0000_0101, 0x00])          # RLE num=3 color 0
    bomp_decode_line(dst, 0, src, 0, 3, set_zero=False)
    assert dst == bytearray(b"\xAA" * 3)

def test_dst_offset_respected():
    dst = bytearray(8)
    src = bytes([0b0000_1001, 0x77])
    bomp_decode_line(dst, 5, src, 0, 3)
    assert dst[:5] == bytearray(5) and dst[5:] == bytearray(b"\x77\x77\x77")

def test_mixed_opcodes_sequence():
    dst = bytearray(6)
    src = bytes([0b0000_0011, 0xAA, 0xBB]) + bytes([0b0000_0111, 0x42])  # lit2, RLE4
    bomp_decode_line(dst, 0, src, 0, 6)
    assert dst == bytearray(b"\xAA\xBB" + b"\x42" * 4)
```

- [ ] **Step 2:** Run `make check` → FAIL (ImportError).
- [ ] **Step 3: Implement `digart/bomp.py`** (faithful port, no "improvements"):

```python
def bomp_decode_line(dst: bytearray, dst_off: int, src: bytes, src_off: int,
                     size: int, set_zero: bool = True) -> None:
    assert size > 0
    while size > 0:
        code = src[src_off]; src_off += 1
        num = (code >> 1) + 1
        if num > size:
            num = size
        size -= num
        if code & 1:
            color = src[src_off]; src_off += 1
            if set_zero or color:
                dst[dst_off:dst_off + num] = bytes([color]) * num
            dst_off += num
        elif set_zero:
            dst[dst_off:dst_off + num] = src[src_off:src_off + num]
            src_off += num
            dst_off += num
        else:
            for _ in range(num):
                color = src[src_off]; src_off += 1
                if color:
                    dst[dst_off] = color
                dst_off += 1
```

- [ ] **Step 4:** `make check` → PASS. Commit `"feat: port BOMP row decoder from upstream bomp.cpp"`.

---

### Task 3: SAN container, palette state machine, frame emission

**Files:**
- Create: `digart/san.py`, `tests/fixtures/make_fixtures.py`, `tests/test_san.py`

**Interfaces:**
- Consumes: `DecodeError`.
- Produces:
  - `SanFrame` frozen dataclass: `.index: bytes` (len 64000), `.palette: bytes` (len 768).
  - `iter_frames(data: bytes, source: str = "?") -> Iterator[SanFrame]`.
  - Module constants `FRAME_W = 320`, `FRAME_H = 200`.
  - Raises `DecodeError` for malformed container. `SanReader.skipped: dict[str, int]` is public for diagnostics; `iter_frames` also exposes the reader via generator attribute — tests may construct `SanReader` directly for `skipped` inspection; `SanReader(data, source).frames()`.

Behavior (spec §4.1; upstream `smush_player.cpp` — follow exactly):
- Container: `ANIM` + u32BE total; chunks are `tag(4) + BE u32 size + payload`, advance `off = chunk_start + size + (size & 1)` for every chunk including `AHDR`. Top-level unknown tag → `DecodeError`.
- `AHDR` (payload len ≥ 0x306): u16LE version@0 (assert 2), u16LE numFrames@2, palette = payload[6:774], u16LE fps@0x306. Announced frame count stored on `reader.num_frames_announced` (a mismatch with the count of emitted frames is recorded in `skipped["FRAME_COUNT_MISMATCH"]`, never fatal).
- `FRME` sub-chunks: same BE-size/padding walk over the payload; per-frame local sub-chunk handlers; unknown sub-chunk → `skipped["?"+tag] += 1` (the engine would error; for extraction we log, and the census in Task 5's full-bundle run proves the set is benign — any surprise here is caught by `make verify` frame-count parity).
- `NPAL`: `pal = payload[0:768]` (assert len ≥ 0x300).
- `XPAL`: u16LE@0 (ignored), u16LE cmd@2.
  - cmd==256: skip u16LE@4; for i<768: `shifted[i] += delta[i]; pal[i] = clip(shifted[i] >> 7, 0, 255)`.
  - else: for j<768: `shifted[j] = pal[j] << 7; delta[j] = i16(u16LE@4+2j)`; if cmd==512 also `pal = payload[4+1536 : 4+1536+768]`.
- After processing every sub-chunk of a `FRME`, yield `SanFrame(bytes(buf), bytes(pal))` — always, even if nothing was drawn (matches the engine displaying the unchanged back buffer). `FOBJ`/`ZFOB` hooks: `self._fobj(payload)` exists from Task 4; until then they call `self._pending_fobj += 1` (fixture tests emit none).
- `buf = bytearray(64000)` zero-filled.

- [ ] **Step 1: Write fixtures** `tests/fixtures/make_fixtures.py`:

```python
import struct

def be(tag: bytes, payload: bytes) -> bytes:
    out = tag + struct.pack(">I", len(payload)) + payload
    if len(payload) & 1:
        out += b"\x00"
    return out

def fsub(tag: bytes, payload: bytes) -> bytes:
    return be(tag, payload)

def ahdr(payload_len: int = 0x31a, palette: bytes | None = None, num_frames: int = 0, fps: int = 12) -> bytes:
    p = bytearray(payload_len)
    struct.pack_into("<HH", p, 0, 2, num_frames)
    struct.pack_into("<H", p, 6 + 768, fps)
    if palette is not None:
        p[6:6 + 768] = palette
    return p

def xpal(cmd: int, delta: bytes = b"", full_palette: bytes | None = None) -> bytes:
    p = struct.pack("<HHH", 0, cmd, 0)           # LE u16 @0, cmd @2, u16 @4 (present only for 256; harmless otherwise? NO — see impl note)
    # Correct layouts:
    if cmd == 256:
        p = struct.pack("<HHH", 0, cmd, 0)        # 3 u16 LE then no palette data
    else:
        assert len(delta) == 768 * 2
        p = struct.pack("<HH", 0, cmd) + delta
        if full_palette is not None:
            assert len(full_palette) == 768
            p += full_palette
    return be(b"XPAL", p)

def npal(pal: bytes) -> bytes:
    return be(b"NPAL", pal)

def frame(*subs: bytes) -> bytes:
    return be(b"FRME", b"".join(subs))

def san(frames: list[bytes], palette: bytes = bytes(768)) -> bytes:
    body = be(b"AHDR", ahdr(palette=palette, num_frames=len(frames))) + b"".join(frames)
    return b"ANIM" + struct.pack(">I", 8 + len(body)) + body
```

**XPAL layout note for the implementer:** cmd==256 payloads carry exactly 3 LE u16s (8 bytes incl. pad byte allowance — assert payload size ≥ 8; a 6-byte payload is also tolerated: cmd 256 reads `@4` only if 8 bytes remain). cmd 512/other carry `2×u16 + 1536 bytes + [768]`.

- [ ] **Step 2: Write failing tests** `tests/test_san.py`:

```python
import struct
from digart import san as S
from digart.errors import DecodeError
from tests.fixtures import make_fixtures as fx

PAL_A = bytes([1, 2, 3] * 256)
PAL_B = bytes([4, 5, 6] * 256)

def frames_of(*subs_per_frame):
    data = fx.san([fx.frame(*subs) for subs in subs_per_frame], PAL_A)
    return list(S.iter_frames(data))

def test_frame_repeats_without_drawing():
    fs = frames_of((), ())
    assert len(fs) == 2
    assert fs[0].index == bytes(64000) and fs[0].palette == PAL_A
    assert fs[1].index == fs[0].index

def test_npal_replaces_palette_before_snapshot():
    fs = frames_of((fx.npal(PAL_B),))
    assert fs[0].palette == PAL_B

def test_xpal_full_replace():
    delta = struct.pack("<h", 0) * 768
    fs = frames_of((fx.xpal(512, delta, PAL_B),))
    assert fs[0].palette == PAL_B

def test_xpal_delta_accumulates_and_shifts():
    # start from base color 100<<7=12800, delta +128 -> (12800+128)>>7 == 101
    init = fx.npal(bytes([100] * 768))
    setup = fx.frame(init)
    fs_reader = S.SanReader(fx.san([setup]), "?")
    it = fs_reader.frames(); next(it)                 # frame 0: pal=100
    fs_reader._xpal(struct.pack("<HH", 0, 0) + struct.pack("<h", 128) * 768)   # cmd 0: store delta
    fs_reader._xpal(struct.pack("<HHH", 0, 256, 0))                            # cmd 256: apply
    assert fs_reader.pal[0] == 101
    fs_reader._xpal(struct.pack("<HH", 0, 0) + struct.pack("<h", -128) * 768)  # shifted=101<<7 again
    fs_reader._xpal(struct.pack("<HHH", 0, 256, 0))
    assert fs_reader.pal[0] == 100                    # (12928-128)>>7 == 100

def test_unknown_subchunk_recorded_not_fatal():
    data = fx.san([fx.frame(fx.be(b"ZZZZ", b"\x01\x02\x03\x04"))])
    r = S.SanReader(data)
    assert len(list(r.frames())) == 1
    assert r.skipped["ZZZZ"] == 1

def test_bad_container_raises():
    try:
        list(S.iter_frames(b"NUTS" + struct.pack(">I", 4) + b"\x00" * 4))
        assert False
    except DecodeError as e:
        assert e.offset == 0 and "ANIM" in e.reason

def test_odd_chunk_sizes_advance_with_pad():
    data = fx.san([fx.frame(fx.npal(PAL_B + b"\x00")), fx.frame()], PAL_A)
    # npal payload 768 even; force an odd one via unknown subchunk of 3 bytes
    data = fx.san([fx.frame(fx.be(b"PSAD", b"\x01\x02\x03")), fx.npal(PAL_B)], PAL_A)
    fs = list(S.iter_frames(data))
    assert fs[0].palette == PAL_B                     # after the odd-size chunk
```

- [ ] **Step 3:** Run → FAIL (module stub).
- [ ] **Step 4: Implement `digart/san.py`** per the behavior rules. Key structure:

```python
from collections.abc import Iterator
from dataclasses import dataclass, field
from .errors import DecodeError

FRAME_W, FRAME_H = 320, 200

@dataclass(frozen=True)
class SanFrame:
    index: bytes
    palette: bytes

@dataclass
class SanReader:
    data: bytes
    source: str = "?"
    pal: bytearray = field(default_factory=lambda: bytearray(768))
    delta: list = field(default_factory=lambda: [0] * 768)
    shifted: list = field(default_factory=lambda: [0] * 768)
    buf: bytearray = field(default_factory=lambda: bytearray(FRAME_W * FRAME_H))
    skipped: dict = field(default_factory=dict)
    num_frames_announced: int = 0
    _pending: int = 0

    def frames(self) -> Iterator[SanFrame]:
        d, n, off = self.data, len(self.data), 0
        if d[:4] != b"ANIM":
            raise DecodeError(self.source, 0, f"missing ANIM: {d[:4]!r}")
        off = 8
        emitted = 0
        while off + 8 <= n:
            tag, size = d[off:off + 4], int.from_bytes(d[off + 4:off + 8], "big")
            if size < 8 or off + size > n:
                raise DecodeError(self.source, off, f"bad {tag!r} chunk size {size}")
            body = off + 8
            if tag == b"AHDR":
                if size - 8 < 0x306:
                    raise DecodeError(self.source, body, f"AHDR too small {size - 8}")
                p = d[body:body + size - 8]
                ver, self.num_frames_announced = struct.unpack_from("<HH", p, 0)
                self.pal = bytearray(p[6:774])
            elif tag == b"FRME":
                self._feed(d[body:body + size - 8])
                emitted += 1
                yield SanFrame(bytes(self.buf), bytes(self.pal))
            else:
                self.skipped["top?" + tag.hex()] = 1
            off = body + size - 8 + ((size - 8) & 1)
        if self.num_frames_announced != emitted:
            self.skipped["FRAME_COUNT_MISMATCH"] = self.num_frames_announced - emitted

    def _feed(self, f: bytes) -> None:
        p = 0
        while p + 8 <= len(f):
            tag = f[p:p + 4]
            size = int.from_bytes(f[p + 4:p + 8], "big")
            payload = f[p + 8:p + 8 + size]
            if tag == b"NPAL":
                self.pal = bytearray(payload[:768])
            elif tag == b"XPAL":
                self._xpal(payload)
            elif tag == b"FOBJ":
                self._fobj(payload)
            elif tag == b"ZFOB":
                self._zfb(payload)
            else:
                self.skipped[tag.decode("latin1")] = self.skipped.get(tag.decode("latin1"), 0) + 1
            p += 8 + size + (size & 1)

    def _xpal(self, payload: bytes) -> None:
        cmd = int.from_bytes(payload[2:4], "little")
        if cmd == 256:
            for i in range(768):
                self.shifted[i] += self.delta[i]
                self.pal[i] = min(255, max(0, self.shifted[i] >> 7))
        else:
            for j in range(768):
                self.shifted[j] = self.pal[j] << 7
                v = int.from_bytes(payload[4 + 2 * j:6 + 2 * j], "little")
                self.delta[j] = v - 0x10000 if v > 0x7FFF else v
            if cmd == 512:
                self.pal = bytearray(payload[4 + 1536:4 + 1536 + 768])

    def _fobj(self, payload: bytes) -> None:      # implemented in Task 4
        self._pending += 1

    def _zfb(self, payload: bytes) -> None:       # implemented in Task 4
        self._pending += 1

def iter_frames(data: bytes, source: str = "?") -> Iterator[SanFrame]:
    return SanReader(data, source).frames()
```
(Add `import struct` at top. Chunk-size subtlety: outer `size` includes the 8-byte header; payload length is `size - 8`; padding computed from the payload length — matches BE-size semantics used in the real files.)

- [ ] **Step 5:** `make check` → PASS. Commit `"feat: SAN container walk with NPAL/XPAL palette state machine"`.

---

### Task 4: FOBJ/ZFOB back-buffer drawing

**Files:**
- Modify: `digart/san.py` (replace `_fobj`/`_zfb` stubs; add imports `zlib`, `bomp_decode_line`, `struct`)
- Create: `tests/test_san_draw.py`

**Interfaces:**
- Consumes: `bomp_decode_line`, `DecodeError`.
- Produces: unchanged public API; real FOBJ drawing.

Rules (port of `handleFrameObject` + `decodeFrameObject` + `smushDecodeRLE`, Dig path `_insanity=False`):
- Header (LE, 14 B): u16 codec, i16 left, i16 top, u16 w, u16 h, u16 objId, u16 parm2.
- Guard order, each returns silently (counts in `skipped`): `h > FRAME_H or w > FRAME_W` → `skip_big`; `(h, w) != (200, 320)` → `skip_small` (non-insane overlay objects are never displayed; objId `242x384` special-case likewise lands in `skip_small` — document with a comment that the engine routes it to a hidden buffer we deliberately do not expose).
- codec 1/3 (RLE): row cursor `p = top * FRAME_W + left` for row 0; per row `row_len = u16LE(payload[k])`; `bomp_decode_line(self.buf, p, payload, k + 2, w, set_zero=False)`; `k += row_len + 2`; `p += FRAME_W`. (C caller advances by `left` then `pitch-left` = `pitch`; the line decoder's own advance is lost — replicate exactly.)
- codec 20 (uncompressed): faithful port of the upstream transposed-cursor quirk: row 0 base = `left * FRAME_W + top` (yes, `pitch*left + top`), then `+FRAME_W` per row, memcpy `w` bytes.
- any other codec value → `DecodeError(self.source, offset, f"unsupported codec {codec}")` (must never fire on The Dig; `make verify` proves it).
- `ZFOB` payload: u32BE inflated size@0, then a zlib stream; `data = zlib.decompress(payload[4:])` (fall back to `zlib.decompressobj(-15)` raw if a file turns out raw — log which on first hit); header + draw identical to FOBJ from the inflated bytes.

- [ ] **Step 1: Write failing tests** `tests/test_san_draw.py`:

```python
import struct, zlib
from digart import san as S
from tests.fixtures import make_fixtures as fx

def runs(color: int, num: int) -> bytes:           # RLE opcodes covering num pixels (BOMP max run = 128)
    out = bytearray()
    while num:
        n = min(num, 128)
        out += bytes([((n - 1) << 1) | 1, color])
        num -= n
    return bytes(out)

def lit_zeros(n: int) -> bytes:                    # literal run of n zero bytes (BOMP max run = 128)
    return bytes([((n - 1) << 1)]) + bytes(n)

def fobj_payload(codec: int, left: int, top: int, w: int, h: int, rows: bytes) -> bytes:
    return struct.pack("<HhhHHHH", codec, left, top, w, h, 0, 0) + rows

def full_rows(color: int) -> bytes:
    enc = runs(color, 320)
    return b"".join(struct.pack("<H", len(enc)) + enc for _ in range(200))

def fullscreen(codec: int = 1, color: int = 0x42) -> bytes:
    if codec == 1:
        return fx.fsub(b"FOBJ", fobj_payload(1, 0, 0, 320, 200, full_rows(color)))
    raw = struct.pack("<HhhHHHH", 20, 0, 0, 320, 200, 0, 0) + bytes(color) * 64000
    return fx.fsub(b"FOBJ", raw)

def test_rle_fill_then_snapshot():
    fs = list(S.iter_frames(fx.san([fx.frame(fx.npal(bytes(768))), fx.frame(fullscreen(1, 0x42))])))
    assert fs[1].index[0] == 0x42 and fs[1].index[-1] == 0x42

def test_index_zero_rows_keep_previous():
    # frame1: full 0x11; frame2: rows 0-1 = 0x22, row2 = literal zeros (keep), rows 3-199 = RLE 0x00 (keep)
    enc22, enc00 = runs(0x22, 320), runs(0x00, 320)
    zero_lit = lit_zeros(128) + lit_zeros(128) + lit_zeros(64)
    rows = (struct.pack("<H", len(enc22)) + enc22) * 2 + \
           struct.pack("<H", len(zero_lit)) + zero_lit + \
           b"".join(struct.pack("<H", len(enc00)) + enc00 for _ in range(197))
    f2 = fx.fsub(b"FOBJ", fobj_payload(1, 0, 0, 320, 200, rows))
    data = fx.san([fx.frame(fx.npal(bytes(768))),
                   fx.frame(fx.fsub(b"FOBJ", fobj_payload(1, 0, 0, 320, 200, full_rows(0x11)))),
                   fx.frame(f2)])
    fs = list(S.iter_frames(data))
    assert fs[1].index[:320] == bytes([0x11]) * 320
    assert fs[2].index[:320] == bytes([0x22]) * 320          # explicit rows
    assert fs[2].index[640:960] == bytes([0x11]) * 320       # literal-zero row keeps 0x11
    assert fs[2].index[960:] == bytes([0x11]) * (64000 - 960) # RLE color-0 rows keep 0x11

def test_small_obj_skipped():
    small = fx.fsub(b"FOBJ", fobj_payload(1, 0, 0, 300, 200, b""))
    r = S.SanReader(fx.san([fx.frame(small)]))
    fs = list(r.frames())
    assert fs[0].index == bytes(64000) and r.skipped["skip_small"] == 1

def test_codec20_uncompressed():
    fs = list(S.iter_frames(fx.san([fx.frame(fx.npal(bytes(768))), fx.frame(fullscreen(20, 0x33))])))
    assert fs[1].index[0] == 0x33 and fs[1].index[-1] == 0x33

def test_zfb_roundtrip():
    inner = fobj_payload(1, 0, 0, 320, 200, full_rows(0x55))
    z = struct.pack(">I", len(inner)) + zlib.compress(inner, 9)
    fs = list(S.iter_frames(fx.san([fx.frame(fx.fsub(b"ZFOB", z))])))
    assert fs[0].index[0] == 0x55
```

- [ ] **Step 2:** Run → FAIL (stubs don't draw).
- [ ] **Step 3:** Implement `_fobj`/`_zfb` exactly per rules (note: row start offset = `top * FRAME_W + left`; the RLE loop advances the *row* by FRAME_W, drawing `w` pixels from each row's start).
- [ ] **Step 4:** `make check` PASS. Commit `"feat: FOBJ/ZFOB back-buffer compositing matching SmushPlayer"`.

---

### Task 5: Vendored C++ oracle + differential harness

**Files:**
- Create: `vendor/san-oracle/` (fetched upstream files + `shim.h`, `bomp_core.cpp`, `codec1_core.cpp`, `oracle_main.cpp`, `build.sh`, `UPSTREAM.txt`), `tools/diff_oracle.py`, `tests/test_oracle_fixture.py`

**Interfaces:**
- Produces: `vendor/san-oracle/san-oracle dump FILE` → stdout stream of records `b"FRMK" + "<HH"(w,h) + pal[768] + index[w*h]`, one per FRME, byte order of frames identical to the file. Exit 2 + stderr message on unsupported codec / malformed stream.
- Consumes: `iter_frames` for the Python side.

Design: the oracle must not re-implement upstream — it *is* upstream:
`bomp_core.cpp` and `codec1_core.cpp` are sed-extracted verbatim regions of the vendored `bomp.cpp`/`codec1.cpp`; `oracle_main.cpp` transcribes only the trivial chunk walk + the `handleDeltaPalette`/`handleNewPalette` bodies and the Dig-branch guards, calling `smushDecodeRLE`/`smushDecodeUncompressed`.

- [ ] **Step 1: Vendor.**
```bash
mkdir -p vendor/san-oracle && cd vendor/san-oracle
SHA=$(curl -s "https://api.github.com/repos/scummvm/scummvm/commits?per_page=1" | python3 -c "import json,sys;print(json.load(sys.stdin)[0]['sha'])")
for p in engines/scumm/bomp.h engines/scumm/bomp.cpp engines/scumm/codec1.cpp engines/scumm/codec20.cpp engines/scumm/nut_renderer.cpp; do
  curl -fsSL "https://raw.githubusercontent.com/scummvm/scummvm/$SHA/$p" -O
done
{ echo "scummvm commit: $SHA"; echo "verbatim upstream, GPL-3.0-or-later:"; shasum -a 256 bomp.h bomp.cpp codec1.cpp codec20.cpp nut_renderer.cpp; } > UPSTREAM.txt
git add -A && git commit -m "chore: vendor upstream scummvm decode sources for the oracle"
```
Expected: all 5 files non-empty; `grep -c 'void bompDecodeLine' bomp.cpp` = 1.

- [ ] **Step 2: `shim.h`**
```cpp
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
typedef uint8_t byte;
#define READ_LE_UINT16(p) ((uint16_t)(p)[0] | ((uint16_t)(p)[1] << 8))
#define READ_BE_UINT32(p) (((uint32_t)(p)[0] << 24) | ((uint32_t)(p)[1] << 16) | ((uint32_t)(p)[2] << 8) | (uint32_t)(p)[3])
#define CLIP(v, lo, hi) ((v) < (lo) ? (lo) : ((v) > (hi) ? (hi) : (v)))
#define error(...) do { fprintf(stderr, "oracle: " __VA_ARGS__); fputc('\n', stderr); exit(2); } while (0)
```

- [ ] **Step 3: `build.sh`** — extract, compile:
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
awk '/^void bompDecodeLine\(byte \*dst, const byte \*src, int len, bool setZero\)/,/^}/' bomp.cpp > _bomp_body.cpp
printf '#include "shim.h"\n' > bomp_core.cpp && cat _bomp_body.cpp >> bomp_core.cpp
awk '/^void smushDecodeRLE/,/^}/' codec1.cpp > _c1.cpp
awk '/^void smushDecodeUncompressed/,/^}/' codec20.cpp > _c20.cpp
{ printf '#include "shim.h"\n#include "codec.h"\n'; cat _c1.cpp _c20.cpp; } > codec1_core.cpp
printf '#pragma once\nvoid smushDecodeRLE(byte*, const byte*, int, int, int, int, int);\nvoid smushDecodeUncompressed(byte*, const byte*, int, int, int, int, int);\n' > codec.h
clang++ -O1 -w -std=c++17 -lz -o san-oracle bomp_core.cpp codec1_core.cpp oracle_main.cpp
echo built: vendor/san-oracle/san-oracle
```
(`bomp.cpp` also defines `bompDecodeLineReverse`/`drawBomp` needing ScummVM surfaces — excluded by the awk range. `smushDecodeRLE` needs `bompDecodeLine` — same TU link resolves it; the extracted region must be the `setZero` parameterless overload… verify after extraction: `grep -c 'bool setZero' _bomp_body.cpp` must be 1; if upstream's signature differs, adjust the awk pattern, not the body.)

- [ ] **Step 4: `oracle_main.cpp`** (~130 lines): struct `SmushDig { uint8 pal[768]; int16 delta[768]; int32 shifted[768]; uint8 buf[320*200]; }` with `handleNewPalette`, `handleDeltaPalette` copied line-for-line from `/tmp`-reference `smush_player.cpp` (fetch it into the repo? No — copy the two function bodies and the FRME/FOBJ switch into `oracle_main.cpp`, replacing `debugC`/`assert` with nothing; MKTAG → 4-char literals). Frame walk: same BE-size + pad rules as `digart/san.py`. After each FRME: `fwrite("FRMK",1,4,stdout); write(w,h as u16LE, pal, buf)`. ZFOB: `inflateInit`/`inflate` with zlib header, same 14-byte header dispatch. Unsupported codec / big obj: exit(2).

- [ ] **Step 5: `tools/diff_oracle.py`**:
```python
"""Byte-exact differential: digart.san vs vendored upstream oracle. Exit 1 on any mismatch."""
import struct, subprocess, sys
from pathlib import Path
from digart.san import iter_frames

ORACLE = Path(__file__).resolve().parent.parent / "vendor/san-oracle/san-oracle"
GAME = Path.home() / "Documents" / "The Dig®.app/Contents/Resources/game/game"

def oracle_records(p: Path):
    r = subprocess.run([str(ORACLE), "dump", str(p)], capture_output=True)
    if r.returncode:
        sys.exit(f"oracle failed {p.name}: {r.stderr.decode(errors='replace').strip()}")
    d, i = r.stdout, 0
    while i < len(d):
        if d[i:i + 4] != b"FRMK":
            sys.exit(f"oracle record desync at {i} in {p.name}")
        w, h = struct.unpack_from("<HH", d, i + 4); i += 8
        pal = d[i:i + 768]; i += 768
        idx = d[i:i + w * h]; i += w * h
        yield w, h, pal, idx

def main() -> int:
    files = sorted(GAME.glob("VIDEO/*.SAN"))
    bad = []
    for p in files:
        ours, theirs = list(iter_frames(p.read_bytes(), p.name)), list(oracle_records(p))
        why = None
        if len(ours) != len(theirs):
            why = f"frame count {len(ours)} vs {len(theirs)}"
        else:
            for n, (f, rec) in enumerate(zip(ours, theirs)):
                if (f.palette, f.index) != (rec[2], rec[3]):
                    off = next((k for k in range(len(f.index)) if f.index[k] != rec[3][k]), "palette")
                    why = f"frame {n} diff at {off}"; break
        print(("ok  " if not why else "FAIL") + f" {p.name}" + (f"  {why}" if why else f"  ({len(ours)} frames)"))
        if why:
            bad.append(p.name)
    print(f"\n{len(files) - len(bad)}/{len(files)} identical to oracle")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Fixture differential test** `tests/test_oracle_fixture.py`: skip if `ORACLE` missing; for the fixture SANs that draw (`test_san_draw`-style frames in tmp files), run `san-oracle dump` and compare record stream to `iter_frames` output — catches oracle/Python drift on synthetic streams.
- [ ] **Step 7: Run `make check` → PASS. `make oracle` builds. Run `tools/diff_oracle.py` once manually on the smallest real file only** (`PIGOUT.SAN`, via a one-off copy of `oracle_records` loop or temporarily narrowing `GAME.glob`) — if mismatches appear: the vendored upstream region is authoritative; fix `digart/san.py`, never the extracted regions. Commit once the full 55/55 pass is achieved (may iterate within this task).

- [ ] **Step 8: Commit** `"feat: vendored SMUSH oracle + byte-exact differential harness"`.

---

### Task 6: PNG writers + manifest

**Files:**
- Create: `digart/manifest.py`, `digart/pngout.py`, `tests/test_manifest.py`

**Interfaces:**
- Produces:
  - `AssetRecord(id, kind, source, frame, name, width, height, has_alpha, palette, path)` dataclass, `to_dict()` in spec §5.1 key order.
  - `palette_hash(pal: bytes) -> str` = `sha256(pal).hexdigest()`.
  - `ManifestBuilder(out_dir: Path)`: `.record_palette(pal: bytes) -> str`, `.add(rec: AssetRecord)`, `.finalize(extracted_at: str, game_root_hash: str) -> None` writing `manifest.json` + `palettes/<hash>.{json,png}`; insertion order preserved; counts computed at finalize.
  - `write_san_png(out_dir: Path, rel: Path, frame: SanFrame) -> None`;
    `write_indexed_png(out_dir: Path, rel: Path, index: bytes, w: int, h: int, pal: bytes, transparent0: bool) -> None`.

- [ ] **Step 1: Failing tests** `tests/test_manifest.py`: build 2 SAN records + 1 palette in `tmp_path`; assert `manifest.json` top-level keys, `counts.san_frames == 2`, palette sidecar `<hash>.json` has 256 `[r,g,b]` entries and `<hash>.png` strip; `write_san_png` output re-opened with Pillow equals `index→rgb(pal)` pixel-for-pixel; `transparent0` PNG has `getpixel((0,0))[3] == 0` where index==0 and `255` where index!=0; determinism: two identical runs byte-equal the PNG and manifest files (compare `read_bytes()`); id format `san:sq1:00000` via `rec_id("san", "SQ1.SAN", frame=0)` helper exported from manifest.py:
```python
def rec_id(kind: str, source: str, frame: int) -> str:
    stem = Path(source).stem.lower()
    return f"{kind}:{stem}:{frame:05d}"
```

- [ ] **Step 2: Implement.** Pillow RGB path for SAN: `Image.frombytes("RGB", (w,h), rgb_bytes)` (build rgb via `bytes(take3(pal[i]) for i in index)` through a translate table: `index.translate(bytes().join pal)` — simplest correct: `Image.frombytes("L", (w,h), index).convert("P", palette=Image.ADAPTIVE, colors=256)` is LOSSY — forbidden. Use `putpalette(pal[:768])` on mode `L` image and save with `transparency=...`? For opaque: `im = Image.frombytes("L", (w, h), index); im = im.convert("P"); im.putpalette(pal); im.convert("RGB").save(path)` — verify losslessness in test. For alpha: same, then `rgb = im.convert("RGB"); a = bytes(0 if px==0 else 255 ...)` via `index.translate(...)`, `rgb.putalpha(Image.frombytes("L",...,a))`, save `RGBA`.) Palette strip PNG: `Image.new("RGB", (256,1))` per color.
- [ ] **Step 3:** `make check` PASS. Commit `"feat: deterministic PNG and manifest writers"`.

---

### Task 7: NUT glyph/icon extraction

**Files:**
- Create: `digart/nut.py`, `tests/test_nut.py`; Modify: `tests/fixtures/make_fixtures.py` (add `mk_nut`), `vendor/san-oracle/UPSTREAM.txt` (nut_renderer.cpp already listed)

**Interfaces:**
- Consumes: `bomp_decode_line`, `DecodeError`.
- Produces: `NutImage(name: str, index: bytes, width: int, height: int, palette: bytes)`; `iter_images(data: bytes, source: str) -> Iterator[NutImage]`. `name = f"{Path(source).stem.lower()}:{i:03d}"`. Index 0 = transparent (decided by writer).

- [ ] **Step 0: Read the vendored truth.** Open `vendor/san-oracle/nut_renderer.cpp`, function `loadFont` (and `NutRenderer::codec1` / `codec21` just below it). The port is a *transcription*, not a reinterpretation: chunk pre-scan strides, `READ_LE_UINT16(dataSrc + offset + 14/+16)` glyph geometry, FRME payload → `FOBJ`-style rows, `smushDecodeRLE` into a glyph-sized buffer with pitch = glyph width (font path has NO screen-size guard). Glyph codec is 1 (BOMP rows) or 21; implement `nut_codec21` as given in this plan's appendix note below. Palette: NUT files carry the same AHDR 768-byte palette at payload[6:774] as SAN.
- [ ] **Step 1: Fixture + failing tests**: `mk_nut(num_chars=2, glyphs=[(8,8,index0bytes),(16,6,...)])` building AHDR(numChars@+2) + per-glyph `be(b"???", meta)` + `be(b"FRME", be(b"FOBJ", hdr+rows))` shapes matching the transcribed stride; assert `width/height` + first pixel + palette bytes. `@pytest.mark.game` test: `iter_images(FONT0.NUT.read_bytes())` yields ≥1 image, `all(0 < im.width and im.height)`.
- [ ] **Step 2: Implement `digart/nut.py`** per Step 0 transcription (raise `DecodeError` on stride desync).
- [ ] **Step 3: PASS + commit** `"feat: NUT glyph/icon extraction"`.

---

### Task 8: SCUMM v7 LA1 bitmaps

**Files:**
- Create: `tools/la1_census.py`, `docs/la1-census.txt`, `digart/la1.py`, `tests/test_la1.py`

**Interfaces:**
- Consumes: `bomp_decode_line`, `DecodeError`.
- Produces: `La1Bitmap(name: str, index: bytes, width: int, height: int, palette: bytes, transparent0: bool)`; `iter_bitmaps(la0: bytes, la1: bytes, errors: list[DecodeError]) -> Iterator[La1Bitmap]`.

- [ ] **Step 1: Census before code.** `tools/la1_census.py` walks: `LECF`(top chunk of DIG.LA1, payload contains `LOFF` + ROOMs) → `LOFF`: `u16LE count` (verified 367) + entries `u32LE offset + u8 kind` (verified ascending on the real file: 580, 181722, 1965645, 2000936). For each entry with `la1[off:off+4]==b'ROOM'`: BE-walk its 2-level children printing `tag size @offset` (first room children verified: `RMHD CYCL TRNS PALS WRAP OFFS APAL`). Output → `docs/la1-census.txt` via `python3 tools/la1_census.py > docs/la1-census.txt`. Also census entries whose kind byte != ROOM (which are those? costumes/sounds per `LOFF` kind byte — record the tag each offset lands on, one line per entry, plus the tag histogram). **Commit the census output with this task; it is the normative table for Step 2.**
- [ ] **Step 2: Implement** `digart/la1.py` from the census: parse `ROOM` children; for each bitmap-class tag found in the census, decode BOMP row data (`w,h` from `RMHD` or the tag's own header per census record — whichever the census proves) with `set_zero=True` for backgrounds (room `APAL` 768B 8-bit palette, fallback first `PALS` table) and `set_zero=False`-style semantics only for overlay classes (set `transparent0=True`). Scripts/sounds/charsets/arrays/`CYCL`/`TRNS`/`WRAP`/`OFFS` → recognized-and-skip. Any chunk > 4096 bytes with unrecognized tag → `errors.append(DecodeError("DIG.LA1", off, f"unhandled {tag!r}"))`.
- [ ] **Step 3: Tests**: synthetic LA0/LA1 (LECF+LOFF+ROOM+APAL+bg) asserting pixels + palette; `@game` test: full `iter_bitmaps` run prints counts; assert `len(bitmaps) >= 0` and `len(errors) / total_room_children < 0.10` (10% ceiling — census-driven, may tighten after census review).
- [ ] **Step 4: PASS + commit** `"feat: SCUMM v7 LA1 bitmap extraction"`.

---

### Task 9: CLI wiring, end-to-end, proofs

**Files:**
- Create: `digart/cli.py`, `tests/test_cli.py`; Modify: `README.md`, `docs/proofs/`

**Interfaces:**
- Consumes: `iter_frames`, `iter_images`, `iter_bitmaps`, `ManifestBuilder`, `rec_id`, `write_*_png`, `DecodeError`, `palette_hash`.
- Produces: `main(argv: list[str] | None = None) -> int`; exit 0/1/2 per spec §6.

- [ ] **Step 1: Implement `cli.py`**: argparse; `GAME_DEFAULT = str(Path.home() / "Documents" / "The Dig®.app")`; `extract`: preflight (required relative paths under `Contents/Resources/game/game`: `VIDEO/`, `DIG.LA0`, `DIG.LA1`; missing → print list, exit 2; disk: `shutil.disk_usage(out).free` vs `(15 if san else 0 + 1) << 30`, `--force` bypasses); build task list from `--only`; `ProcessPoolExecutor(max_workers=--jobs or min(4, os.cpu_count()))` mapping each file `_extract_one(path, out) -> tuple[list[dict], list[dict]]` — worker opens the file **read-only** with `Path.read_bytes`, decodes, writes PNGs under `out/<kind>/<STEM>/`, returns manifest dicts + `to_dict()` errors; parent merges (sorted by `(source, index)`), `ManifestBuilder.finalize`, `_errors.json` only when non-empty, prints summary. `verify`: `import tools.diff_oracle` main via importlib path (or `subprocess` with `sys.executable`) — exit its code.
- [ ] **Step 2: Failing tests** `tests/test_cli.py`: fake-game dir (tmp_path with synthetic 2-frame SAN + synthetic .nut built by fixtures, plus empty `DIG.LA0/LA1` placeholders that yield zero bitmaps and zero errors); `main(["extract", "--game", fake_app, "--out", str(out), "--jobs", "1"])` → 0; manifest ids + `san:sq1:00001` present + `verify`-absent ok. Missing bundle → 2, stderr mentions `VIDEO`. Errors fixture (truncated SAN bytes) → `_errors.json` + exit 1.
- [ ] **Step 3:** `make check` green, then the real run: `make verify` → **55/55 identical** (required; iterate Tasks 3/4 Python if not). Then real `thedig-textures extract` on the user's bundle; report total frames/PNGs/bytes; commit nothing from `out/` (gitignored).
- [ ] **Step 4: Proofs**: copy three first frames (`san/SQ1/00000.png`, `san/SQ10/00000.png`, `san/PIGOUT/00000.png`) into `docs/proofs/first-frames/`; write `docs/proofs/README.md` comparing to an in-game screenshot you take once (launch the game, pause on screen 1, macOS `cmd-shift-4` — or state the user-supplied screenshot path): document that HUD/dialogue text is a runtime overlay deliberately excluded; list which on-screen elements in the screenshot should match frame pixels (background art) vs overlay (text, cursor, item bar). Commit `"docs: first-frame proofs vs in-game screens"`.
- [ ] **Step 5:** Finalize `README.md` (real commands + manifest schema pointer + regeneration handoff note). `git add -A && git commit -m "feat: end-to-end CLI with full-bundle verification"`.

---

## Appendix — NUT codec21 (Task 7 transcription reference)

```python
def nut_codec21(buf, off, src, s_off, w, h, pitch):
    while h:
        row_end = s_off + 2 + int.from_bytes(src[s_off:s_off + 2], "little")
        s_off += 2
        length = w
        o = off
        while length > 0:
            skip = int.from_bytes(src[s_off:s_off + 2], "little"); s_off += 2
            o += skip * pitch; length -= skip
            if length <= 0:
                break
            run = int.from_bytes(src[s_off:s_off + 2], "little") + 1; s_off += 2
            length -= run
            n = run if length >= 0 else run + length
            buf[o:o + n] = src[s_off:s_off + n]
            o += n; s_off += n
        s_off = row_end; off += pitch; h -= 1
```
Port `off`/`dst` cursor exactly from the vendored C (`NutRenderer::codec21`); this appendix is a reading aid, the vendored file is authoritative.

## Plan Self-Review (done at authoring; re-check after any task deviation)

- Spec coverage: §2→T9 preflight; §3→T3/4 (SAN), T7 (NUT), T8 (LA1); §4→T2-T4, T7, T8 (format rules restated verbatim in each task); §5→T6 (+ ids via `rec_id`); §6→T9; §7→T5; §8→per-task test steps + T9 Step 3; §9→error paths in every module; §11→T9 disk preflight; §12→T9 Steps 3-4.
- Placeholders: none — every code step carries real code or a real command with its expected result. Two steps deliberately instruct "transcribe the vendored function" instead of re-typing 100+ lines; the vendored file is the content.
- Type consistency: `iter_frames(data, source)` (T3→T5→T9), `SanFrame.index/.palette` (T3→T6), `iter_images(data, source)` (T7→T9), `iter_bitmaps(la0, la1, errors)` (T8→T9), `AssetRecord`/`rec_id` (T6→T9), `DecodeError.to_dict` (T1→T6 `_errors.json`).
