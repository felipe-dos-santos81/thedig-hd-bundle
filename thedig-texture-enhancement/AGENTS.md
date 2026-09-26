# AGENTS.md

Guidance for agents working on *The Dig* background and object regeneration
kit. README.md is the user view; this is the agent view. The kit is a fork of
the *Fate of Atlantis* kit
(`~/code/atlantis-hd-bundle/atlantis-texture-enhancement`, its `AGENTS.md` the
model for this one); everything here does not repeat from there is unchanged.
The design is the bundle root's
`docs/superpowers/specs/2026-09-25-thedig-regeneration-design.md` and the
build plan `docs/superpowers/plans/2026-09-26-thedig-regeneration.md`.

## 1. Architecture

| Stage | Command | Service | Reads | Writes |
|---|---|---|---|---|
| Caption | `dig_recreate.py caption` | vLLM `:8000` | the source rooms | captions and `style` in `rooms.yaml` |
| Batch | `dig_recreate.py batch` | ComfyUI `:8188` | `rooms.yaml`, `reviews.yaml`, the workflow template | `data/rooms-ai/`; geometry rejections in `reviews.yaml` |
| Objects | `dig_recreate.py objects` | ComfyUI `:8188` | promoted rooms, `rooms.yaml`, `reviews.yaml`, the workflow template | `data/objects-ai/`; geometry rejections in `reviews.yaml` |
| Review | `dig_recreate.py review` | vLLM `:8000` | source, promoted rooms and objects | `reviews.yaml` |

`verify` audits both output trees.

Run order: `batch` → `review` (judges rooms; no object exists yet) → repeat
`batch`/`review` until the rooms settle (no more rejections) → `objects` →
`review` again (rooms are already reviewed, so this pass judges the render
objects) → repeat `objects`/`review` → `verify`. `objects` paints over each
room's *current* promoted output; running it before its room's review has
settled risks a later rejection re-rendering the room and staling every
object painted over it (see below).

Rules that must survive any change:

- **The source is thedig-textures-exporter's output, at tool version 0.2.0 or
  later**, read in place from `DIG_SRC`. `source_tree` is its only reader,
  and `manifest.json` decides which rooms and objects exist; a pre-0.2.0
  manifest, or an object entry missing `room`, `x` or `y`, is a load failure.
  Never write under `DIG_SRC`; never parse paths for meaning.
- **Re-import-safe means geometry.** Every room and object output is exactly
  4x native, **RGB or RGBA per the manifest's `has_alpha`**, with an alpha
  channel byte-equal to the source alpha scaled 4x nearest-neighbour. No
  render is promoted without passing `geometry_check`. Do not loosen the gate
  to get an item through: fix its caption, its `style`, or `skip_objects`.
- **An object is painted only over a `done` room.** `objects` skips (reports
  `waiting`) any object whose room is not `done` and not `skip`. Every
  `render` object's attempt record carries `room_sha256`, the sha256 of the
  promoted room it was painted over: this is how a later room re-render is
  detected as `stale` (see below), and how `verify` tells a hand-replaced
  file (`UNRECORDED`) from one painted over an older room (`STALE`).
- **`stale` / `waiting` / `BADPLACE` are object-only states.** `waiting`: the
  object's room is not yet `done` (not an error). `stale`: the object is
  `done`, but its promoted record's `room_sha256` differs from the room's
  current promoted file; it is re-rendered like `new`. A `done` object whose
  current output file no attempt record promoted (hand-replaced) keeps its
  status unchanged — `verify` reports that file `UNRECORDED` instead of
  `stale`. `BADPLACE`: the object's rectangle is not inside its room (a
  manifest placement error, `source_tree.load`); it loads, is reported by
  `objects` and `verify`, and is never rendered, but never stops the others.
- **Services are external.** The driver never starts or stops vLLM or
  ComfyUI. It checks `GET /v1/models` and `GET /queue`. Its only
  state-changing ComfyUI calls are `POST /free` (at the end of `batch` and
  `objects`, and the start of `review`) and `POST /interrupt` (sent only by
  `comfy_client`) for a prompt that timed out or was stopped with Ctrl-C.
  After a failed or Ctrl-C'd room or object it deletes that item's own
  leftover renders (`comfy_client.sweep_outputs`, anchored to SaveImage's
  `<key>_a<attempt>-<label>_NNNNN_.png` naming). The attempt in the
  ComfyUI-facing name keeps ComfyUI's cache from answering a rerun with an
  old render; the audit tiles keep the plain `window-K`/`object` and `seam`
  names.
- **Unified memory.** vLLM holds about 73 GB and a render about 45 GB of the
  GB10's 121 GB. `batch` and `objects` each refuse below `MEMORY_FLOOR_GB`
  (45) unless `--no-memory-check`.
- **Atomic writes.** YAML and JSON go through `<name>.tmp` and a rename,
  images through `<name>.pending` and a rename.
- **Resumable by construction.** Caption skips filled entries. Batch and
  objects derive each item's status from its audit folder
  (`dig_recreate.room_status`): `new`, `stuck`, `failed` (the latest attempt
  has no record), `rejected` (by geometry or review), `missing`, or `done`.
  An item is rendered when it is not `done` and not `stuck`, unless
  `--force`. A room or object is `stuck` when its latest judged attempt (one
  with a record) was rejected and it has `MAX_ATTEMPTS` judged attempts;
  failed attempts never count, so an item that keeps failing on
  infrastructure is retried on every run (exit code 1). A stuck item whose
  workflow names a `fallback` (`fallback_for`) is rendered once more through
  it on the next run, and reported STUCK only once that attempt is rejected
  too. A failed attempt keeps its number and its tiles. The next attempt's
  corrections (`corrections_for`) are the current review's issues while no
  later attempt was promoted, whatever the attempts since became; a geometry
  rejection gives the one `prompts.GEOMETRY_CORRECTION` sentence instead of
  the gate's strings. A review of an attempt later than the audit folder's
  latest is stale (`current_review`) and ignored. An object additionally
  reads `stale` (`object_status`, built on `room_status`): see above.
- **Renders never depend on other rooms**, except that an object depends on
  its own room's promoted output. A room is consistent within itself through
  the window continuation, and with other rooms through each room's colour
  match toward its own source; an object is consistent with its room by
  being painted directly over it.
- **Only `comfy_client` knows node ids.**

## 2. Modules

| File | Owns | Must not |
|---|---|---|
| `dig_recreate.py` | CLI and stages, selection, preflights, audit folders, promotion | know node ids or YAML syntax |
| `source_tree.py` | reading and validating `manifest.json`: rooms, objects, placement, colour keys | talk to services or write files |
| `room_geometry.py` | guide, de-dither, transparent fill, margins, wraparound, 2D windows, composites and L masks, 2D stitch and boundaries, seam, fix-ups, alpha attach | talk to services or know files |
| `object_geometry.py` | classification, context window, object inputs and mask, compose, crop, check | talk to services or know files |
| `geometry_check.py` | shift, edge agreement, seam ratio | know files, rooms or the audit tree |
| `rooms_file.py` | `rooms.yaml` (kind, caption, style, skip_objects) and `reviews.yaml`: shape, validation, folded style, atomic save | do I/O beyond its own files |
| `colour_match.py` | Lab statistics and the `source-relative` transfer, over an optional pixel mask | know rooms or files |
| `comfy_client.py` | ComfyUI HTTP, the workflow registry, node ids, staging, output lookup, interrupt, sweep | decide what to render |
| `prompts.py` | caption, render and review prompts, VLM payloads, `parse_review`, `parse_object_reviews`, `vlm_is_serving` | know files or make targets |

`object_geometry.py` must not talk to services or know files, like
`room_geometry.py`.

## 3. The render path

### Rooms

Per room (`dig_recreate.render_room`):

1. `room_geometry.build_guide`: the RGBA source with every transparent pixel
   filled from its nearest opaque neighbour (`fill_transparent`), de-dithered
   at native size (`DEDITHER_METHOD`), **padded** at the bottom to the next
   multiple of 8 rows by repeating its last row (six native heights are not
   multiples of 8: 230, 399, 425, 450, 500, 780), upscaled 4x with Lanczos.
2. `room_geometry.plan_room`: margins on all four sides, wraparound
   (horizontal-only), the render span, and the **2D window grid**: columns
   and rows planned separately by the same rule as one axis (first window at
   the start, last flush with the end, starts on multiples of 8, every
   neighbour overlapping by at least `WINDOW_OVERLAP`), windows their
   product, rendered row by row, left to right.
3. Each window, row by row, left to right: `window_inputs` (guide crop,
   composite, **L-shaped mask**: `min(mask_x, mask_y)`, a column ramp over
   the left overlap and a row ramp over the upper overlap, so the kept region
   is an L; a first-row or first-column window is painted whole on that
   axis), `comfy_client.render_window`, `paste_window` (from the stitch
   origin: the middle of each overlap, or the window's own edge with none).
4. A wraparound: `seam_inputs`, `render_window`, `apply_seam`. The stitched
   canvas is saved as `attempt-N.png` here, before it is cropped: for a
   padded room (see step 1), `attempt-N.png` is the **padded** canvas, 4x
   the padded height, not the room's 4x size; the promoted output (after
   step 5) is exactly 4x.
5. `finish_room`: crop the padded canvas back to exactly the room's 4x size,
   `colour_match.match` toward the guide (`--match-strength`; over opaque
   pixels only for an RGBA room), then `apply_fixups` (the wraparound's
   repeat copied byte-exact, the margins set to the source's flat colours),
   then for an RGBA room `room_geometry.with_alpha` attaches the source alpha
   scaled 4x nearest-neighbour.
6. `geometry_check.check`: shift per room and per 2D window; edge agreement
   per room and per window (the room's edge maps masked to the window's
   rectangle, and to the opaque pixels for an RGBA room), with hysteresis: a
   source edge is strong above `EDGE_THRESHOLD` (80) and kept by a render
   edge above `RENDER_EDGE_THRESHOLD` (60) within 1 px; a window with fewer
   than `MIN_WINDOW_EDGES` (100) strong source edge pixels reads 1.0; seam
   ratios relative to the guide's. Promote on a pass; a rejection goes to
   `reviews.yaml` as `source: geometry`.

A render that raises (a ComfyUI error, a timeout, a wrong-size window,
Ctrl-C) writes `attempt-N.error.txt` (workflow, seed, window, seconds, error)
and no `attempt-N.json`, so the attempt reads as failed. Batch then sweeps
the room's stray outputs; on Ctrl-C `comfy_client` has already sent
`/interrupt`, and batch re-raises after the sweep and `/free`. Failed
attempts never count toward STUCK, and the next attempt still carries the
current review's corrections (see §1).

### Objects (`dig_recreate.render_object`, `object_geometry`)

Per `render`-class object, over its room's already-promoted 4x render:

1. **Context window** (native): the object rectangle grown by `CONTEXT_MARGIN`
   (32 px) on each side, clamped to the room (padded to `ALIGN` rows), then
   widened to at least `MIN_CONTEXT` (128x128) where the room allows, its
   edges on multiples of `ALIGN` (8) (`object_geometry.context_box`).
2. **Guide:** the object's native image drawn onto the (transparent-filled)
   native room at its placement (`draw_object`), de-dithered and upscaled 4x
   as the room guide.
3. **Composite:** the promoted room cropped to the context window (`base`),
   with the object's guide pasted over it only at the pixels that changed
   (the **diff**: the object's opaque pixels that differ in colour from the
   room beneath).
4. **Mask:** the diff grown by `MASK_GROW` (2 native px), scaled 4x nearest,
   then box-blur softened (`MASK_SOFTEN`); the diff pixels themselves stay
   255 (paint) after softening. Everything else is 0 (keep the promoted
   room). The workflow's reference input is the composite, not the guide.
5. **Prompt:** the room's render prompt (kind, style, corrections) plus
   `OBJECT_NOTE`: repaint only the changed area, in the same style, light and
   brushwork as its surroundings, keeping its outline where the reference
   shows it. The caption is cut to its room-wide sections
   (`prompts.room_wide_caption`: SCENE, MEDIUM, LIGHTING, PALETTE, TEXT):
   with LAYOUT and OBJECTS, the object spike painted the caption's asteroid
   and crystal cone into objects of rooms 2 and 27.
6. **Seed:** `SEED + attempt - 1`, as rooms.
7. **Finish** (`object_geometry.compose`): colour-match the render toward the
   object's guide, with statistics over the diff pixels only, then lay it
   over the promoted room through the mask — every pixel the mask does not
   paint is byte-equal to the promoted room by construction. Crop the object
   rectangle out of the finished context window (`object_crop`); attach the
   source alpha 4x nearest when the object `has_alpha`.
8. **Gate** (`object_geometry.check_object`; §11 of the design spec): the
   context window's own rows, checked with the **object rectangle as its one
   window** (`MIN_WINDOW_EDGES` floor) — the unchanged room around the object
   would otherwise hide the object's own drift in a whole-window measure —
   plus the outside-mask byte-equality assert. Promote on a pass.

An `identical`-class object promotes the promoted room's 4x crop of the
object rectangle directly (`object_geometry.identical_output`), with no
render and no review; its `GeometryResult` is a trivial pass.

Node ids in `recreation_qwen2511_canny.json`: 1 LoadImage (the guide window,
also the Canny input), 2 LoadImage (the composite), 3 LoadImageMask (red),
4 CLIPLoader, 5 UNETLoader (2511 fp8), 6 VAELoader, 7 DifferentialDiffusion,
9/10 positive/negative TextEncodeQwenImageEditPlus (`image1` is the
reference), 11 VAEEncode (the composite), 12 SetLatentNoiseMask, 13 KSampler
(40 steps, cfg 3.0, denoise 1.0), 14 VAEDecode, 15 SaveImage,
22 ModelSamplingAuraFlow, 23 CFGNorm, 30 Canny (0.4/0.8), 31 ControlNetLoader,
32 SetUnionControlNetType (canny), 33 ControlNetApplyAdvanced (strength 0.7,
0–65% of the steps).

Node ids in `recreation_qwen21_i2i.json`: 1 LoadImage (the guide window),
2 LoadImage (the composite), 3 LoadImageMask (red), 4 CLIPLoader (qwen3vl_8b),
5 UNETLoader (2.1 bf16), 6 VAELoader, 7 DifferentialDiffusion,
9 TextEncodeQwenImage21 (prompt, negative_prompt, resolution 0,
`images.image_1` is the reference), 11 VAEEncode (the composite),
12 SetLatentNoiseMask, 13 KSampler (40 steps, cfg 1.0, denoise 1.0),
14 VAEDecode, 15 SaveImage. Its fallback, `qwen-image-2.1-i2i-faithful`, is
the same graph with the registry's `settings` writing denoise 0.9 into node 13.
It is also the registry's `multi_window` workflow for `qwen-image-2.1-i2i`:
`cmd_batch` (`room_workflow_for`) sends every room with more than one window,
or a wraparound seam, through it, because at denoise 1.0 each window paints the
whole caption's objects into itself (rooms 2 and 27 in the 2026-09-26 spike).
Such a room has no fallback. Objects keep the default workflow (one render each).

The 2.1 encoder's reference slot is an autogrow input and must be addressed
as `images.image_1`: the AITD kit's live render showed the flat `image_1`
arrives as an unexpected keyword and kills the render. `resolution: 0` relies
on every window being a multiple of 32 in both dimensions, which `plan_room`
(and, for objects, `context_box`) guarantees.

**A graph is only validated by rendering it.** The template tests check each
graph against its registry record, not against ComfyUI's real node schemas.
Render one room through any new or edited graph before trusting it.

## 4. Prompts

- `CAPTION_QUESTION` gains a `MEDIUM` section (painted, pre-rendered 3D, or
  mixed, with one sentence of visible evidence) alongside SCENE, VIEW,
  LAYOUT, OBJECTS, LIGHTING, PALETTE, TEXT, INVARIANTS; under 600 words; "no
  people" unless painted in. When a room's `style` is blank, `caption` sets
  it from `medium_style(caption)`: `"rendered"` when MEDIUM mentions
  pre-rendered, 3D, CGI or computer-generated, else `"painted"`.
- The positive prompt (`render_prompt`) opens with `PAINTED_RULES` or
  `RENDERED_RULES` (chosen by `style`, formatted with the workflow's
  reference phrase): `PAINTED_RULES` asks for confident painterly brushwork
  in the manner of The Dig's painted backgrounds; `RENDERED_RULES` asks for a
  crisp pre-rendered 3D look — clean modelled surfaces, specular highlights,
  ray-traced light — at a much higher resolution than the reference. Both
  keep the exact composition and the reference's colours, light and shadow.
  Then the insert rules for an `insert` room (the caption's TEXT as LETTERING
  when present), the window note for a multi-window room, `OBJECT_NOTE` for
  an object render, REFERENCE OBSERVATIONS (the caption; for an object only
  its room-wide sections), then corrections
  (the review's issues, or `GEOMETRY_CORRECTION` after a geometry rejection).
  The negative prompt (`negative_prompt(style)`) is `PAINTED_NEGATIVE` or
  `RENDERED_NEGATIVE` (the rendered one drops "3D render" and "CGI", which
  the rendered look wants): goes to 2511's node 10, and 2.1's node 9
  `negative_prompt` (ignored at cfg 1).
- `REVIEW_QUESTION` sends (guide window, render window) pairs and the whole
  render, with a `style`-specific rejection rule from `STYLE_RULES`, and
  returns `{"accepted", "issues"}`. `parse_review` tolerates fences and
  chatter, and refuses contradictory verdicts.
- `OBJECT_REVIEW_QUESTION` sends, per room, up to `OBJECT_REVIEW_BATCH` (8)
  objects as one side-by-side (guide, render) image each, labelled with their
  keys, plus the room overview, and returns
  `{"objects": {"<key>": {"accepted", "issues"}}}`. `parse_object_reviews`
  keeps only the keys it asked about with a valid, non-contradictory verdict;
  a key the VLM's answer omits is left out and stays unreviewed.

## 5. Testing

```bash
make check   # py_compile every module
make test    # unittest discover: every test_*.py
```

Tests never touch the network or the GPU. `testkit.py` is the one shared
test-support module. Rules, as in Atlantis:

- one test module per production module;
- data-only variations are one `subTest` table;
- keep the suite small: a test covers one behaviour, and the facets of one
  run are asserted in one test; add a separate test only for a different
  behaviour or a named regression;
- a rule is tested once, at the layer that owns it;
- a regression test names what it guards.

The miniature source (`testkit.make_source`) is built from two tables:

- `DEFAULT_ROOMS`: `room(1, 320, 144)` (one window), `room(2, 568, 144)` (two
  windows), `room(3, 1152, 144, wrap=(840, 224), right_margin=88)` (a
  wraparound), `room(4, 16, 200, flat=0)` (a flat placeholder, `skip`).
- `DEFAULT_OBJECTS`: `obj010_01` (identical to the room beneath, state 01),
  `obj010_02` (differs — `render`, the same placement, state 02), `obj011_01`
  (a sprite with alpha), `obj012_01` (in the `skip` room — copied),
  `obj013_01` (sticks out of room 1 — `BADPLACE`), `obj014_01` (in the
  two-window room 2).

`write_rooms`, `run_cli`, `fake_render`, `comfy_stub` and `vlm_stub` work as
in Atlantis; `vlm_stub` also patches `review_objects` and `comfy_stub`'s
`fake_render` "renders" a window or an object by saving its composite.
Never re-implement these in a test module.

Three test classes run on the real corpus, whenever
`../thedig-textures-exporter/out` (or `DIG_SRC`) exists;
`testkit.REAL_SRC`, `testkit.needs_real_corpus` and `testkit.real_rooms()` are
their one definition of it:

- `test_source_tree.RealCorpusTests` pins the manifest: 111 rooms, 642
  objects, room 27 at 512x780, and the RGBA rooms {32, 34, 85, 88, 107}.
- `test_dig_recreate.RealCorpusTests` pins the room gate: each scene or
  insert room's own guide, through `finish_room` at
  `DEFAULT_MATCH_STRENGTH`, passes `geometry_check.check` (a perfect render
  of any real room is promotable).
- `test_object_geometry.RealCorpusTests` pins object classification: every
  placed real object classifies as `identical` or `render`, with at least
  one of each.

## 6. Live checks and the spike

Live checks, spikes and runs are in `NOTES.md`.

The room spike and the object spike (2026-09-26, `NOTES.md`) settled the
Dig-specific choices:

- Multi-window rooms render through `qwen-image-2.1-i2i-faithful` (the
  registry's `multi_window`): at denoise 1.0 every window painted the whole
  caption's objects into itself. One-window rooms and objects stay at 1.0.
- Object prompts carry only the room-wide caption sections
  (`room_wide_caption`), for the same caption leak.
- `DEDITHER_METHOD` stays `palette-smooth`; `WINDOW_HEIGHT` stays 240;
  `RENDERED_RULES` stay.
- Multi-state objects render state by state with no chaining: the slight
  frame-to-frame shimmer was judged acceptable.
- Captions need a read against the room image before every batch, and a
  hand-set `style` where MEDIUM hedges ("3D or painting").

The other defaults (`WINDOW_OVERLAP`, `RENDER_EDGE_THRESHOLD`,
`MIN_EDGE_AGREEMENT`, `DEFAULT_MATCH_STRENGTH`) are still the Atlantis kit's
measured choices (its `AGENTS.md` §6); nothing in the Dig spikes contradicted
them. `NOTES.md` is the record of what was measured here.
