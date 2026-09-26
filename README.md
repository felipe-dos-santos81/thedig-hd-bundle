# thedig-hd-bundle

HD room backgrounds and room objects for *The Dig* (LucasArts, 1995), for
personal use. There are two projects, run in this order:

| Folder | What it does | Output |
|---|---|---|
| [`thedig-textures-exporter/`](thedig-textures-exporter/) | Extracts every texture from your own GOG copy of the game, pixel-exact against ScummVM's decoders | `out/`: PNGs at native size, palettes, and `manifest.json` with each room object's room and position |
| [`thedig-texture-enhancement/`](thedig-texture-enhancement/) | Repaints each room and each room object at exactly 4x through ComfyUI, then checks it with a geometry gate and a VLM review | `data/rooms-ai/` and `data/objects-ai/`: 4x PNGs, pixel-aligned with the source |

The enhancement kit reads `../thedig-textures-exporter/out` by default; set
`DIG_SRC` to point it elsewhere. Each folder has its own README, Makefile and
virtualenv.

Neither project commits game data or generated art: `out/`, `data/` and
`reviews.yaml` are gitignored. You need your own copy of the game.

Design: [`docs/superpowers/specs/2026-09-25-thedig-regeneration-design.md`](docs/superpowers/specs/2026-09-25-thedig-regeneration-design.md).
Plan: [`docs/superpowers/plans/2026-09-26-thedig-regeneration.md`](docs/superpowers/plans/2026-09-26-thedig-regeneration.md).
