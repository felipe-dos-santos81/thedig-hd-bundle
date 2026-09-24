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

### 4.1 SAN (Westwood SMUSH)
`ANIM` container with size/version header and chunked payload: `AHDR` (frame count,
width, height, color depth, frame-rate hints), `PALE` (256-color palettes of 6-bit RGB
components, scaled to 8-bit by ×4 with the same rounding the engine uses), `BONE`
(scene/element metadata), `FRME` per frame, `SPR#` per element inside a frame, plus audio
chunks (`SAHD`/`SND `) which the tool skips. Frames are built by running the opcode-RLE
sprite streams onto the back buffer: opcodes encode copy-skip runs, solid runs,
palette-change runs, and pixel-delta runs; a designated index (or off-screen draw) acts
as the color key. `digart/san.py` yields, per frame: `uint8` indexed buffer + active
palette + set of transparent pixels.

### 4.2 NUT
LucasArts `.nut` (as parsed by ScummVM's `engines/scumm/nut_renderer.cpp`): header,
palette(s), and a per-glyph/image entry table with size and pixel data. Each entry is
emitted as an RGBA PNG (entries that carry a transparent key get alpha).

### 4.3 SCUMM v7 `DIG.LA0`/`DIG.LA1`
Parse the `LA0` index: `RNAM`, `MAXS`, `DROO`, `DSCR`, `DSOU`, `DCOS`, `DCHR`, `DOBJ`,
`ANAM` per `engines/scumm/resource.cpp` (v7 is unencrypted; `DIG.LA1` is the single data
disk). Follow room offsets into `DIG.LA1`, walk room sub-chunks, and decode the
bitmap-bearing chunks (v7 background/`bgbg` data and sprite/costume image blocks) with
the BOMP/RLE path of `engines/scumm/gfx.cpp`. Room scripts, sound, and character
definitions are recognized and skipped.

Where the shipped GOG 1.7.0 fork differs from upstream on any of these three paths, the
differential gate (§7) fails loudly; the pinned commit is chosen so it passes.

## 5. Output layout

All paths under `--out` (default `./out/`, gitignored):

```
out/
  san/<NAME>/<frame:05d>.png        # e.g. san/SQ1/00000.png
  nut/<STEM>/img_<entry:03d>.png    # icon/glyph sheets per .nut file
  la1/<resource-name>[_<i>].png     # embedded room/sprite bitmaps
  palettes/<hash>.json              # 256×[r,g,b] 8-bit table + 6-bit source table
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
in deterministic source-file/frame order. A regeneration pipeline can group, condition,
and trace every PNG from this file alone.

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

- `vendor/san-oracle/` holds a pinned copy of upstream scummvm-tools SAN parsing
  (`engines/scumm/compress_scumm_san.cpp` plus minimal stream helpers) and a `build.sh`
  that compiles a single-file CLI: given a `.san`, it emits each frame's raw indexed
  buffer and palette to stdout/`--out-dir`.
- `tools/diff_oracle.py`: for all 55 `.SAN` files, decode with `digart/san.py` and with
  the oracle binary; assert identical frame count, dimensions, palette bytes, and
  indexed pixel bytes. Any mismatch prints file, frame index, first differing offset.
- `make verify` runs unit tests then the full differential pass. Acceptance requires
  55/55 files, 0 byte mismatches.
- `LA1`/`NUT` correctness is covered by hermetic fixtures (§8) plus manual proof:
  documented comparison of first frames of `SQ1`/menu screens against the running game
  (recorded under `docs/proofs/` after first run).

## 8. Testing

- Unit tests (hermetic, no game copy needed): hand-built fixture generators under
  `tests/fixtures/` produce a 1-frame SAN, a multi-frame SAN with mid-stream palette
  swap, and a SAN using transparency; expected RGBA bytes pinned from the oracle once.
  Same for one minimal `.nut` and one synthetic v7-style room chunk.
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
