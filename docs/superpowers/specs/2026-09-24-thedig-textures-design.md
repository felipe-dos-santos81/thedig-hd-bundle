# The Dig Texture Extraction — Design Spec

Date: 2026-09-24
Status: approved for implementation planning
Project: `~/code/mine/thedig-textures`

## 1. Purpose

Extract every piece of game art from the GOG macOS bundle of *The Dig* (1995) into PNG
still images plus a machine-readable manifest, so an AI regeneration pipeline can consume
them. Extraction must be pixel-exact: decoded frames match what the shipped engine renders,
verified differentially against upstream ScummVM decode code.

The game ships as a SCUMM v7 title (`GID_DIG`) running on a bundled, GOG-modified
ScummVM 1.7.0. Its visuals are not PNG/BMP files; they are custom formats that must be
decoded.

## 2. Source layout (read-only input)

Bundle root: `~/Documents/The Dig®.app/Contents/Resources/game/game/`

| Path | What it holds |
|---|---|
| `VIDEO/*.SAN` (55 files) | Westwood SMUSH animation streams (`ANIM` container): scene backgrounds (`SQ*.SAN`, `TRAM*`, `RTRAM*`, `ALCOVE`, `NEXUSPAN`, `DARKCAVE`, …), FMV cutscenes, and animated props. Primary texture source. `VIDEO/` also holds `FONT0..3.NUT` and `DIGTXT.TRS`. |
| `DIG.LA0`, `DIG.LA1` | SCUMM v7 index (room directories: `RNAM`, `MAXS`, `DROO`, `DSCR`, …) and room-data archive. Holds embedded bitmap resources (room backdrops, sprite/costume sheets, screens). |
| `VIDEO/FONT0..3.NUT`, `_other/BIGFONT.NUT`, `_other/SMLFONT.NUT` | LucasArts `.nut` bitmap fonts and icon/image sheets (the game renders text and icons from these). |
| `DIGMUSIC.BUN`, `DIGVOICE.BUN`, `*.TRS` | Audio and text. Out of scope. |

The tool treats the bundle as strictly read-only. It never opens a file for writing under
the game root and never mutates the `.app`.

## 3. Scope

In scope
- All frames of all 55 `.SAN` files (every frame, including near-duplicates).
- All bitmap images in all `.NUT` files.
- All bitmap-bearing resources found in `DIG.LA1` via `DIG.LA0`; every resource that
  cannot be decoded is recorded with a reason, not silently dropped.
- A single manifest, palette sidecars, and a differential verification harness.

Out of scope (explicit non-goals)
- Audio, music, speech, translated text.
- The AI regeneration itself (next phase; manifest is its input).
- Re-encoding assets back into game formats.
- The Nightdive HD remaster assets (not present in this bundle).
- Live-launching or driving the bundled engine.

## 4. Formats and authoritative references

Byte-exact field layouts are defined by the upstream code, pinned at a commit in
`vendor/` (see §7). The spec fixes structure and invariants, not a re-typed hex table.

### 4.1 SAN (Westwood SMUSH — verified against the bundle and ScummVM's SmushPlayer)
`ANIM` container (tag + u32BE total size) holding `AHDR` (u16LE version=2, u16LE
numFrames, u16[4], 768-byte **8-bit RGB palette** at offset 6 — used verbatim, no 6-bit
scaling, u16LE fps at 0x306) followed by one `FRME` per frame. Each `FRME` is a sequence
of BE-tagged, BE-sized, even-padded sub-chunks:

- `NPAL` — replace the full 768-byte palette.
- `XPAL` — delta palette: u16LE ×2 (second = command); command 512 reads 768 signed u16
  deltas and then a full palette; command 256 applies accumulated deltas
  (`shifted += delta; color = clip(shifted >> 7)`), exactly as
  `SmushPlayer::handleDeltaPalette`.
- `FOBJ` — draw object: u16LE codec (1 or 3 → row-BOMP RLE; 20 → uncompressed), i16LE
  left, i16LE top, u16LE width, u16LE height, 4 reserved LE bytes; payload = per row
  [u16LE row-size][BOMP bytes]. BOMP `bompDecodeLine(setZero=false)`: literal bytes equal
  to 0 leave the back-buffer pixel unchanged — for The Dig **index 0 is "keep previous
  pixel"**, not transparency.
- `ZFOB` — u32BE inflated size + zlib stream wrapping a `FOBJ`.
- `PSAD`, `IACT`, `TRES`, `TEXT`, `STOR`, `FTCH`, `SKIP`, `LOAD`, `GOST` — audio, game
  scripting, and font-overlay chunks: skipped. Text/HUD is a runtime overlay and is
  deliberately **not** baked into extracted frames — clean video-buffer imagery is the
  regeneration source.

Extraction models the engine's back buffer: persistent 320×200 buffer; `FOBJ` objects
whose size differs from the screen are skipped (the shipped engine does the same); after
each `FRME`, the current buffer (indexed + active palette) is emitted as a frame, even
when the frame changed nothing. `digart/san.py` yields `(indexed_bytes, palette)` per
frame; SAN output PNGs are opaque RGB (no alpha).

### 4.2 NUT
LucasArts `.nut` = an SMUSH `ANIM`/`AHDR` container (glyph count = u16LE at AHDR+10)
followed by two chunks per glyph: metadata (glyph width u16LE @+14, height u16LE @+16)
and a `FRME` with the glyph pixels (row-BOMP `FOBJ`, codec 1/21), per ScummVM's
`NutRenderer::loadFont`. Glyph/icon index 0 **is** the transparent color → each glyph is
emitted as RGBA PNG.

### 4.3 SCUMM v7 `DIG.LA0`/`DIG.LA1`
`LA0` (16 KB) is the v7 index: `RNAM` (u16LE id + 9 name bytes XOR 0xFF), `MAXS`,
`DROO`, `DSCR`, `DSOU`, `DCOS`, `DCHR`, `DOBJ`, `AARY`, `ANAM`, per
`engines/scumm/resource.cpp` (v7 data is unencrypted). `LA1` (88.6 MB) is a single
`LECF` container: a `LOFF` offset directory (u16LE count + (u32LE offset, u8 kind)
entries, ascending) followed by one `ROOM` chunk per entry. Room children (`RMHD`,
`CYCL`, `TRNS`, `PALS`, `WRAP`, `OFFS`, `APAL`, plus bitmap-bearing chunks) are walked as
upstream `engines/scumm/room.cpp` does; bitmaps are decoded via the same BOMP row path
with the room's own 8-bit `APAL`/`PALS` palette; index 0 → alpha. Scripts, sounds,
charsets and arrays are recognized and skipped. The exact bitmap tag inventory is
captured by the §8 census probe before the decoder ships; every decodable bitmap is
extracted, every other chunk logged.

Where the shipped GOG 1.7.0 fork differs from upstream on any of these paths, the
differential gate (§7) fails loudly; the pinned commit is chosen so it passes.

## 5. Output layout

All paths under `--out` (default `./out/`, gitignored):

```
out/
  san/<NAME>/<frame:05d>.png        # e.g. san/SQ1/00000.png
  nut/<STEM>/img_<entry:03d>.png    # icon/glyph sheets per .nut file
  la1/<resource-name>[_<i>].png     # embedded room/sprite bitmaps
  palettes/<hash>.json              # 256×[r,g,b] 8-bit color table
  palettes/<hash>.png               # 256×1 palette strip for visual conditioning
  manifest.json
  _errors.json                      # written only if errors occurred
```

PNG writing strips timestamps so output is reproducible run-to-run.

### 5.1 Manifest schema

```json
{
  "tool": "thedig-textures",
  "tool_version": "0.1.0",
  "extracted_at": "2026-09-24T12:00:00Z",
  "game_root": "sha256 over sorted (relative path, size) pairs of the game dir",
  "counts": {"san_frames": 0, "nut_images": 0, "la1_bitmaps": 0, "errors": 0},
  "assets": [
    {
      "id": "san:sq1:00000",
      "kind": "san_frame | nut_image | la1_bitmap",
      "source": "VIDEO/SQ1.SAN",
      "frame": 0,
      "name": null,
      "width": 320, "height": 200,
      "has_alpha": true,
      "palette": "<hash>",
      "path": "san/SQ1/00000.png"
    }
  ]
}
```

Rules: `id` = `"<kind-prefix>:<source-stem-lower>:<zero-padded index>"`; `frame`/`name`
set per kind; `palette` is the hex sha256 of the 8-bit color table; entries are emitted
in deterministic source-file/frame order. `has_alpha` is always `false` for `san_frame`
(opaque back-buffer; index 0 = keep-previous), and `true` for `nut_image`/`la1_bitmap`
(index 0 = transparent). A regeneration pipeline can group, condition, and trace every
PNG from this file alone.

## 6. CLI

```
thedig-textures extract [--game <path-to-.app>] [--out <dir>]
                        [--only san,nut,la1] [--jobs N]
thedig-textures verify  [--out <dir>]
```

- Defaults: `--game ~/Documents/The Dig®.app`, `--out ./out`, `--jobs` = min(4, CPUs).
- `verify` runs the §7 differential gate and exits non-zero on any mismatch.
- Pre-flight: game root exists and contains the expected files (fail with the list of
  missing files); free disk at `--out` ≥ 15 GB for a full run (estimated all-frames
  output 2–10 GB; abort with a clear message, `--force` overrides; `--only` runs scale
  the requirement to the selected kinds: san 15 GB, nut/la1 1 GB).
- Exit codes: 0 success with zero errors, 1 errors recorded, 2 usage/preflight failure.

## 7. Pixel-exact verification (oracle)

- `vendor/san-oracle/` holds pinned upstream files that carry the decode logic in
  self-contained functions: `engines/scumm/bomp.cpp` (`bompDecodeLine`) and
  `engines/scumm/codec1.cpp` (`smushDecodeRLE`), plus a `oracle.cpp` harness that
  transcribes the `FRME`/`FOBJ`/`NPAL`/`XPAL` walk and back-buffer rules from
  `engines/scumm/smush/smush_player.cpp`. `build.sh` compiles it into `san-oracle`;
  `san-oracle dump FILE` emits, per frame, a fixed binary record: dimensions, active
  768-byte palette, indexed pixels. (Note: scummvm-tools' `compress_scumm_san` was
  evaluated and rejected — it rewrites headers and strips audio but never decodes
  pixels, so it cannot serve as an oracle.)
- `tools/diff_oracle.py`: for all 55 `.SAN` files, decode with `digart/san.py` and with
  the oracle binary; assert identical frame count, dimensions, palette bytes, and
  indexed pixel bytes. Any mismatch prints file, frame index, first differing offset.
- `make verify` runs unit tests then the full differential pass. Acceptance requires
  55/55 files, 0 byte mismatches.
- `LA1`/`NUT` correctness reuses the same oracle functions for their row-BOMP payload
  paths, plus hermetic fixtures (§8) and manual proof: documented comparison of first
  frames of `SQ1`/menu screens against the running game (recorded under `docs/proofs/`
  after first run).

## 8. Testing

- Unit tests (hermetic, no game copy needed): fixture generators under
  `tests/fixtures/` produce a 1-frame SAN, a multi-frame SAN with a mid-stream `XPAL`
  palette change, and a SAN whose BOMP rows carry index-0 keep-previous pixels; expected
  indexed+palette bytes pinned from the oracle once. Same for one minimal `.nut` glyph
  file and one synthetic `ROOM` chunk.
- Integration tests marked `game` (skipped when the bundle is absent): run `extract
  --only san` over the three smallest `.san` files and `verify` over all 55.
- Manifest tests: schema validation, deterministic ordering, id uniqueness.
- Error handling: truncated chunk, bad opcode, and bad offset fixtures each produce a
  `DecodeError(file, offset, reason)` entry in `_errors.json` and do not abort the run.

## 9. Errors and edge cases

- Unknown/extra chunks (e.g. audio in `FRME` streams, `RTRAM` duplicates, demo files):
  skipped by design where safe, logged where a resource could not be decoded.
- SANs whose frames never clear transparency: alpha preserved, never baked to black.
- Unicode path (`The Dig®.app`): handled natively by `pathlib`; no shell string paths.
- A corrupted or empty source file: recorded in `_errors.json`, run continues.

## 10. Module structure

```
digart/
  san.py       SMUSH reader + frame compositor (indexed buffer + palette + alpha mask)
  nut.py       .nut sheet/image parser
  la1.py       SCUMM v7 index + room bitmap extraction
  manifest.py  asset record builder, deterministic writer, hashers
  pngout.py    PNG/palette strip writing, no-timestamp policy
  cli.py       argparse entrypoint, preflight, orchestration, --jobs
  errors.py    DecodeError and per-file error report
```

Each module is independently testable and has one owner per format. Runtime deps:
`pillow` only; dev deps: `pytest`. License: GPL-3.0-or-later (matches vendored code).

## 11. Risks

- Frame volume: "all frames" chosen knowingly; worst case is ~200 k+ PNGs / ~10 GB.
  Mitigation: disk preflight, `--only`, and manifest-driven downstream sampling.
- GOG 1.7.0 fork vs upstream drift: caught by `make verify`; pin a commit that passes.
- `.nut`/`LA1` bitmap coverage may reveal undocumented sub-formats: they fall back to
  logged errors, never silent skips — a later plan can extend without schema change.

## 12. Success criteria (definition of done)

1. `thedig-textures extract` completes on the user's bundle with zero unexpected errors.
2. `make verify`: 55/55 SAN files byte-identical to the oracle; unit tests green.
3. Every `.NUT` image and every decodable `LA1` bitmap present under `out/` and listed
   in `manifest.json`; each manifest entry's `path` exists and its `width`/`height`/
   `palette` match the file on disk.
4. The `.app` bundle is unmodified (`git`-independent check: mtimes/sizes unchanged).
