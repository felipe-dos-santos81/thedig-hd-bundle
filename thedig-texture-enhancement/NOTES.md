# Live checks, spikes and runs

Measured facts behind the kit's constants. Newest last.

## Extraction (2026-09-26)

`thedig-textures extract --only la1` 0.2.0 on the Mac, rsynced to the GB10:
753 LA1 bitmaps, 0 errors; 111 rooms and 642 objects, every object with `room`,
`x`, `y`. `make check`: kit 150 tests OK with 0 skips (every real-corpus test
ran and passed, including the gate on all 105 non-skip rooms).

Placement (plan Task 2 Step 7):

- 639 objects inside their room, 5 identical to the room beneath them.
- 3 outside, reported `BADPLACE`: `obj199_01` in room 23 (x 1784, 32 wide:
  8 px past the 1808 edge); `obj618_01` (288x32) and `obj627_01` (256x128) in
  room 93, which is 40x200 and `skip`.
- The IMHD x/y is the draw position: of the 261 objects whose pixels visibly
  overlap their room, 255 agree best at offset (0, 0) in a ±16 px search; the
  other 6 are scattered one-offs. The other 366 objects are new art, with no
  clear agreement peak.

## Room spike (2026-09-26, GB10)

Rooms 2 (976x200, rendered, 4 windows), 4, 11, 43, 60 (320x200, 1 window) and
27 (512x780, rendered, 10 windows), seed 42, match strength 0.5, vLLM stopped.

Captions: the VLM captioned all six in one run. Five needed hand corrections
against the room image: room 2's open payload bay, the shuttle's heading and a
whole (not cropped) asteroid; room 11 is a sand canyon under an overhanging
wall, not a vaulted stone hall; room 43 is seen from above, not from a cave
mouth; room 60 missed a large rock and its opening's shape. Only room 27's was
right as written. `medium_style` set rooms 4 and 11 to `rendered` because their
MEDIUM hedged "pre-rendered 3D or … painting"; both are `painted`.

| Variant | Rooms | s a window | Promoted | Worst shift (px) | Lowest edge |
|---|---|---|---|---|---|
| `qwen-image-2.1-i2i` (denoise 1.0), palette-smooth | 4, 11, 43, 60 | 53 | all | 0.31 (60) | 0.999 |
| same | 2 | 55 | no | 104 (window 4); room −6.0 | 0.32 (window 4) |
| same | 27 | 65 | no | 109; room −81, −82 | 0.36 (window 5) |
| `qwen-image-2.1-i2i-faithful` (0.9), palette-smooth | 27 | 65 | yes | 0.13 | 0.998 |
| same | 2, seed 42 | 53 | no | 0.67 (window 2) | 1.0 |
| same, next attempt | 2, seed 43 | 54 | yes | 0.15 | 0.999 |
| denoise 1.0, `--dedither none` | 11, 43, 60 | 53 | all | 0.20 (60) | 0.987 (11) |

- **Caption leak** is the failure of multi-window rooms at denoise 1.0: every
  window gets the whole caption, and a mostly empty window paints the caption's
  objects into itself. Room 2's three space windows each gained an asteroid
  (plus a sun or a shuttle nose); room 27's ten windows each repainted the whole
  shaft, stacked. The gate caught both; the big "shifts" are real repaint
  failures, not phase correlation misreading the dark art.
- At denoise 0.9 both rooms kept their layout. Room 27 keeps three small
  artefacts: a blue diamond on the platform top, a faint orange line mid-right,
  and a glow above the bottom starburst. The 0.9 look is a clean upscale closer
  to the source than the 1.0 repaints of the one-window rooms.
- Room 2's first 0.9 attempt was rejected on window 2 (−0.7 px), a window of
  black space and the sun with edge agreement 1.0 everywhere: shift on a nearly
  empty window is noisy. Seed 43 passed. Watch for this in the full run.
- One-window rooms at 1.0 are faithful painted repaints: the dithering and sand
  ripples become smooth painted gradients, and the layout holds to 0.3 px.
- `--dedither none` keeps finer texture (sand ripples, crevice sparkles, stone
  lines) but carries a faint diagonal grain from the source's dithering into
  room 11's sand; palette-smooth is softer and cleaner.

Decisions (the user's, from the review pages):

- Multi-window rooms (several windows or a wraparound seam) render through
  `qwen-image-2.1-i2i-faithful`: the registry's `multi_window` for the default
  workflow (commit 95a149d); 28 of the 105 rendered rooms. One-window rooms and
  objects keep denoise 1.0. The rejected alternatives: layout-free window
  captions (keeps the painted look, untested) and per-window captions (more code
  and VLM time).
- `DEDITHER_METHOD` stays `palette-smooth`: `none` keeps the dithering grain
  the repaint is meant to remove. `--dedither none` stays available per batch.
- `WINDOW_HEIGHT` stays 240: room 27's failure at 1.0 was caption leak, not
  drift, and its 0.9 render holds to 0.13 px over ten 240-row windows.
- `RENDERED_RULES` stay: rooms 2 and 27 keep their CGI look through the 0.9
  workflow.
- Read every caption against its room image before a batch, and set `style`
  by hand where MEDIUM hedges.
