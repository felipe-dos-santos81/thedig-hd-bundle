# First-frame proofs — extracted SAN frames vs the running game

This directory holds the manual visual proof that the SAN decoder reproduces the
game's background art. The automated proof is stronger and lives elsewhere:
`tools/diff_oracle.py` compares every decoded frame of all 55 `.SAN` files
byte-for-byte against the vendored ScummVM codec (`make verify`). This document
covers the one thing the differential cannot: that the *right* art is on screen
in the *right* place when the game actually runs it.

## Status of the in-game screenshot

**No in-game screenshot was supplied with this task, so the side-by-side
comparison is not yet recorded here.** The three decoded first frames are
committed under `first-frames/` and are ready to compare against a capture:

| Decoded frame | Source | What it should show |
|---|---|---|
| `first-frames/SQ1/00000.png` | `VIDEO/SQ1.SAN` frame 0 | Opening scene background (the alien desert/beach establishing shot) |
| `first-frames/SQ10/00000.png` | `VIDEO/SQ10.SAN` frame 0 | Scene-10 background |
| `first-frames/PIGOUT/00000.png` | `VIDEO/PIGOUT.SAN` frame 0 | The pig/creature cut-in background |

To complete the proof: launch the bundle, reach each screen, pause, and capture
with macOS `cmd-shift-4`; drop the captures next to the frames and add the
per-element comparison below.

## Methodology

1. Extract with `thedig-textures extract` (or `--only san`). Frame `00000` of
   each SAN is the first back-buffer state the engine presents for that screen.
2. Capture the same screen from the running game at native 320×200 (the engine
   scales the 320×200 back buffer to the window; compare at 1× or downscale the
   capture to 320×200).
3. Compare region by region (below). A correct decode shows pixel-identical
   background art; only runtime-drawn overlay differs.

## What should match, and what deliberately does not

The engine composes each screen from two layers. The extractor emits **only the
first layer**; the second is generated live and is intentionally absent.

**Background art — must match the decoded frame pixel-for-pixel**

- The full 320×200 scene backdrop: terrain, sky, room interiors, painted props.
- Animated props that are baked into the SMUSH stream (e.g. moving scenery),
  which is why every frame of a SAN is extracted, not just frame 0.

**Runtime overlay — deliberately excluded (drawn by the engine, not in the SAN)**

- HUD and verb/dialogue text — rendered from the `.NUT` fonts (extracted
  separately under `out/nut/`) and positioned by SCUMM scripts.
- The mouse cursor and the verb-coin / sentence line.
- The inventory bar and inventory item icons when opened.
- Any scene-specific SCUMM `OBIM`/`AKOS` sprites and actor/costume cels composited
  on top of the backdrop (extracted separately under `out/la1/`).
- Fades, transitions and palette cycling performed by the engine at runtime.

So when comparing: the backdrop must be identical; a difference confined to
text, cursor, sentence line, inventory bar, or a character sprite is expected and
is not a decode failure. A difference in the backdrop pixels is.

## Reproducing the extracted frames

```sh
thedig-textures extract --only san          # writes out/san/**/<frame:05d>.png
```

The frames committed here are byte-identical to a fresh extraction (the writer
strips timestamps and the decoder is deterministic); `make verify` is the
machine-checkable guarantee.
