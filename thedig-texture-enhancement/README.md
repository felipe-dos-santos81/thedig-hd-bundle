# The Dig Background and Object Regeneration

Regenerates the 111 room backgrounds and 642 room object images of *The Dig*
(LucasArts, 1995, SCUMM v7) as painted or pre-rendered high-definition art at
exactly 4x their native size, with local models:

- ComfyUI running one of two render workflows, chosen per run: Qwen-Image 2.1
  img2img (`qwen-image-2.1-i2i`, the default, with `qwen-image-2.1-i2i-faithful`
  as its fallback for stuck rooms and objects), or Qwen-Image-Edit 2511 with
  the InstantX Canny ControlNet (`qwen-edit-2511-canny`).
- vLLM serving `Qwen/Qwen3.8-27B`, which captions each room before rendering
  and reviews each promoted room and object afterwards.

Input: `../thedig-textures-exporter/out/` (override with `DIG_SRC`), the
output of `thedig-textures extract --only la1` at tool version 0.2.0 or
later: RGB or RGBA room and object PNGs and `manifest.json`.
Output: `data/rooms-ai/room_NNN.png` (override with `DIG_DST`) and
`data/objects-ai/objNNN_SS.png` (override with `DIG_OBJ_DST`).

**Personal use only.** The extracted and regenerated art is LucasArts/Disney
copyright. Do not redistribute it. `data/` and `reviews.yaml` are gitignored;
never commit art.

## Pipeline

```
DIG_SRC (exporter out/) ─[caption]─▶ rooms.yaml ─(you edit)─┐
                                                             ▼
data/rooms-ai/room_NNN.png     ◀─[batch]──── rooms.yaml + reviews.yaml
data/objects-ai/objNNN_SS.png  ◀─[objects]── promoted rooms + placement
        └──────[review]──▶ reviews.yaml ──▶ batch / objects again for rejects
```

`caption` and `review` need vLLM; `batch` and `objects` need ComfyUI; they
never run together (GB10 unified memory, as in Atlantis).

1. **`make caption`** (vLLM up) describes every `scene` and `insert` room
   whose caption is blank and writes it into `rooms.yaml`, saving after each
   room; a blank `style` is set from the caption's MEDIUM section (`painted`
   or `rendered`). `force=1` redoes all; blanking one caption redoes that room.
2. **Edit `rooms.yaml`.** The caption becomes the REFERENCE OBSERVATIONS
   block of every window's prompt; an insert's `TEXT:` section becomes the
   lettering its render must reproduce. `style` may be overridden by hand.
   `skip_objects` lists object keys (`objNNN_SS`) to write as a
   nearest-neighbour 4x instead of rendering.
3. **`make batch`** (ComfyUI up, vLLM stopped) renders every captioned room
   whose output is missing or whose latest attempt was rejected, and writes
   each `skip` room as a nearest-neighbour 4x. On exit, even after a failure,
   it frees ComfyUI's models so vLLM can start.
4. **`make objects`** (ComfyUI up, after `batch`) classifies every object of
   the selected rooms and repaints the ones that differ from the room beneath
   them, over each room's promoted render.
5. **`make review`** (vLLM up) judges every promoted room whose latest
   attempt is unreviewed, then every promoted `render` object whose latest
   attempt is unreviewed, and writes `reviews.yaml`.
6. **`make batch` and `make objects` again** redo only the rejected rooms and
   objects, with the next seed and the issues as corrections. Repeat 5 and 6.
7. **`make verify`** audits `data/rooms-ai/` and `data/objects-ai/`.

`make dry-run` and `make objects-dry-run` print what `batch` and `objects`
would do (windows, wraparound, margins, corrections, classification) without
touching ComfyUI.

## Swapping the services on this host

vLLM (about 73 GB) and a render (about 45 GB) do not fit together in the
GB10's 121 GB of unified memory.

| Service | Start | Stop |
|---|---|---|
| vLLM | `docker start lmcache-server vllm-server` | `docker stop vllm-server lmcache-server` |
| ComfyUI | `make server` (foreground) or `sudo systemctl start comfyui` | Ctrl-C, or `sudo systemctl stop comfyui` |

`make batch` and `make objects` refuse to start with less than 45 GB free
(`memcheck=0` skips the guard). If vLLM cannot start after a batch, free
ComfyUI's models by hand:

```
curl -X POST http://127.0.0.1:8188/free -H 'Content-Type: application/json' -d '{"unload_models":true,"free_memory":true}'
```

## Rooms

`rooms.yaml` has one entry per manifest room:

```yaml
room_034:
  kind: scene          # scene | insert | skip
  style: painted       # painted | rendered; blank until caption fills it
  caption: >-
    ...
  skip_objects: []     # optional: object keys written as nearest-neighbour 4x
```

- `scene`: a room or cutscene background.
- `insert`: a close-up with lettering, a map or a puzzle piece; its prompt
  adds the lettering rules and its review checks the lettering.
- `skip`: written as a nearest-neighbour 4x, never rendered.

| Kind | Rooms |
|---|---|
| `skip` | 1, 86, 93 (one flat colour); 103, 104 (two-colour line charts); 88 (sprite sheet) |
| `insert` | 28, 35, 51, 59, 69, 76, 79, 106, 107 |
| `scene` | all others (96 rooms) |

`style` picks the render and negative prompt: `painted` (the default) asks
for confident painterly brushwork; `rendered` asks for a crisp pre-rendered
3D look and drops "3D render"/"CGI" from the negative prompt. `make caption`
sets a blank `style` from the caption's MEDIUM section; edit it by hand to
correct a misread.

A room whose manifest entry has `has_alpha: true` (rooms 32, 34, 85, 88, 107)
is regenerated as RGBA with its alpha channel **byte-equal** to the source
alpha scaled 4x nearest-neighbour: transparent pixels are filled with their
nearest opaque neighbour's colour before rendering so the model never paints
a hole, then the exact source alpha is reattached.

A room whose native height is not a multiple of 8 (230, 399, 425, 450, 500,
780 native rows) is padded at the bottom to the next multiple of 8 by
repeating its last row before planning windows, so every window's 4x size is
a multiple of 32; the padding is cropped away before the colour match and the
gate. A room wider than 320 native columns or taller than 240 native rows
renders as a 2D grid of overlapping windows (at least 64 columns or rows of
overlap on each axis), planned row by row, left to right, and stitched back
together; room 27 (512x780) is one such grid.

## Objects

Every room object (an OBIM image placed at `x, y` in its room) is classified
from pixels on each run:

- `skip`: listed in the room's `skip_objects`. Written as a nearest-neighbour
  4x.
- `identical`: every opaque object pixel equals the native room pixel beneath
  it. Output: the promoted room's 4x crop of the object rectangle, with the
  object's own alpha. No render, no review.
- `render`: everything else. Repainted in its **context window** (the object
  rectangle grown 32 native px on each side, clamped to the room, then
  widened to at least 128x128 where the room allows, its edges on multiples
  of 8) over the promoted room, through a mask that paints only the object's
  changed pixels (grown 2 native px and softened).

Besides the room states (`new`, `stuck`, `failed`, `rejected`, `missing`,
`done`), an object also reports:

- `waiting`: its room is not yet `done` (and not `skip`). Reported, not an
  error; `make objects` retries it once the room is promoted.
- `stale`: it is `done`, but its promoted attempt's `room_sha256` names a
  different file than the room's current promoted output (the room was
  re-rendered since). Re-rendered on the next `make objects`, like `new`. A
  `done` object whose current output file no attempt record promoted (hand-
  replaced) keeps its status unchanged; `make verify` reports that file
  `UNRECORDED` instead.
- `BADPLACE`: the object's rectangle is not inside its room (a manifest
  placement error). Reported by `make objects` and `make verify`; never
  rendered, and it never stops the others.

## Checks

Rooms: before a render is promoted, `make batch` colour-matches it toward its
guide in float CIE Lab (a render whose colours already agree comes back
within one level; RGBA rooms match over opaque pixels only), then checks it:

- **Size:** exactly 4x native; RGB or RGBA per the manifest's `has_alpha`,
  with the exact source alpha.
- **Geometry:** the render, box-downscaled to native size, must not be
  shifted by half a native pixel or more — over the room and within each 2D
  window — and must keep most of the source's strong edges, per window
  (transparent native pixels excluded; thresholds: AGENTS.md §3). A failure
  is written to `reviews.yaml` as `source: geometry`, and the next batch
  retries the room.
- **Seams:** a vertical or horizontal stitch boundary whose colour step is
  far more than the local texture's own step there is printed as a warning.

Objects: the same size, mode and alpha rules against the object, plus:

- Every pixel the mask keeps (outside the repainted area) equals the
  promoted room, byte for byte. This holds by construction; the check
  catches a paste bug.
- Shift and edge agreement are measured over the whole context window,
  treated as the object's own one window (a room-wide measure would hide the
  object's own drift under the unchanged room around it). A context window
  with too few strong source edges reads 1.0.

A rejected room or object's next attempts carry the rejection's issues as
corrections until one is promoted, even across a failed attempt in between;
a geometry rejection's correction is one fixed sentence asking the model to
keep the reference layout.

A room or object is **STUCK** when its latest judged attempt (one with a
record) was rejected and it has had 4 judged attempts. With the default
workflow, the next batch renders it once more through
`qwen-image-2.1-i2i-faithful` (denoise 0.9: a cleaner upscale that keeps
closer to the source). If that is rejected too, the run reports it and
leaves it alone.

- Fix a stuck room's caption, then run `make batch room=N force=1`.
- Fix a stuck object's room caption, or add the object to `skip_objects`,
  then run `make objects object=objNNN_SS force=1`.

A failed attempt (a ComfyUI error, a timeout, Ctrl-C) has no record and never
counts, so an item only failing on infrastructure is retried on every run
instead, and the run exits 1.

To restart an item from scratch, delete its `.quality/<key>/` folder **and**
its entry in `reviews.yaml` — a leftover entry becomes current again once new
attempts reach its attempt number — then run with `force=1`.

## Outputs and the audit folder

```
data/rooms-ai/room_NNN.png            the promoted render
data/rooms-ai/.quality/room_NNN/
  attempt-N.png                       the raw stitch, before the colour match
  attempt-N.tiles/                    window-K.{guide,composite,mask}.png, window-K.png, seam.*
  attempt-N.prompt.txt                starts "workflow: NAME"; every window's prompt
  attempt-N.json                      seed, windows, wrap, margins, match, geometry, promoted, sha256, seconds
  attempt-N.error.txt                 a failed attempt: workflow, seed, window, seconds, error (no .json)
  attempt-N.review.json               the VLM verdict

data/objects-ai/objNNN_SS.png                 the promoted render (or the identical/skip crop)
data/objects-ai/.quality/objNNN_SS/
  attempt-N.png                       the finished context window, before the crop
  attempt-N.tiles/                    object.{guide,composite,mask}.png, object.png
  attempt-N.prompt.txt                the object prompt (render objects only)
  attempt-N.json                      class, room, room_sha256, plus (render) workflow, seed,
                                       context, match, geometry, promoted, sha256, seconds
  attempt-N.error.txt                 a failed attempt (no .json)
  attempt-N.review.json               the VLM verdict (render objects only)
```

## Commands

| Target | What it does |
|---|---|
| `make caption [room=] [force=1]` | Write captions and `style` into `rooms.yaml` |
| `make dry-run [room=] [workflow=] [strength=] [dedither=] [force=1]` | Show what `batch` would render |
| `make batch [room=] [workflow=] [strength=] [dedither=] [memcheck=0] [force=1]` | Render and promote rooms into `data/rooms-ai` |
| `make objects-dry-run [room=] [object=] [workflow=] [force=1]` | Show what `objects` would classify and render |
| `make objects [room=] [object=] [workflow=] [strength=] [dedither=] [memcheck=0] [force=1]` | Classify, render and promote room objects into `data/objects-ai` |
| `make review [room=] [force=1]` | Review promoted rooms, then promoted objects, into `reviews.yaml` |
| `make verify [room=] [object=]` | Audit both output trees against the manifest, the 4x rule and the attempts |
| `make server` | Start ComfyUI from `~/ComfyUI` on :8188 |
| `make install` / `make check` / `make test` / `make clean` | venv / byte-compile / unit tests / caches |

`room="1 29 58"` and `object="obj010_01 obj010_02"` select by number or key
(repeatable); every stage target also takes `src=DIR`, `dst=DIR` and
`obj_dst=DIR`. `--object` is accepted by every stage but only `objects`,
`review` and `verify` act on it; passed alone (no `room=`), `review` and
`verify` touch only the named objects, not any room. Environment overrides:
`DIG_SRC`, `DIG_DST`, `DIG_OBJ_DST`, `DIG_ROOMS`, `DIG_REVIEWS`,
`DIG_WORKFLOW`, `DIG_MATCH_STRENGTH`, `COMFY_URL`, `COMFY_DIR`,
`VLM_BASE_URL`, `VLM_MODEL`, `VLM_API_KEY`.

## Setup

- `make install` creates `.venv` with Pillow, PyYAML and numpy.
- ComfyUI at `~/ComfyUI` (override with `COMFY_DIR`), at or after commit
  c194dd0 (2026-09-20), with these files under `models/`:
  - `qwen-edit-2511-canny`: `diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors`,
    `text_encoders/qwen_2.5_vl_7b_uncensored_comfy_ready_bf16.safetensors`,
    `vae/qwen_image_vae.safetensors`,
    `controlnet/Qwen-Image-InstantX-ControlNet-Union.safetensors`;
  - `qwen-image-2.1-i2i` and its fallback: `diffusion_models/qwen_image_2.1_bf16.safetensors`,
    `text_encoders/qwen3vl_8b_bf16.safetensors`,
    `vae/qwen_image_2.1_vae_bf16.safetensors`.

  `make batch` and `make objects` check the files and the node classes
  before rendering.
- vLLM serving `Qwen/Qwen3.8-27B` at `http://127.0.0.1:8000/v1`.

## Project structure

| File | Purpose |
|---|---|
| `dig_recreate.py` | Driver: `caption`, `batch`, `objects`, `review`, `verify`; preflights, audit folders, promotion |
| `source_tree.py` | Reads and validates the extractor's `manifest.json`: rooms, objects, placement, colour keys |
| `room_geometry.py` | Guide image, margins, wraparound, 2D windows, composites/masks, stitch, seam, fix-ups |
| `object_geometry.py` | Classification, context window, object composite/mask, compose, crop, check |
| `geometry_check.py` | The shift, edge and seam measures |
| `colour_match.py` | The Lab transfer of a render toward its source, over an optional pixel mask |
| `prompts.py` | Caption, render and review prompts; VLM requests; the review parsers |
| `comfy_client.py` | ComfyUI HTTP client and the workflow registry; the only place that knows node ids |
| `recreation_qwen2511_canny.json`, `recreation_qwen21_i2i.json` | ComfyUI API graphs (unchanged from Atlantis) |
| `rooms.yaml` | Kinds, captions, styles and `skip_objects` of the 111 rooms |
| `Makefile`, `run_batch.sh`, `run_server.sh` | Targets and wrappers |
| `testkit.py`, `test_*.py` | Test support and unit tests (no GPU, no network) |
| `NOTES.md` | Live checks, spikes and runs (created by the first room spike) |

The design spec and build plan are at the bundle root:
[`../docs/superpowers/specs/2026-09-25-thedig-regeneration-design.md`](../docs/superpowers/specs/2026-09-25-thedig-regeneration-design.md),
[`../docs/superpowers/plans/2026-09-26-thedig-regeneration.md`](../docs/superpowers/plans/2026-09-26-thedig-regeneration.md).
