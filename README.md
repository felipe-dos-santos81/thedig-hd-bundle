# thedig-textures

Extract every piece of game art from GOG's *The Dig* (1995) into PNGs plus a
machine-readable manifest, for AI regeneration. Decoding is pixel-exact: SAN
frames are verified byte-for-byte against the shipped ScummVM decoder.

## What it extracts

| Source | Content |
|---|---|
| `VIDEO/*.SAN` | Westwood SMUSH frames (scene backgrounds, cutscenes, animated props) |
| `VIDEO/*.NUT`, `_other/*.NUT` | LucasArts bitmap fonts and icon sheets |
| `DIG.LA0` / `DIG.LA1` | SCUMM v7 room and sprite bitmaps |

Output is `out/` plus `out/manifest.json` (asset ids, sizes, palette hashes,
paths). The game bundle is opened **read-only** and never modified.

## Requirements

- Python >= 3.12
- `clang++` (only to build the verification oracle)
- The GOG bundle at `~/Documents/The Dig®.app`

## Usage

```sh
make check     # unit tests (no game bundle needed)
make verify    # build the oracle + byte-exact differential over all 55 SANs

thedig-textures extract                 # write PNGs + manifest to ./out
thedig-textures extract --only san      # limit to one asset kind
thedig-textures extract --game PATH --out DIR --jobs N
```

## Development

```sh
make install   # create .venv and install the package with dev deps
make help      # list targets
make clean     # remove the venv and caches
```

## License

GPL-3.0-or-later. Vendored ScummVM sources under `vendor/san-oracle/` retain
their original headers.
