# The Dig Texture Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `thedig-textures`, a Python CLI that extracts every SAN frame, NUT glyph/icon, and SCUMM v7 LA1 bitmap from the GOG *The Dig* `.app` into PNGs + a manifest, pixel-identical to what ScummVM's shipped SmushPlayer renders.

**Architecture:** Pure-Python ports of the upstream ScummVM decode paths (BOMP row RLE, SMUSH `ANIM/AHDR/FRME/NPAL/XPAL/FOBJ` including the stateful codec-37 delta-block decoder, NUT font walker, LECF/ROOM index), plus a small vendored C++ oracle harness built from the *actual* upstream `bomp.cpp`/`codec37.cpp`, used for byte-exact differential verification on all 55 `.SAN` files.

**Tech Stack:** Python 3.12, Pillow (only runtime dep), pytest (dev), stdlib `zlib`, clang++ (oracle build only).

**Spec:** `docs/superpowers/specs/2026-09-24-thedig-textures-design.md`. Read §4 (formats) before any task; it encodes format facts already verified against the bundle and upstream code.

## Global Constraints

- Python >= 3.12; runtime dependency: `pillow` only; dev dependency: `pytest`.
- License: GPL-3.0-or-later. Vendored upstream files keep their original headers; the sed-extracted regions in the oracle are verbatim (no re-typing).
- The game bundle (`~/Documents/The Dig®.app`) is opened **read-only, always**; nothing is ever written under it.
- Screen model for The Dig SANs: 320×200 (`FRAME_W = 320`, `FRAME_H = 200`). Palettes are 768-byte 8-bit RGB, used verbatim (no 6-bit scaling).
- SAN frames are opaque RGB: every `FRME`'s `FOBJ` is codec 37 (`SMUSH_CODEC_DELTA_BLOCKS`), a stateful delta-block decoder that writes a full 320×200 frame into the back buffer; NUT/LA1 glyph/costume bitmaps map index 0 to alpha 0 in the PNG writer.
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
digart/codec37.py                  DeltaBlocksDecoder — port of smush/codec37.cpp (SAN FOBJ codec 37)
digart/san.py                      SanFrame, iter_frames — SmushPlayer frame state machine
digart/nut.py                      NutImage, iter_images — port of NutRenderer::loadFont
digart/la1.py                      La1Bitmap, iter_bitmaps — LECF/LOFF/ROOM walker
digart/manifest.py                 AssetRecord, ManifestBuilder, palette_hash
digart/pngout.py                   deterministic PNG + palette-strip writers
digart/cli.py                      extract/verify, preflight, --jobs orchestration
tools/diff_oracle.py               python-vs-C++ differential over all .san files
tools/diff_nut.py                  python-vs-C++ differential over all .nut files
tools/la1_census.py                DIG.LA1 chunk-tag census (Task 9 Step 1)
vendor/san-oracle/UPSTREAM.txt     pinned scummvm commit SHA + file hashes
vendor/san-oracle/upstream/engines/scumm/{bomp.h,bomp.cpp,nut_renderer.cpp}   verbatim upstream
vendor/san-oracle/upstream/engines/scumm/smush/{codec1.cpp,codec37.cpp,codec37.h,smush_player.cpp}
vendor/san-oracle/inc/common/*.h   stub headers pulling in shim.h
vendor/san-oracle/shim.h           minimal byte/READ_* typedefs
vendor/san-oracle/bomp_core.cpp    sed-extracted upstream bompDecodeLine overloads
vendor/san-oracle/oracle_main.cpp  transcribed Dig-path SMUSH walk + FRMK emitter
vendor/san-oracle/build.sh
tests/conftest.py                  bundle fixture + game skip
tests/fixtures/make_fixtures.py    synthetic SAN/NUT/ROOM builders
tests/test_bomp.py test_san.py test_codec37.py test_nut.py test_la1.py
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
    src = bytes([0b0000_0010, 0xAA, 0xBB]) + bytes([0b0000_0111, 0x42])  # lit2, RLE4
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
  - Raises `DecodeError` for malformed container. `SanReader.skipped: dict[str, int]` is public for diagnostics; tests may construct `SanReader` directly for `skipped` inspection; `SanReader(data, source).frames()`.

Behavior (spec §4.1; upstream `smush_player.cpp` — follow exactly):
- Container: `ANIM` + u32BE total; chunks are `tag(4) + u32BE payload-size + payload` (the size field is the **payload length**, excluding the 8-byte header); advance `off = chunk_start + 8 + size + (size & 1)` for every chunk including `AHDR`. Top-level unknown tag → `DecodeError`.
- `AHDR` (payload len ≥ 0x306): u16LE version@0 (assert 2), u16LE numFrames@2, palette = payload[6:774], u16LE fps@0x306. Announced frame count stored on `reader.num_frames_announced` (a mismatch with the count of emitted frames is recorded in `skipped["FRAME_COUNT_MISMATCH"]`, never fatal).
- `FRME` sub-chunks: same BE-size/padding walk over the payload; per-frame local sub-chunk handlers; unknown sub-chunk → `skipped["?"+tag] += 1` (the engine would error; for extraction we log, and the census in Task 5's full-bundle run proves the set is benign — any surprise here is caught by `make verify` frame-count parity).
- `NPAL`: `pal = payload[0:768]` (assert len ≥ 0x300).
- `XPAL`: u16LE@0 (ignored), u16LE cmd@2.
  - cmd==256: skip u16LE@4; for i<768: `shifted[i] += delta[i]; pal[i] = clip(shifted[i] >> 7, 0, 255)`.
  - else: for j<768: `shifted[j] = pal[j] << 7; delta[j] = i16(u16LE@4+2j)`; if cmd==512 also `pal = payload[4+1536 : 4+1536+768]`.
- After processing every sub-chunk of a `FRME`, yield `SanFrame(bytes(buf), bytes(pal))` — always, even if nothing was drawn (matches the engine displaying the unchanged back buffer). `FOBJ` hook: `self._fobj(payload)` exists from Task 5; until then it calls `self._pending += 1` (fixture tests emit none). `ZFOB` is recognized-and-ignored (never occurs in the bundle).
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
            if off + 8 + size > n:
                raise DecodeError(self.source, off, f"bad {tag!r} chunk size {size}")
            body = off + 8
            if tag == b"AHDR":
                if size < 0x306:
                    raise DecodeError(self.source, body, f"AHDR too small {size}")
                p = d[body:body + size]
                ver, self.num_frames_announced = struct.unpack_from("<HH", p, 0)
                assert ver == 2
                self.pal = bytearray(p[6:774])
            elif tag == b"FRME":
                self._feed(d[body:body + size])
                emitted += 1
                yield SanFrame(bytes(self.buf), bytes(self.pal))
            else:
                raise DecodeError(self.source, off, f"unknown top-level chunk {tag!r}")
            off = body + size + (size & 1)
        if self.num_frames_announced != emitted:
            self.skipped["FRAME_COUNT_MISMATCH"] = self.num_frames_announced - emitted

    def _feed(self, f: bytes) -> None:
        p = 0
        while p + 8 <= len(f):
            tag = f[p:p + 4]
            size = int.from_bytes(f[p + 4:p + 8], "big")
            payload = f[p + 8:p + 8 + size]
            if tag == b"NPAL":
                assert len(payload) >= 0x300
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
(Add `import struct` at top. Chunk-size subtlety: outer `size` is the **payload length only** — it excludes the 8-byte `tag+size` header. Next chunk starts at `chunk_start + 8 + size + (size & 1)`. Verified against all 55 real `.SAN` files: the payload-only stride lands exactly on the next tag; the header-inclusive reading desyncs by 8 bytes. Padding is computed from the payload length.)

- [ ] **Step 5:** `make check` → PASS. Commit `"feat: SAN container walk with NPAL/XPAL palette state machine"`.

---

### Task 4: Vendored upstream sources + C++ oracle + differential harness

**Files:**
- Create: `vendor/san-oracle/{UPSTREAM.txt, shim.h, build.sh, oracle_main.cpp}`, vendored `vendor/san-oracle/upstream/engines/scumm/{bomp.h, bomp.cpp, nut_renderer.cpp, smush/codec1.cpp, smush/codec37.cpp, smush/codec37.h, smush/smush_player.cpp}`, stub headers `vendor/san-oracle/inc/common/{scummsys.h, endian.h, textconsole.h, util.h}` + `vendor/san-oracle/inc/graphics/surface.h`, `tools/diff_oracle.py`

**Interfaces:**
- Produces: `vendor/san-oracle/san-oracle dump FILE` → stdout stream of records `b"FRMK" + "<HH"(w,h) + pal[768] + index[w*h]`, one per `FRME`, in file order. Exit 2 + stderr message on malformed stream.
- The oracle compiles the vendored upstream `codec37.cpp` **verbatim**; it must not re-implement the decoder.

**Verified facts that fix this task's shape** (see spec §4.1; controller-verified against all 55 files):
- Every `FOBJ` is codec 37; there are no codec 1/3/20 `FOBJ` and no `ZFOB` in the bundle.
- The decoder is `SmushDeltaBlocksDecoder` (`smush/codec37.cpp`), constructed once per stream with `(320, 200)` and **stateful across frames**.
- All Dig game hooks are base-class no-ops (`smush_player.h:318-333`); `_insanity` is false; every `IACT` is audio-only `(code=8, flags=46)` and has no back-buffer effect.
- The `(height==242 && width==384)` special-buffer path (`smush_player.cpp:866`) never occurs (all FOBJ are 320×200).

- [ ] **Step 1: Vendor (correct paths).**
```bash
mkdir -p vendor/san-oracle/upstream/engines/scumm/smush && cd vendor/san-oracle
SHA=$(curl -s "https://api.github.com/repos/scummvm/scummvm/commits?per_page=1" | python3 -c "import json,sys;print(json.load(sys.stdin)[0]['sha'])")
for p in engines/scumm/bomp.h engines/scumm/bomp.cpp engines/scumm/nut_renderer.cpp \
         engines/scumm/smush/codec1.cpp engines/scumm/smush/codec37.cpp \
         engines/scumm/smush/codec37.h engines/scumm/smush/smush_player.cpp; do
  curl -fsSL "https://raw.githubusercontent.com/scummvm/scummvm/$SHA/$p" -o "upstream/$p"
done
{ echo "scummvm commit: $SHA"; echo "verbatim upstream, GPL-3.0-or-later:"; \
  (cd upstream && find . -type f -exec shasum -a 256 {} +); } > UPSTREAM.txt
```
Expected: 7 files non-empty; `grep -c 'SmushDeltaBlocksDecoder::decode' upstream/engines/scumm/smush/codec37.cpp` = 1.

- [ ] **Step 2: `shim.h` + stub headers.**
`shim.h` provides what the vendored TUs need:
```cpp
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
typedef uint8_t byte; typedef int8_t int8; typedef uint8_t uint8;
typedef int16_t int16; typedef uint16_t uint16; typedef int32_t int32; typedef uint32_t uint32;
#define READ_LE_UINT16(p) ((uint16_t)(p)[0] | ((uint16_t)(p)[1] << 8))
#define READ_LE_UINT32(p) ((uint32_t)(p)[0] | ((uint32_t)(p)[1] << 8) | ((uint32_t)(p)[2] << 16) | ((uint32_t)(p)[3] << 24))
#define READ_BE_UINT32(p) (((uint32_t)(p)[0] << 24) | ((uint32_t)(p)[1] << 16) | ((uint32_t)(p)[2] << 8) | (uint32_t)(p)[3])
#define CLIP(v, lo, hi) ((v) < (lo) ? (lo) : ((v) > (hi) ? (hi) : (v)))
#define error(...) do { fprintf(stderr, "oracle: " __VA_ARGS__); fputc('\n', stderr); exit(2); } while (0)
```
Stub headers under `inc/`: `inc/common/scummsys.h` (typedefs, pulled from `shim.h`), `inc/common/endian.h` (`READ_LE_UINT16/UINT32`), `inc/common/textconsole.h` (empty), `inc/common/util.h` (empty), and `inc/graphics/surface.h` (`namespace Graphics { struct Surface {}; }`, needed because the vendored `bomp.h` declares `BompDrawData` which embeds `Graphics::Surface`). Each is one `#include "../shim.h"` line (the `graphics/` stub needs one level less). Compile with `-I upstream/engines -I inc` so `"scumm/..."` resolves to the vendored files and `"common/..."`/`"graphics/..."` to the stubs.

- [ ] **Step 3: `build.sh`** — extract, compile, link:
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# bompDecodeLine (both overloads) as a standalone TU
awk '/^void bompDecodeLine\(byte \*dst, const byte \*src, int len, bool setZero\)/,/^}/' upstream/engines/scumm/bomp.cpp > _bomp_body.cpp
grep -q 'setZero' _bomp_body.cpp || { echo "bomp extraction failed" >&2; exit 1; }
{ printf '#include "shim.h"\n'; cat _bomp_body.cpp; } > bomp_core.cpp
# codec37.cpp verbatim + oracle_main.cpp
clang++ -O1 -w -std=c++17 -I upstream/engines -I inc -lz \
  -o san-oracle bomp_core.cpp upstream/engines/scumm/smush/codec37.cpp oracle_main.cpp
echo built: vendor/san-oracle/san-oracle
```
(If the 3-arg `bompDecodeLine(byte*, const byte*, int)` overload is also referenced by `codec37.cpp:573`, add a second awk range for it — verify with `grep -c 'bompDecodeLine' bomp_core.cpp`. Adjust the awk pattern, never the vendored body.)

- [ ] **Step 4: `oracle_main.cpp`** — transcribe ONLY the Dig path from the vendored `smush_player.cpp`:
  - Container walk: `ANIM` then `tag + u32BE payload-size + payload`, stride `chunk + 8 + size + (size & 1)` (payload-only; matches `digart/san.py`).
  - `AHDR`: `pal = payload[6:774]`; `NPAL`: `pal = payload[0:768]` (assert ≥ 0x300).
  - `XPAL`: copy `handleNewPalette`/`handleDeltaPalette` (`smush_player.cpp:815-853`) line-for-line: `uint8 pal[768]; int16 delta[768]; int32 shifted[768];` cmd 256 → `shifted[i] += delta[i]; pal[i] = CLIP(shifted[i] >> 7, 0, 255)`; else `shifted[j] = pal[j] << 7; delta[j] = READ_LE_UINT16(...)`; cmd 512 also reads 768 palette bytes.
  - `FOBJ`: read the 14-byte LE header; apply the `decodeFrameObject` guards (`smush_player.cpp:865-884`) for `_insanity=false`, screen 320×200: `h>200||w>320` → skip; `h!=200||w!=320` → skip. Otherwise dispatch codec 37 to one persistent `SmushDeltaBlocksDecoder(320, 200).decode(buf, payload + 14)`; any other codec → `error(...)`.
  - After each `FRME`: `fwrite("FRMK",1,4,stdout)`, write `w,h` as u16LE (320,200), then `pal[768]`, then `buf[64000]`.
  - Ignore `IACT`/`TRES`/`PSAD`/`TEXT`/`STOR`/`FTCH`/`SKIP`/`LOAD`/`GOST` (audio/script; no back-buffer effect). Unknown sub-chunk → ignore.

- [ ] **Step 5: `tools/diff_oracle.py`** — as the original plan (decode each file with `iter_frames` and with `san-oracle dump`; compare frame count, palette, index; exit 1 on any mismatch). This is the acceptance gate for Task 5; it will fail until the Python port lands.

- [ ] **Step 6: `make check` PASS; `make oracle` builds.** Gate for this task: `san-oracle dump` exits 0 on all 55 files and emits **12638** `FRMK` records total. Do not weaken `tools/diff_oracle.py` to make it pass.

- [ ] **Step 7: Commit** `"chore: vendor upstream scummvm decode sources + codec-37 oracle"`.


---

### Task 5: Codec 37 delta-blocks decoder port + 55/55 differential

**Files:**
- Create: `digart/codec37.py`, `tests/test_codec37.py`, `tests/test_oracle_fixture.py`
- Modify: `digart/san.py`

**Interfaces:**
- Consumes: `bomp_decode_line`, `DecodeError`, the vendored `vendor/san-oracle/upstream/engines/scumm/smush/codec37.cpp` (authoritative), the `san-oracle` binary from Task 4.
- Produces:
  - `digart.codec37.DeltaBlocksDecoder(width: int, height: int, rebel2_variant: bool = False)` with `.decode(dst: bytearray, src: bytes) -> None` writing `width * height` bytes into `dst`; **stateful across calls** (mirrors the persistent `_deltaBlocksCodec`).
  - `SanReader` holds one `DeltaBlocksDecoder(FRAME_W, FRAME_H)` per stream and calls it from `_fobj` for codec 37.

Rules (port of `SmushPlayer::decodeFrameObject` codec-37 branch, Dig path `_insanity=False`):
- Header (LE, 14 B): u16 codec, i16 left, i16 top, u16 w, u16 h, u16 objId, u16 parm2.
- Guards, each returns silently and counts in `skipped`: `h > FRAME_H or w > FRAME_W` → `skip_big`; `(h, w) != (FRAME_H, FRAME_W)` → `skip_small`.
- codec 37 → `decoder.decode(self.buf, payload[14:])`. Any other codec → `DecodeError(self.source, offset, f"unsupported codec {codec}")` (never fires on The Dig).
- Port `SmushDeltaBlocksDecoder` **verbatim** from the vendored `codec37.cpp`: `makeTable` (including the full `makeTableBytes` table), `proc1`, `proc3WithFDFE`, `proc3WithoutFDFE`, `proc4WithFDFE`, `proc4WithoutFDFE`, `decode`. Preserve the buffer layout and state exactly: one `bytearray(delta_size)` (`delta_size = frame_size * 3 + 0x13600`) with `delta_bufs` as memoryviews at `+0x4D80` and `+0xE880 + frame_size`; `cur_table`, `prev_seq_nb`, `offset_table`, `table_last_pitch`, `table_last_index`. `decode` case 2 calls the 3-arg `bompDecodeLine(dst, src, len)` overload → `bomp_decode_line(delta_buf, delta_offs[cur], src, 16, decoded_size, set_zero=True)`.
- Express `_deltaBufs[i]` as memoryviews into the single buffer so `dst + offsetTable[code] + nextOffs` and the `memset`/`memcpy` spans stay faithful in-bounds byte operations.

- [ ] **Step 1: Write failing tests.**
`tests/test_codec37.py` (hermetic):
```python
import struct
from digart.codec37 import DeltaBlocksDecoder

def test_case0_raw_copy():
    d = DeltaBlocksDecoder(320, 200)
    # case 0: src[0]=0, src[1]=table idx, src[2:4]=seq, src[4:8]=decodedSize, src[8:12]?, src[12]=mask, payload at +16
    body = bytes(range(256)) * 250                      # 64000 bytes
    src = bytes([0, 0, 0, 0]) + struct.pack("<I", 64000) + bytes(4) + bytes([0]) + body
    dst = bytearray(64000)
    d.decode(dst, src)
    assert bytes(dst) == body

def test_case2_bomp_rows():
    # case 2: BOMP row data at +16, decodedSize = payload length
    row = bytes([0b0000_1111, 0x77])                    # RLE num=8 color 0x77
    rows = (struct.pack("<H", len(row)) + row) * 200
    src = bytes([2, 0, 0, 0]) + struct.pack("<I", len(rows)) + bytes(4) + bytes([0]) + rows
    d = DeltaBlocksDecoder(320, 200)
    dst = bytearray(64000)
    d.decode(dst, src)
    assert dst[:8] == bytes([0x77]) * 8
```
(Adjust the case-0/case-2 `src` field offsets to the vendored header layout — `src[0]` variant, `src[1]` table index, `src[2:4]` seq, `src[4:8]` decodedSize, `src[12]` mask, compressed data at `+16`. The vendored file is authoritative; the brief's byte offsets are a reading aid.)

`tests/test_oracle_fixture.py`: skip when `vendor/san-oracle/san-oracle` is absent; write synthetic SANs (from `tests/fixtures/make_fixtures.py`) to `tmp_path` and assert `san-oracle dump` and `iter_frames` agree on frame count/palette/index.

- [ ] **Step 2:** Run `make check` → FAIL (module stub / `_fobj` still a counter).
- [ ] **Step 3:** Port `digart/codec37.py` and wire it into `SanReader._fobj` (add `from .codec37 import DeltaBlocksDecoder`; keep `_zfb` removed or as an explicit `DecodeError`, since no `ZFOB` exists — do not carry dead zlib code).
- [ ] **Step 4:** `make check` PASS, then `make verify` → **55/55 identical, 0 byte mismatches** (acceptance). If any file mismatches: the vendored upstream is authoritative — fix `digart/codec37.py`/`san.py`, never the oracle.
- [ ] **Step 5: Commit** `"feat: port codec-37 delta-blocks decoder; 55/55 byte-exact vs oracle"`.


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

### Task 7: NUT oracle + differential harness

**Files:**
- Modify: `vendor/san-oracle/oracle_main.cpp`, `vendor/san-oracle/build.sh`; Create: `tools/diff_nut.py`

**Interfaces:**
- Produces: `vendor/san-oracle/san-oracle nut FILE` → stdout stream of records `b"NUTG" + u16LE(w,h) + u8 transparency + pal[768] + index[w*h]`, one per glyph in file order. Exit 2 + stderr on malformed stream / unknown codec.
- The oracle compiles the vendored upstream `codec1.cpp` verbatim and the extracted `codec21` body verbatim.

**Verified NUT facts** (controller-verified across all 6 `.NUT` files):
- Layout: `ANIM` (u32BE length; the payload after the 8-byte header is the font data) → `AHDR` (palette at payload[6:774]; `numChars` = u16LE@10) → **one `FRME` per glyph, each containing exactly one `FOBJ`**. There is **no metadata chunk**. The FOBJ header carries the geometry, all LE relative to the FOBJ chunk start: `codec` u16LE@+8, `xoffs` i16LE@+10, `yoffs` i16LE@+12, `width` u16LE@+14, `height` u16LE@+16, glyph data at `+22`.
- Glyph counts equal `numChars`: FONT0-3 = 234 each, BIGFONT = 233, SMLFONT = 234 (1403 total).
- Codecs: `1` (BIGFONT) and `44` (the other five). Codec `21` never occurs; codec 44 is decoded by the `codec21` routine.
- Transparency: the glyph buffer is `memset` to `kDefaultTransparentColor = 0` for codec 1 and `kSmush44TransparentColor = 2` for codec 44 before decoding (`nut_renderer.h:37-38`).
- `NutRenderer::codec1` = `smushDecodeRLE(dst, src, 0, 0, width, height, pitch=width)` (`nut_renderer.cpp:61-63`); `codec21` is the self-contained routine at `nut_renderer.cpp:65-94`.

- [ ] **Step 1: Extend the build.** Add the vendored `upstream/engines/scumm/smush/codec1.cpp` to the `clang++` line in `build.sh` (it includes `common/endian.h` + `scumm/bomp.h`, both already shimmed). sed-extract the `codec21` method body (`nut_renderer.cpp:65-94`) into a free function `nut_codec21(byte *dst, const byte *src, int width, int height, int pitch)` — the body is verbatim; only the enclosing signature differs.
- [ ] **Step 2: Add the `nut` mode to `oracle_main.cpp`.** Parse `ANIM`→`AHDR`→per-glyph `FRME`/`FOBJ` per the verified layout; per glyph `memset` the buffer to the codec's transparent index, dispatch codec 1 → `smushDecodeRLE(dst, data, 0, 0, w, h, w)` and codec 44 → `nut_codec21(dst, data, w, h, w)`; emit `NUTG` + w,h + transparency + palette + glyph bytes. Unknown codec → `error(...)`.
- [ ] **Step 3: `tools/diff_nut.py`** — for each of the 6 real `.NUT` files, compare `san-oracle nut` records against `digart.nut.iter_images` (Task 8); same shape as `tools/diff_oracle.py`; exit 1 on any mismatch. It fails until Task 8 — do not weaken it.
- [ ] **Step 4: Gate.** `make check` green; `san-oracle nut` exits 0 on all 6 files and emits 1403 records total. Commit `"chore: extend oracle with NUT glyph differential"`.

---

### Task 8: NUT glyph/icon extraction + 6/6 differential

**Files:**
- Create: `digart/nut.py`, `tests/test_nut.py`; Modify: `tests/fixtures/make_fixtures.py` (add `mk_nut`), `Makefile` (run the NUT differential in `verify`)

**Interfaces:**
- Consumes: `bomp_decode_line`, `DecodeError`, the vendored `nut_renderer.cpp`, the `san-oracle nut` records.
- Produces:
  - `NutImage(name: str, index: bytes, width: int, height: int, palette: bytes, transparent: int)` — `transparent` is the index that maps to alpha 0 (`0` for codec 1, `2` for codec 44).
  - `iter_images(data: bytes, source: str) -> Iterator[NutImage]`; `name = f"{Path(source).stem.lower()}:{i:03d}"`.

Rules (transcribe `NutRenderer::loadFont` + `codec1`/`codec21` from the vendored file):
- Walk `ANIM` → `AHDR` → per-glyph `FRME`/`FOBJ` per the Task 7 layout; `palette = ahdr_payload[6:774]`; raise `DecodeError` on stride desync.
- Per glyph: `buf = bytearray(w*h)` memset to the transparency index; codec 1 → a local `smush_decode_rle(buf, data, w, h, pitch=w)` port of the vendored `smushDecodeRLE` (per row: `bomp_decode_line(buf, row, src, 2, w, set_zero=False)`; `src += u16LE(src) + 2`); codec 44 → `nut_codec21(buf, data, w, h, w)` ported from the vendored `codec21` (note: `dst += offs`, then copy `w` bytes — **not** `offs * pitch`).
- Unknown codec → `DecodeError`.

- [ ] **Step 1: Fixture + failing tests.** `mk_nut(glyphs=[(codec, w, h, payload), ...])` building `ANIM`+`AHDR`+one `FRME(FOBJ)` per glyph (no metadata chunk), with `numChars` at AHDR+10 and the palette at payload[6:774]. Assert width/height/palette/transparent and decoded pixels for a hermetic codec-1 and codec-44 glyph.
- [ ] **Step 2: Implement `digart/nut.py`** per the rules above.
- [ ] **Step 3:** `make check` green; add `$(PYTHON) tools/diff_nut.py` to the `verify` target; `make verify` → **6/6 identical, 0 byte mismatches** (plus 55/55 SAN). The oracle is authoritative — fix `digart/nut.py`, never the oracle.
- [ ] **Step 4: Commit** `"feat: NUT glyph/icon extraction; 6/6 byte-exact vs oracle"`.

---

### Task 9: SCUMM v7 LA1 bitmaps

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

### Task 10: CLI wiring, end-to-end, proofs

**Files:**
- Create: `digart/cli.py`, `tests/test_cli.py`; Modify: `README.md`, `docs/proofs/`

**Interfaces:**
- Consumes: `iter_frames`, `iter_images`, `iter_bitmaps`, `ManifestBuilder`, `rec_id`, `write_*_png`, `DecodeError`, `palette_hash`.
- Produces: `main(argv: list[str] | None = None) -> int`; exit 0/1/2 per spec §6.

- [ ] **Step 1: Implement `cli.py`**: argparse; `GAME_DEFAULT = str(Path.home() / "Documents" / "The Dig®.app")`; `extract`: preflight (required relative paths under `Contents/Resources/game/game`: `VIDEO/`, `DIG.LA0`, `DIG.LA1`; missing → print list, exit 2; disk: `shutil.disk_usage(out).free` vs `(15 if san else 0 + 1) << 30`, `--force` bypasses); build task list from `--only`; `ProcessPoolExecutor(max_workers=--jobs or min(4, os.cpu_count()))` mapping each file `_extract_one(path, out) -> tuple[list[dict], list[dict]]` — worker opens the file **read-only** with `Path.read_bytes`, decodes, writes PNGs under `out/<kind>/<STEM>/`, returns manifest dicts + `to_dict()` errors; parent merges (sorted by `(source, index)`), `ManifestBuilder.finalize`, `_errors.json` only when non-empty, prints summary. `verify`: run both differentials (`tools/diff_oracle.py`, `tools/diff_nut.py`) — exit non-zero on any mismatch.
- [ ] **Step 2: Failing tests** `tests/test_cli.py`: fake-game dir (tmp_path with synthetic 2-frame SAN + synthetic .nut built by fixtures, plus empty `DIG.LA0/LA1` placeholders that yield zero bitmaps and zero errors); `main(["extract", "--game", fake_app, "--out", str(out), "--jobs", "1"])` → 0; manifest ids + `san:sq1:00001` present + `verify`-absent ok. Missing bundle → 2, stderr mentions `VIDEO`. Errors fixture (truncated SAN bytes) → `_errors.json` + exit 1.
- [ ] **Step 3:** `make check` green, then the real run: `make verify` → **55/55 SAN + 6/6 NUT identical** (required; iterate the Python ports if not). Then real `thedig-textures extract` on the user's bundle; report total frames/PNGs/bytes; commit nothing from `out/` (gitignored).
- [ ] **Step 4: Proofs**: copy three first frames (`san/SQ1/00000.png`, `san/SQ10/00000.png`, `san/PIGOUT/00000.png`) into `docs/proofs/first-frames/`; write `docs/proofs/README.md` comparing to an in-game screenshot you take once (launch the game, pause on screen 1, macOS `cmd-shift-4` — or state the user-supplied screenshot path): document that HUD/dialogue text is a runtime overlay deliberately excluded; list which on-screen elements in the screenshot should match frame pixels (background art) vs overlay (text, cursor, item bar). Commit `"docs: first-frame proofs vs in-game screens"`.
- [ ] **Step 5:** Finalize `README.md` (real commands + manifest schema pointer + regeneration handoff note). `git add -A && git commit -m "feat: end-to-end CLI with full-bundle verification"`.

---

## Appendix — NUT codec21 (Task 8 transcription reference)

```python
def nut_codec21(buf, off, src, s_off, w, h, pitch):
    while h:
        row_next = s_off + 2 + int.from_bytes(src[s_off:s_off + 2], "little")
        s_off += 2
        length = w
        o = off
        while True:
            skip = int.from_bytes(src[s_off:s_off + 2], "little"); s_off += 2
            o += skip; length -= skip              # pixels, NOT skip * pitch
            if length <= 0:
                break
            run = int.from_bytes(src[s_off:s_off + 2], "little") + 1; s_off += 2
            length -= run
            n = run if length >= 0 else run + length
            buf[o:o + n] = src[s_off:s_off + n]
            o += n; s_off += n
            if length <= 0:                        # C `do { ... } while (len > 0)`
                break
        s_off = row_next; off += pitch; h -= 1
```
The vendored `NutRenderer::codec21` (`nut_renderer.cpp:65-94`) is authoritative; this appendix is a reading aid. Note the skip advances by **pixels** (`o += skip`), not rows.

## Plan Self-Review (re-checked after the codec-37 and NUT re-plans)

- Spec coverage: §2→T10 preflight; §3→T3/T5 (SAN), T7/T8 (NUT), T9 (LA1); §4→T2-T5, T7/T8, T9 (format rules restated verbatim in each task); §5→T6 (+ ids via `rec_id`); §6→T10; §7→T4/T5 (SAN oracle→port), T7/T8 (NUT oracle→port); §8→per-task test steps + T10 Step 3; §9→error paths in every module; §11→T10 disk preflight; §12→T10 Steps 3-4.
- Verified against the bundle: all 12,637 SAN `FOBJ` are codec 37 (no 1/3/20, no `ZFOB`); 12,638 `FRME`; all `IACT` audio-only. NUT = `AHDR` + one `FRME`/`FOBJ` per glyph (no metadata chunk); codecs 1 and 44; transparency 0/2 by codec; 1403 glyphs. The plan matches both.
- Placeholders: none — every code step carries real code or a real command with its expected result. Steps that instruct "transcribe the vendored function" (T4 `oracle_main.cpp`, T5 `codec37.py`, T7 oracle `nut` mode, T8 `nut.py`) name the vendored file as the content.
- Type consistency: `iter_frames(data, source)` (T3→T5→T10), `SanFrame.index/.palette` (T3→T6), `DeltaBlocksDecoder.decode(dst, src)` (T5), `san-oracle dump`/`nut` records (T4/T7→T5/T8), `NutImage.transparent` (T8→T10), `iter_bitmaps(la0, la1, errors)` (T9→T10), `AssetRecord`/`rec_id` (T6→T10), `DecodeError.to_dict` (T1→T6 `_errors.json`).
