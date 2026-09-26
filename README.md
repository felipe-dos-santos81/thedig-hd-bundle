# thedig-hd-bundle

HD room backgrounds and room objects for *The Dig* (LucasArts, 1995), for
personal use. You need your own GOG copy of the game.

| Folder | What it does | Output |
|---|---|---|
| [`thedig-textures-exporter/`](thedig-textures-exporter/) | Extracts the game's art, pixel-exact against ScummVM | `out/`: native-size PNGs and `manifest.json` |
| [`thedig-texture-enhancement/`](thedig-texture-enhancement/) | Repaints every room and room object at exactly 4x through ComfyUI, checked by a geometry gate and a VLM review | `data/rooms-ai/`, `data/objects-ai/` |

## Quick start

```sh
make install     # both virtualenvs
make check       # both test suites (no game, no GPU)
make extract     # rooms and objects into thedig-textures-exporter/out
                 # (game="/path/to/The Dig®.app" if not in ~/Documents)
make -C thedig-texture-enhancement help   # the render pipeline
```

The kit reads `../thedig-textures-exporter/out` by default (`DIG_SRC`
overrides it). Each folder has its own README and Makefile.

## Game data

Nothing extracted or generated is committed: `out/`, `data/` and
`reviews.yaml` are gitignored. The art is LucasArts/Disney copyright; do not
redistribute it.

## Design

- Spec: [`docs/superpowers/specs/2026-09-25-thedig-regeneration-design.md`](docs/superpowers/specs/2026-09-25-thedig-regeneration-design.md)
- Plan: [`docs/superpowers/plans/2026-09-26-thedig-regeneration.md`](docs/superpowers/plans/2026-09-26-thedig-regeneration.md)
