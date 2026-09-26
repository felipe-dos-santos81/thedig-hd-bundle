# thedig-textures

Extract every piece of game art from GOG's *The Dig* (1995) into PNGs plus a
machine-readable manifest, for AI regeneration. Decoding is pixel-exact: every
SAN frame, NUT glyph, LA1 room/object bitmap and AKOS costume cel is verified
byte-for-byte against the shipped ScummVM decoder.

## What it extracts

| Source | Kind | Content |
|---|---|---|
| `VIDEO/*.SAN` (55 files) | `san_frame` | Westwood SMUSH frames: scene backgrounds, cutscenes, animated props (12,638 frames) |
| `VIDEO/*.NUT`, `_other/*.NUT` (6 files) | `nut_image` | LucasArts bitmap fonts and icon sheets (1,403 glyphs) |
| `DIG.LA1` room/object images | `la1_bitmap` | SCUMM v7 room backdrops and `OBIM` sprite sheets (753 images) |
| `DIG.LA1` `AKOS` cels | `la1_bitmap` (`akos:` ids) | Costume/actor cels (28,490 cels) |

Text/HUD is a runtime overlay drawn by the engine and is deliberately **not**
baked into extracted frames. The game bundle is opened **read-only** and is never
modified.

## Output layout

All paths are under `--out` (default `./out/`, gitignored):

```
out/
  san/<NAME>/<frame:05d>.png        # e.g. san/SQ1/00000.png
  nut/<STEM>/img_<entry:03d>.png    # glyph/icon sheets per .nut file
  la1/<resource-name>.png           # room/object bitmaps and AKOS cels
  palettes/<hash>.json              # 256x[r,g,b] 8-bit color table
  palettes/<hash>.png               # 256x1 palette strip
  manifest.json
  _errors.json                      # written only if errors occurred
```

PNGs carry no timestamps, so output is reproducible run-to-run; the manifest
lists assets in sorted source-file/index order with zero-padded ids. The manifest
schema is specified in
[`docs/superpowers/specs/2026-09-24-thedig-textures-design.md`](docs/superpowers/specs/2026-09-24-thedig-textures-design.md)
§5.1: `tool`, `tool_version`, `extracted_at`, `game_root` (sha256 over sorted
path/size pairs), `counts`, and `assets[]` (`id`, `kind`, `source`, `frame`,
`name`, `width`, `height`, `has_alpha`, `palette`, `path`, `room` (LA1 rooms and
objects), `x`, `y` (LA1 objects)).

## Requirements

- Python >= 3.12, `pillow`
- `clang++` (only to build the verification oracle)
- The GOG bundle at `~/Documents/The Dig®.app`

## Usage

```sh
make install   # create .venv and install the package with dev deps
make check     # unit tests (hermetic; no game bundle needed)
make verify    # build the oracle + byte-exact differential over SAN/NUT/LA1/AKOS

thedig-textures extract                 # write PNGs + manifest to ./out
thedig-textures extract --only san      # limit to one kind: san,nut,la1,akos
thedig-textures extract --game PATH --out DIR --jobs N --force
thedig-textures verify                  # run the four differential gates
```

`extract` preflights the bundle (requires `VIDEO/`, `DIG.LA0`, `DIG.LA1`) and
free disk (15 GiB with SAN, else 1 GiB; `--force` bypasses). `--jobs` defaults to
`min(4, CPUs)`. Exit codes: `0` success with zero errors, `1` errors recorded
(see `_errors.json`), `2` usage/preflight failure.

## Verification

`make verify` is the acceptance gate: all 55 `.SAN` files, all 6 `.NUT` files,
every decodable `DIG.LA1` room/object bitmap and every AKOS costume cel decode
byte-identically to the vendored C++ oracle. The manual first-frame comparison
against the running game is documented under [`docs/proofs/`](docs/proofs/).

## Regeneration handoff

The next phase consumes `out/manifest.json` alone: each entry's `path` points at
a PNG, `palette` names a sidecar color table, and `id`/`kind`/`source`/`frame`
let a pipeline group, condition and trace every asset back to its origin. To
regenerate, run `thedig-textures extract` on the same bundle and diff the
manifest `game_root` hash — an unchanged hash means the same inputs.

## License

GPL-3.0-or-later. Vendored ScummVM sources under `vendor/san-oracle/` retain
their original headers.
