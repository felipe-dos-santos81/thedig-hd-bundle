# The Dig Room and Object Regeneration — Design

Date: 2026-09-25
Status: approved for planning

## 1. Problem

Regenerate the room backgrounds and room object images of *The Dig*
(LucasArts, 1995, SCUMM v7), already extracted by this repository
(`thedig-textures`) into `out/la1/` with `out/manifest.json`, as
high-definition art at exactly 4x native size, with local models driven
through ComfyUI. The kit is a fork of the *Fate of Atlantis* kit
(`~/code/atlantis-hd-bundle/atlantis-texture-enhancement`, design
`docs/superpowers/specs/2026-09-24-atlantis-regeneration-design.md` there):
stages joined by hand-editable YAML, resumable runs, an audit folder per
attempt, a deterministic geometry gate and a vision-model review loop.
Everything this document does not change is as that design and that kit's
AGENTS.md describe; this document states the differences.

## 2. Decisions

| Question | Decision |
|---|---|
| Asset scope | **LA1 rooms (111) and OBIM object images (642 images of 364 objects).** SAN frames, AKOS cels and NUT glyphs are later sub-projects |
| What consumes the output | **In-game use** through a future loader (out of scope): every output is re-import-safe — exactly 4x, pixel-aligned with its native asset, transparency preserved exactly — and every object image blends with its regenerated room |
| Architecture | **Approach A: fork** the Atlantis kit into a Dig kit; the Atlantis kit is not touched |
| Repository | **Monorepo** `~/code/thedig-hd-bundle`, mirroring `atlantis-hd-bundle`: `thedig-textures-exporter/` (this repository, subtree-merged with history) and `thedig-texture-enhancement/` (new) |
| Object approach | **In-context masked repaint** over the promoted HD room, reusing the room workflows' latent noise mask; no new ComfyUI nodes or models |
| Placement data | The **exporter** records each LA1 bitmap's room and each object's x/y in the manifest; the kit never reads game files |

Approaches rejected:

- **B, a game-agnostic engine shared with Atlantis.** Removes duplication but
  refactors a working kit and delays the Dig; worth it only for a third game.
- **C, a standalone ComfyUI graph.** Loses captions, the geometry gate, the
  review loop and object placement, which in-game use depends on.
- **Objects rendered standalone.** Lighting and brushwork would not match the
  room they are drawn over.

## 3. Goals and non-goals

Goals:

- Every `scene` and `insert` room rendered, checked and promoted to
  `room_NNN.png` at exactly 4x native; every `skip` room written as a
  nearest-neighbour 4x.
- Every object image of a promoted room promoted to `objNNN_SS.png` at
  exactly 4x its native size, consistent with that room's promoted render.
- Geometry measured objectively on every room and object before promotion.
- Resumable, auditable runs with the Atlantis attempt, STUCK and fallback rules.

Non-goals:

- SAN frames, AKOS costume cels, NUT glyphs; room 88 (an 800x500 sprite
  sheet), which is `skip`.
- Colour cycling (`CYCL`): outputs are stills, as in Atlantis.
- The in-game loader or any ScummVM change.
- A review gallery (the Atlantis kit's `data/gallery/` is not ported in v1).

## 4. Repository and data flow

```
~/code/thedig-hd-bundle/                  public remote, like atlantis-hd-bundle
  README.md                               the two projects and their order
  thedig-textures-exporter/               this repository, via git subtree (history kept)
  thedig-texture-enhancement/             the new kit
```

Neither project commits game data or generated art: the exporter's `out/`,
the kit's `data/` and `reviews.yaml` are gitignored.

```
DIG_SRC (exporter out/) ─[caption]─▶ rooms.yaml ─(you edit)─┐
                                                             ▼
data/rooms-ai/room_NNN.png     ◀─[batch]──── rooms.yaml + reviews.yaml
data/objects-ai/objNNN_SS.png  ◀─[objects]── promoted rooms + placement
        └──────[review]──▶ reviews.yaml ──▶ batch / objects again for rejects
```

`caption` and `review` need vLLM; `batch` and `objects` need ComfyUI; they
never run together (GB10 unified memory, as in Atlantis).

## 5. Exporter change (thedig-textures-exporter)

Additive manifest fields, `tool_version` 0.2.0, spec
`2026-09-24-thedig-textures-design.md` §5.1 updated:

- Every `la1_bitmap` whose id starts `la1:` gains `"room": <int>` — the LOFF
  room number whose `ROOM` it was decoded from.
- Every OBIM entry (`la1:objNNN_SS`) also gains `"x": <int>, "y": <int>`: the
  signed 16-bit `x_pos` and `y_pos` of its `IMHD` at payload offsets 8 and 10
  (SCUMM v7 `ImageHeader`), in native room pixels. `la1.py` already reads
  `obj_id`, width and height from the same header (offsets 4, 12, 14).
- `akos:`, `san:` and `nut:` entries are unchanged.

Pixels do not change, so the four byte-exact differentials stay valid. A
synthetic fixture test asserts `room`, `x` and `y`. The game bundle is on the
Mac (`~/Documents/The Dig®.app`), so `thedig-textures extract --only la1` is
re-run there once, or on this host after copying the bundle.

## 6. Source reading (`source_tree.py`)

- `DIG_SRC` defaults to `../thedig-textures-exporter/out`.
- `load` reads `manifest.json` and keeps `la1:roomNNN` entries as rooms and
  `la1:objNNN_SS` entries as objects. It fails preflight if
  `tool_version < 0.2.0` or any object lacks `room`, `x` or `y`, with
  "re-extract with thedig-textures ≥ 0.2.0".
- Room keys are `room_NNN` (3 digits, 1–111); object keys are the manifest
  name `objNNN_SS` (unique across the manifest).
- Source PNGs are RGB or RGBA (not P-mode, unlike Atlantis). Where the Atlantis
  kit compares palette indices (margins, wraparound, flat-colour detection),
  the Dig kit compares a `(h, w)` uint32 **colour key** array, `R<<16 | G<<8 | B`.
  Transparent pixels get the key `0xFFFFFFFF`, which no RGB colour has.
- An object whose room is not in the manifest, or whose rectangle
  `(x, y, x + w, y + h)` is not inside its room, is an error listed by
  `verify` and never rendered.

## 7. Data files

### rooms.yaml (tracked, hand-owned)

```yaml
room_034:
  kind: scene          # scene | insert | skip
  style: painted       # painted | rendered; blank until caption fills it
  caption: >-
    ...
  skip_objects: []     # optional: object keys written as nearest-neighbour 4x
```

Seeded kinds (from the 2026-09-25 survey; editable):

| Kind | Rooms |
|---|---|
| `skip` | 1, 86, 93 (one flat colour); 103, 104 (two-colour line charts); 88 (sprite sheet) |
| `insert` | 28, 35, 51, 59, 69, 76, 79, 106, 107 |
| `scene` | all others |

### reviews.yaml (gitignored, machine-written)

As in Atlantis, keyed by room key or object key. Geometry rejections are
`source: geometry`; VLM verdicts are `source: vlm`.

## 8. Output contract

- `data/rooms-ai/room_NNN.png`: exactly `(4w, 4h)` of the native room. RGB when
  the manifest's `has_alpha` is false; RGBA when true, with an alpha channel
  **byte-equal** to the source alpha scaled 4x nearest-neighbour.
- `data/objects-ai/objNNN_SS.png`: the same rules against the object's native
  image.
- Audit folders `data/rooms-ai/.quality/room_NNN/` and
  `data/objects-ai/.quality/objNNN_SS/` with the Atlantis files
  (`attempt-N.png`, `.tiles/`, `.prompt.txt`, `.json`, `.error.txt`,
  `.review.json`). An object attempt's JSON adds `room_sha256`, the sha256 of the
  promoted room it was painted over, and `class` (`identical` | `render` | `skip`).
- Atomic writes as in Atlantis (`.tmp`/`.pending` then rename).

## 9. Room render core (differences from Atlantis)

### 9.1 Guide

1. Load the RGB(A) PNG. For an RGBA room, fill each transparent pixel with the
   colour of the nearest opaque pixel (iterative 4-neighbour dilation in numpy),
   so the model never sees a hole.
2. De-dither at native size (`DEDITHER_METHOD`, default `palette-smooth`; the
   spike decides whether `none` is better for the Dig's lightly dithered art).
3. Upscale 4x with Lanczos.

### 9.2 Window plan (2D)

- `WINDOW_WIDTH = 320`, `WINDOW_HEIGHT = 240` native, `WINDOW_OVERLAP = 64` on
  each axis. The window's 4x size is at most 1280x960.
- One function plans one axis: the Atlantis `plan_windows` rule (the first
  window at the start, the last flush with the end, starts on multiples of 8,
  every neighbour overlap ≥ `WINDOW_OVERLAP`). Columns and rows are planned
  separately and windows are their product, rendered **row by row, left to
  right**.
- Margins are found on all four sides (the Atlantis `blank_margins`, on the
  colour key); the span is rounded out to multiples of 8 on both axes.
- Room widths are multiples of 8 (SMAP strips), but six heights are not (230,
  399, 425, 450, 500, 780). The guide and the render canvas are **padded** at
  the bottom to the next multiple of 8 rows by repeating the last row, every
  window's 4x size is then a multiple of 32, and `finish_room` crops the
  canvas back to exactly `(4w, 4h)` before the colour match and the gate.
- Wraparound detection and the seam window stay horizontal-only, as in
  Atlantis; a wraparound room with more than one window row is a `plan_room`
  error (none exists in the Dig; it would need a design change).

### 9.3 Composite, mask and stitch

- A window's stitch origin is the middle of its overlap with its left
  neighbour (x) and with its upper neighbour (y), or its own edge when it has
  none.
- The composite is the guide window with everything already stitched pasted
  over it. The mask is `min(mask_x, mask_y)`, where `mask_x` is the Atlantis
  row ramp over columns (0 keeps the held overlap, 255 paints) and `mask_y` is
  the same ramp over rows. A first-row window has `mask_y = 255`; a first-column
  window has `mask_x = 255`. The kept region is L-shaped.
- `paste_window` pastes from the stitch origin on both axes.
  `stitch_boundaries` returns vertical boundaries (4x columns) and horizontal
  boundaries (4x rows), each with the span it runs along.

### 9.4 Finish

1. Colour match toward the guide in float CIE Lab (the Atlantis
   `colour_match`), with the statistics taken over opaque pixels only.
2. Fix-ups: the wraparound copy and the flat margins, as in Atlantis.
3. For an RGBA room, attach the alpha (source alpha, 4x nearest).
4. Geometry gate (§11).

### 9.5 Prompts and style

- Every prompt names *The Dig* (LucasArts, 1995) and describes its art as
  painted backgrounds mixed with pre-rendered 3D scenes.
- The caption question gains a `MEDIUM` section ("painted", "pre-rendered 3D"
  or "mixed"). When a room's `style` is blank, `caption` sets it to `rendered`
  if MEDIUM mentions pre-rendered, 3D or CGI, else `painted`.
- `painted` uses the Atlantis `PAINTED_RULES` wording, adapted to the Dig.
  `rendered` uses new `RENDERED_RULES`: a crisp high-definition 1990s
  pre-rendered CGI look, clean surfaces and specular light, same composition.
  Its negative prompt drops "3D render" and "CGI" from `PAINTED_NEGATIVE`.
- `INSERT_RULES`, the lettering rules, `SEAM_NOTE` and `GEOMETRY_CORRECTION`
  carry over.

### 9.6 Workflows

Unchanged from Atlantis: `qwen-image-2.1-i2i` (default), its fallback
`qwen-image-2.1-i2i-faithful` (denoise 0.9), and `qwen-edit-2511-canny`. The
graphs are copied unchanged. Their inputs are a guide, a composite and a mask
(`LoadImageMask` → `SetLatentNoiseMask`), which the object stage reuses. Only
`comfy_client` knows node ids; `OUTPUT_PREFIX` becomes `dig`.

## 10. Object stage (`objects`)

Runs with ComfyUI up, after `batch`. It processes the objects of the selected
rooms (`--room`), or single objects (`--object objNNN_SS`).

### 10.1 Status

Per object key, from its audit folder, as rooms, plus two new states:

- `waiting`: its room is not `done` (and not `skip`). This is reported, not an error.
- `stale`: the promoted object's `room_sha256` differs from the room's current
  promoted image. It is re-rendered on the next run, like `new`.

A `skip` room's objects are all written as nearest-neighbour 4x.

### 10.2 Classification

Deterministic, from pixels, recomputed on each run:

- `skip`: listed in the room's `skip_objects`. Written as nearest-neighbour 4x.
- `identical`: every opaque object pixel equals the native room pixel at the
  same position (colour keys). Output: the promoted room's 4x crop of the
  object rectangle, with the object's alpha. No render, no review.
- `render`: everything else.

### 10.3 Rendering one `render` object

1. **Context window** (native): the object rectangle grown by 32 px on each
   side, clamped to the room, then widened to at least 128x128 where the room
   allows, with its edges on multiples of 8 (clamped at the room's edge).
2. **Guide:** the object's native image, transparent pixels filled from the
   native room beneath, de-dithered and upscaled 4x as §9.1.
3. **Composite:** the promoted HD room cropped to the context window, with the
   object guide pasted at `(4(x − cx0), 4(y − cy0))`.
4. **Mask:** native pixels inside the object rectangle that are opaque and
   differ from the room beneath (the **diff**), grown by 2 native px, scaled 4x
   nearest, then the Atlantis ramp softening. Everything else is 0 (keep).
   The workflow's reference input is the composite.
5. **Prompt:** the room's render prompt (caption, kind, style, corrections)
   plus `OBJECT_NOTE`: repaint only the changed area, in the same style,
   light and brushwork as its surroundings, keeping its outline where the
   reference shows it.
6. **Seed:** `SEED + attempt − 1`, as rooms.
7. **Finish:** paste the render into the composite through the mask; crop the
   object rectangle; colour-match toward the object guide with statistics over
   the diff only; attach the alpha (the source alpha, 4x nearest) when
   `has_alpha`.
8. **Gate** (§11), then promote.

### 10.4 Multi-state objects

The 134 objects with several states (up to 14, mostly animation frames)
render each state independently with the same seed and context. The spike
(§14) checks one for flicker. If it flickers, the plan adds **chained states**:
state `k > 01` uses state `k − 1`'s promoted render as the composite's object
area, at denoise 0.6. Chained states are not built unless the spike asks for them.

## 11. Quality gates

Rooms:

- Size exactly 4x; mode RGB or RGBA per `has_alpha`; alpha byte-equal to the
  source alpha 4x nearest.
- Shift < `MAX_SHIFT` (0.5 native px) and edge agreement ≥ `MIN_EDGE_AGREEMENT`
  (0.80), over the room and per 2D window (the room's edge maps masked to the
  window's rectangle). Transparent native pixels are excluded from both
  measures. Thresholds and `MIN_WINDOW_EDGES` are as in Atlantis.
- Seam warnings at vertical and horizontal stitch boundaries (`seam_ratio`
  along either axis; warn only, as in Atlantis).

Objects:

- The same size, mode and alpha rules against the object.
- Pixels outside the mask equal the promoted room crop, byte for byte. This
  holds by construction; the assert catches a paste bug.
- Shift and edge agreement measured on the context window. A sparse window
  (< `MIN_WINDOW_EDGES`) reads 1.0.

A gate failure writes `source: geometry` into `reviews.yaml`; the next run
retries with `GEOMETRY_CORRECTION`.

## 12. Review

- Rooms: as in Atlantis (a guide/render pair per window, plus the overview),
  with the Dig wording and the `style` in the prompt.
- Objects: **one VLM request per room**, covering its `render` objects whose
  latest attempt is unreviewed. The request holds a sheet of before/after
  pairs (the context-window guide next to the context-window render, each
  labelled with its key) plus the room overview. The reply is JSON with a
  verdict and issues per key, parsed by `parse_object_reviews`. A key missing
  from the reply stays unreviewed. At about 5 minutes per request, one request
  per room (at most about 100) replaces one per rendered object (up to 642,
  about 50 hours).
- A room is re-rendered when its review rejects it. Its objects become `stale`
  once the new room is promoted.

## 13. Stages and commands

| Target | What it does |
|---|---|
| `make caption [room=] [force=1]` | Captions and `style` into `rooms.yaml` (vLLM) |
| `make dry-run [room=] [workflow=] [strength=] [force=1]` | Room windows (2D), margins, wrap, corrections |
| `make batch [room=] [workflow=] [strength=] [memcheck=0] [force=1]` | Render and promote rooms (ComfyUI) |
| `make objects [room=] [object=] [workflow=] [memcheck=0] [force=1]` | Classify, render and promote objects (ComfyUI) |
| `make review [room=] [force=1]` | Review rooms, then objects (vLLM) |
| `make verify [room=]` | Audit both trees against the manifest |
| `make server`, `install`, `check`, `test`, `clean` | As in Atlantis |

Environment: `DIG_SRC`, `DIG_DST` (rooms, default `data/rooms-ai`),
`DIG_OBJ_DST` (default `data/objects-ai`), `DIG_ROOMS`, `DIG_REVIEWS`,
`DIG_WORKFLOW`, `DIG_MATCH_STRENGTH`, and unchanged `COMFY_URL`, `COMFY_DIR`,
`VLM_BASE_URL`, `VLM_MODEL`, `VLM_API_KEY`.

## 14. Spike

Before the object stage is built, render with the finished room path:

- rooms 11 and 60 (painted), 43 (painted, busy), 2 and 4 (rendered), and 27
  (512x780, a 2D window grid);
- one multi-state object, chosen once placement exists (the one with the most
  states in a spike room).

Decide and record in the plan:

1. `DEDITHER_METHOD`: `palette-smooth` or `none`.
2. `WINDOW_HEIGHT`: 240, or 200 if 240-tall windows drift past the gate.
3. Whether `RENDERED_RULES` keeps rooms 2 and 4 recognisably CGI and passing the gate.
4. Whether states flicker (§10.4).

## 15. Modules (the kit)

As in the Atlantis kit's AGENTS.md §2, with:

| File | Change |
|---|---|
| `dig_recreate.py` | Replaces `atl_recreate.py`; adds `cmd_objects`, object status, per-room object review |
| `source_tree.py` | Dig manifest, rooms and objects, colour keys, placement validation |
| `room_geometry.py` | Transparent fill, 2D plan, L masks, 2D stitch and boundaries, alpha attach |
| `object_geometry.py` | New: classification, context window, diff mask, object composite, crop and alpha |
| `geometry_check.py` | Opaque-pixel masking, horizontal seams |
| `colour_match.py` | Optional pixel mask for the statistics |
| `prompts.py` | Dig wording, `MEDIUM`, `RENDERED_RULES`, `OBJECT_NOTE`, the object review question and parser |
| `rooms_file.py` | `style` and `skip_objects` fields |
| `comfy_client.py` | `OUTPUT_PREFIX = "dig"`; otherwise unchanged |

`object_geometry.py` must not talk to services or know files, like
`room_geometry.py`.

## 16. Error handling

As in Atlantis: a render that raises writes `attempt-N.error.txt`, counts as
failed, never counts toward STUCK, and batch sweeps the item's stray ComfyUI
outputs. `/free` is sent at the end of `batch` and `objects` and at the start
of `review`, and the memory floor applies to both render stages. Exit code 1
when any item failed on infrastructure. A pre-0.2.0 manifest, or an object
entry missing `room`, `x` or `y`, is a load failure (exit 2). An object whose
rectangle is not inside its room (§6) loads, is reported `BADPLACE` by
`objects` and `verify`, and is never rendered; it does not stop the others.

## 17. Testing

Unit tests, with no GPU or network.

- Kit (`unittest`, as in Atlantis): the ported Atlantis tests, plus 2D window
  planning (coverage, overlap on both axes, multiples of 8, row-by-row order,
  single-window rooms), L masks and 2D stitching on synthetic images,
  transparent fill and alpha attach, colour keys and four-side margins,
  object classification, context-window clamping at room edges, diff masks,
  the outside-mask equality gate, `stale` and `waiting` status, the object
  review parser, and manifest validation (missing placement, old version,
  out-of-room object).
- Exporter (`pytest`, grouped, ≤ 3 functions per module, per its AGENTS.md):
  a synthetic `IMHD` fixture asserting `room`, `x`, `y` (including a negative
  `x`), plus the manifest writer emitting them only for `la1:` entries.

## 18. Build order

1. Create `thedig-hd-bundle`; subtree-merge `thedig-textures` as
   `thedig-textures-exporter/`; top-level README.
2. Exporter placement fields, tests, spec §5.1; re-extract LA1.
3. Fork the kit into `thedig-texture-enhancement/`: copy, rename `ATL_*` →
   `DIG_*` and `atl_` → `dig_`, Dig `source_tree`, seeded `rooms.yaml`;
   Atlantis tests green.
4. 2D windows, L masks, 2D stitch, transparent rooms, gates.
5. Prompts: Dig wording, `MEDIUM`, `style`.
6. Spike (§14); record the decisions.
7. Object stage.
8. Object review and `verify`.
9. Full run: caption, batch, objects, review, until nothing is new or rejected.

## 19. Risks and open items

- **Placement semantics.** `IMHD` x/y are assumed to be room pixel
  coordinates of the image's top-left. Step 2 checks this on a few `identical`
  objects: an exact pixel match at the placement confirms it.
- **Flicker in multi-state objects** (§10.4).
- **Tall windows** may drift more than Atlantis's 200-tall ones (§14).
- **Pre-rendered rooms** may resist a style that differs from the model's
  painterly bias; `faithful` and caption edits are the levers.
- **Colour cycling** is lost in stills.

## 20. Legal

Personal use only. The extracted and regenerated art is LucasArts/Disney
copyright. Do not redistribute it; never commit it.
