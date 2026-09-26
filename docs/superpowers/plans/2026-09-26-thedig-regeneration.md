# The Dig Room and Object Regeneration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Regenerate The Dig's 111 LA1 room backgrounds and 642 room object images at exactly 4x through local ComfyUI models, re-import-safe, with a geometry gate and a VLM review loop.

**Architecture:** A new monorepo `~/code/thedig-hd-bundle` holds the existing extractor (subtree-merged, gaining object placement fields in its manifest) and a new kit forked from the Fate of Atlantis kit. The kit keeps the Atlantis stages (caption → batch → review → verify) and adds 2D windows, padding, transparent rooms, a per-room `style`, and a new `objects` stage that repaints each object in context over its promoted HD room through the existing latent-noise-mask workflows.

**Tech Stack:** Python 3.12, Pillow, numpy, PyYAML, `unittest` (kit), `pytest` (exporter); ComfyUI (Qwen-Image 2.1 i2i, Qwen-Image-Edit 2511 + InstantX Canny) on `:8188`; vLLM `Qwen/Qwen3.8-27B` on `:8000`.

**Spec:** `docs/superpowers/specs/2026-09-25-thedig-regeneration-design.md` (after Task 1 it lives at the bundle root). The Atlantis kit it forks from is `~/code/atlantis-hd-bundle/atlantis-texture-enhancement` (read its `AGENTS.md` once before Task 3).

## Global Constraints

- Python ≥ 3.12. Kit runtime dependencies are exactly `pillow>=10`, `pyyaml>=6`, `numpy>=1.26`; the exporter's is `pillow>=10` only. No new dependencies.
- Every output is exactly `(4w, 4h)` of its native asset (`SCALE = 4`). RGB when the manifest's `has_alpha` is false; RGBA when true, with an alpha channel byte-equal to the source alpha scaled 4x nearest-neighbour.
- The kit reads `DIG_SRC` only through `source_tree`, never writes under it, and never reads game files.
- Never commit game art: the exporter's `out/`, the kit's `data/` and `reviews.yaml` stay gitignored. The bundle's remote is public.
- Only `comfy_client` knows ComfyUI node ids. The two workflow JSON graphs are copied from Atlantis unchanged.
- Services are external. The driver never starts or stops vLLM or ComfyUI; they never run together; `MEMORY_FLOOR_GB = 45` guards both render stages.
- Atomic writes: YAML/JSON through `<name>.tmp` + rename, images through `<name>.pending` + rename (the Atlantis helpers).
- Gate thresholds unchanged: `MAX_SHIFT = 0.5`, `MIN_EDGE_AGREEMENT = 0.80`, `EDGE_THRESHOLD = 80.0`, `RENDER_EDGE_THRESHOLD = 60.0`, `MIN_WINDOW_EDGES = 100`, `SEAM_WARN = 3.0`.
- Windows: `WINDOW_WIDTH = 320`, `WINDOW_HEIGHT = 240`, `WINDOW_OVERLAP = 64`, `ALIGN = 8` native; every window's and every object context's 4x size is a multiple of 32.
- `SEED = 42` (attempt N uses `SEED + N − 1`), `MAX_ATTEMPTS = 4`, `DEFAULT_WORKFLOW = "qwen-image-2.1-i2i"` with fallback `qwen-image-2.1-i2i-faithful`, `DEFAULT_MATCH_STRENGTH = 0.5`.
- Environment prefix `DIG_` (`DIG_SRC`, `DIG_DST`, `DIG_OBJ_DST`, `DIG_ROOMS`, `DIG_REVIEWS`, `DIG_WORKFLOW`, `DIG_MATCH_STRENGTH`); `COMFY_URL`, `COMFY_DIR`, `VLM_BASE_URL`, `VLM_MODEL`, `VLM_API_KEY` unchanged.
- Exporter: `tool_version` 0.2.0; its four byte-exact differentials must stay green; its tests are pytest, grouped, ≤ 3 functions per module (its `AGENTS.md`).
- Kit tests: `unittest`, no GPU, no network; `testkit.py` is the only shared test-support module; one test module per production module.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **A room whose height is not a multiple of 8** (230, 399, 425, 450, 500, 780): it must render through padded windows and come back exactly `(4w, 4h)`, not crash or change size. Pinned in Task 5 (`plan_room` on 352×470) and Task 6 (driver render of a 352×470 room).
2. **An object placed outside its room, or in a room the manifest lacks**: it must load, be reported `BADPLACE`, never render, and not stop the other objects or fail the run. Pinned in Task 4 (`placement_error`) and Task 11 (the `objects` run).
3. **An object whose room is `skip`, or listed in `skip_objects`**: it must be written as a nearest 4x copy, never wait forever for a room render. Pinned in Task 11.
4. **A `has_alpha` asset with no transparent pixel** (room 32): the output must still be RGBA with alpha 255 everywhere. Pinned in Task 7.
5. **A VLM object review that omits a key, adds an unknown key, or contradicts itself for one object**: that object stays unreviewed, the others are recorded. Pinned in Task 12 (`parse_object_reviews`) and the driver review test.

---

## File Structure

```
~/code/thedig-hd-bundle/
  README.md                                   the two projects and their order (Task 1)
  .gitignore                                  .superpowers/, .DS_Store (Task 1)
  docs/superpowers/specs/2026-09-25-thedig-regeneration-design.md   (moved in Task 1)
  docs/superpowers/plans/2026-09-26-thedig-regeneration.md          (moved in Task 1)
  thedig-textures-exporter/                   subtree of ~/code/thedig-textures (Task 1)
    digart/la1.py          La1Bitmap gains room/x/y (Task 2)
    digart/manifest.py     AssetRecord gains room/x/y (Task 2)
    digart/cli.py          _record passes room/x/y (Task 2)
    digart/__init__.py, pyproject.toml   0.2.0 (Task 2)
    tests/test_la1.py, tests/test_cli.py, tests/test_manifest.py (Task 2)
  thedig-texture-enhancement/                 fork of atlantis-texture-enhancement (Task 3)
    dig_recreate.py        driver: caption, batch, objects, review, verify
    source_tree.py         Dig manifest: rooms, objects, colour keys, placement (Task 4)
    room_geometry.py       guide, padding, transparent fill, 2D plan/masks/stitch, alpha (Tasks 4–7)
    object_geometry.py     NEW: classification, context window, object inputs, compose, check (Task 10)
    geometry_check.py      2D windows, row seams, opaque mask, min_edges (Tasks 6–7)
    colour_match.py        optional statistics mask (Task 7)
    prompts.py             Dig wording, MEDIUM, style rules, window note, object prompts/review (Tasks 6, 8, 11, 12)
    rooms_file.py          style, skip_objects, object review keys (Tasks 8, 11)
    comfy_client.py        OUTPUT_PREFIX "dig" (Task 3)
    testkit.py             Dig-shaped miniature source with objects (Task 4)
    test_*.py              one per module
    rooms.yaml             seeded kinds (Task 8)
    NOTES.md               live checks, spike and run log (Task 9)
    README.md, AGENTS.md, CLAUDE.md (Task 13)
```

---

### Task 1: Create the `thedig-hd-bundle` monorepo

**Files:**
- Create: `~/code/thedig-hd-bundle/README.md`, `~/code/thedig-hd-bundle/.gitignore`
- Move: the spec and this plan to `~/code/thedig-hd-bundle/docs/superpowers/{specs,plans}/`

**Interfaces:**
- Consumes: `~/code/thedig-textures` on branch `docs/thedig-regeneration-spec` (holds the spec and this plan).
- Produces: repo `~/code/thedig-hd-bundle`, branch `main` with the subtree, then branch `feat/dig-regeneration` for Tasks 2–14. The exporter lives at `thedig-textures-exporter/`.

- [ ] **Step 1: Create the repo and the README**

```bash
mkdir ~/code/thedig-hd-bundle && cd ~/code/thedig-hd-bundle
git init -b main
```

Write `README.md`:

```markdown
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
```

Write `.gitignore`:

```
.superpowers/
.DS_Store
```

```bash
git add README.md .gitignore
git commit -m "chore: start thedig-hd-bundle

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 2: Subtree-merge the extractor with its history**

```bash
cd ~/code/thedig-hd-bundle
git subtree add --prefix=thedig-textures-exporter ~/code/thedig-textures docs/thedig-regeneration-spec
```

Expected: a merge commit; `git log --oneline | wc -l` is above 20.

- [ ] **Step 3: Move the design documents to the bundle root**

```bash
mkdir -p docs/superpowers/specs docs/superpowers/plans
git mv thedig-textures-exporter/docs/superpowers/specs/2026-09-25-thedig-regeneration-design.md docs/superpowers/specs/
git mv thedig-textures-exporter/docs/superpowers/plans/2026-09-26-thedig-regeneration.md docs/superpowers/plans/
git commit -m "docs: move the regeneration spec and plan to the bundle root

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4: Verify the extractor still passes in its new place**

Run: `cd ~/code/thedig-hd-bundle/thedig-textures-exporter && make check`
Expected: pytest passes (game-marked tests deselected).

- [ ] **Step 5: Branch for the feature work**

```bash
cd ~/code/thedig-hd-bundle && git checkout -b feat/dig-regeneration
```

- [ ] **Step 6: Ask before publishing**

Ask the user whether to create the public GitHub remote now. Only on an explicit yes:

```bash
gh repo create felipe-dos-santos81/thedig-hd-bundle --public --source ~/code/thedig-hd-bundle --push
```

---

### Task 2: Exporter manifest placement fields (0.2.0)

**Files:**
- Modify: `thedig-textures-exporter/digart/la1.py` (`La1Bitmap`, `_process_room`, new `_les16`)
- Modify: `thedig-textures-exporter/digart/manifest.py` (`AssetRecord`)
- Modify: `thedig-textures-exporter/digart/cli.py` (`_record`, `_extract_family`)
- Modify: `thedig-textures-exporter/digart/__init__.py`, `thedig-textures-exporter/pyproject.toml` (version)
- Modify: `thedig-textures-exporter/docs/superpowers/specs/2026-09-24-thedig-textures-design.md` §5.1, `thedig-textures-exporter/README.md`
- Test: `tests/test_la1.py`, `tests/test_cli.py`, `tests/test_manifest.py` (extend existing functions; the ≤3-per-module rule stands)

**Interfaces:**
- Produces: manifest entries whose id starts `la1:` gain `"room": int` after `"path"`; `la1:obj…` entries also gain `"x": int, "y": int` (signed IMHD `x_pos`/`y_pos`, SCUMM v7 offsets 8 and 10 of the IMHD payload, confirmed against upstream ScummVM `object.h` `ImageHeader.v7`). `akos:`, `san:`, `nut:` entries have none of these keys. `tool_version` is `"0.2.0"`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_la1.py`, `test_la1_room_and_object_bitmaps`: after the first room's assertions add

```python
    assert (bmp.room, bmp.x, bmp.y) == (1, None, None)  # a backdrop has a room, no position
```

and replace the object block's `imhd`/`room` lines and final assertions with

```python
    imhd = chunk(b"IMHD", struct.pack("<IHHhhHH", 7, 63, 1, -16, 24, w, h))
    obim = chunk(b"OBIM", imhd + chunk(b"IM01", bomp))
    rmhd = chunk(b"RMHD", struct.pack("<IHHH", 7, w, h, 0))
    errors = []
    room = fx.la1_container(chunk(b"ROOM", rmhd + fx.palette_wrap(PAL) + obim), room=5)
    bitmaps = list(L.iter_bitmaps(room, errors))
    assert errors == []
    assert len(bitmaps) == 1
    assert bitmaps[0].name == "obj063_01"
    assert bitmaps[0].index == bytes(range(1, 9))
    assert bitmaps[0].transparent0 is False
    assert (bitmaps[0].room, bitmaps[0].x, bitmaps[0].y) == (5, -16, 24)  # IMHD x_pos is signed
```

In `tests/test_cli.py`, `obim_bomp_la1`: change the IMHD to `struct.pack("<IHHhhHH", 7, 63, 1, 40, 16, w, h)`. In `test_extract_transparency_and_stale_errors`, after the BOMP asset's id assertion add

```python
    assert (asset["room"], asset["x"], asset["y"]) == (1, 40, 16)
    assert list(asset)[-4:] == ["path", "room", "x", "y"]
```

and after the AKOS asset's id assertion add

```python
    assert not {"room", "x", "y"} & set(asset)          # costume cels carry no placement
```

In `tests/test_manifest.py`, at the end of `test_manifest_schema_counts_and_palette_sidecars` add

```python
    obj = AssetRecord(id="la1:obj063_01", kind="la1_bitmap", source="DIG.LA1", frame=None,
                      name="obj063_01", width=8, height=4, has_alpha=True, palette=h,
                      path="la1/obj063_01.png", room=3, x=-8, y=16).to_dict()
    assert list(obj)[-4:] == ["path", "room", "x", "y"]
    assert (obj["room"], obj["x"], obj["y"]) == (3, -8, 16)
    assert "room" not in san_record(h, 0).to_dict()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd thedig-textures-exporter && .venv/bin/python -m pytest tests/test_la1.py tests/test_cli.py tests/test_manifest.py -q`
Expected: FAIL (`AttributeError: 'La1Bitmap' object has no attribute 'room'`, `TypeError: ... unexpected keyword argument 'room'`).

- [ ] **Step 3: Implement**

`digart/la1.py`: change the dataclass import to `from dataclasses import dataclass, field, replace`, and add to `La1Bitmap` after `transparent`:

```python
    # Where the bitmap lives in the game. Keyword-only, so AkosCel's positional
    # fields still follow `transparent`: the LOFF room number of the ROOM it was
    # decoded from, and for an OBIM image its IMHD x_pos/y_pos (signed native room
    # pixels). None for AKOS cels; x and y None for room backdrops.
    room: int | None = field(default=None, kw_only=True)
    x: int | None = field(default=None, kw_only=True)
    y: int | None = field(default=None, kw_only=True)
```

Add next to `_le16`:

```python
def _les16(data: bytes, off: int) -> int:
    return struct.unpack_from("<h", data, off)[0]
```

In `_process_room`, the RMIM branch yields `replace(bmp, room=room)` instead of `bmp`. In the OBIM branch read the position after `obj_id`:

```python
                ox = _les16(data, imhd + 8 + 8)
                oy = _les16(data, imhd + 8 + 10)
```

and yield `replace(bmp, room=room, x=ox, y=oy)` instead of `bmp`.

`digart/manifest.py`, `AssetRecord`: add after `path: str`

```python
    room: int | None = None
    x: int | None = None
    y: int | None = None
```

and end `to_dict` with

```python
        for key in ("room", "x", "y"):
            value = getattr(self, key)
            if value is not None:
                d[key] = value
        return d
```

(binding the existing dict literal to `d` first).

`digart/cli.py`: give `_record` three keyword parameters `room: int | None = None, x: int | None = None, y: int | None = None` and add `"room": room, "x": x, "y": y,` to its dict just before `"_palette_bytes"`. In `_extract_family` pass `room=item.room, x=item.x, y=item.y` to `_record`.

`digart/__init__.py`: `__version__ = "0.2.0"`. `pyproject.toml`: `version = "0.2.0"`.

- [ ] **Step 4: Run the whole suite**

Run: `cd thedig-textures-exporter && make check`
Expected: PASS. If a test pins `"0.1.0"`, update it to `digart.__version__`.

- [ ] **Step 5: Document the contract**

In the exporter spec §5.1, after the paragraph ending "…from this file alone.", add:

```markdown
Since 0.2.0 every entry whose `id` starts `la1:` also carries `"room"`: the LOFF
room number of the `ROOM` it was decoded from. Every `la1:obj…` entry also carries
`"x"` and `"y"`: its `IMHD` `x_pos` and `y_pos` (signed 16-bit, SCUMM v7 payload
offsets 8 and 10), the native room position of the image's top-left pixel. These
keys follow `path`; `akos:`, `san:` and `nut:` entries have none of them.
```

In `README.md`, extend the manifest field list sentence with "`room` (LA1 rooms and objects), `x`, `y` (LA1 objects)".

- [ ] **Step 6: Commit**

```bash
git add thedig-textures-exporter
git commit -m "feat(exporter): record each LA1 bitmap's room and each object's position

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 7: Re-extract LA1 and check the placement semantics (manual, needs the game)**

The GOG bundle is on the Mac (`~/Documents/The Dig®.app`). On a host that has it:

```bash
cd thedig-textures-exporter && make install
.venv/bin/thedig-textures extract --only la1 --out out
```

Copy `out/` to `~/code/thedig-hd-bundle/thedig-textures-exporter/out` on the GB10 if extracted elsewhere. Then run this check there (Pillow only):

```bash
cd ~/code/thedig-hd-bundle/thedig-textures-exporter && .venv/bin/python - <<'EOF'
import json
from pathlib import Path
from PIL import Image, ImageChops
out = Path("out"); doc = json.loads((out / "manifest.json").read_text())
assert doc["tool_version"] == "0.2.0", doc["tool_version"]
rooms = {a["room"]: a for a in doc["assets"] if (a["name"] or "").startswith("room")}
inside = identical = 0; outside = []
for a in doc["assets"]:
    if not (a["name"] or "").startswith("obj"):
        continue
    r = rooms.get(a["room"])
    if (r is None or a["x"] < 0 or a["y"] < 0 or a["x"] + a["width"] > r["width"]
            or a["y"] + a["height"] > r["height"]):
        outside.append(a["name"]); continue
    inside += 1
    obj = Image.open(out / a["path"]).convert("RGBA")
    box = (a["x"], a["y"], a["x"] + a["width"], a["y"] + a["height"])
    under = Image.open(out / r["path"]).convert("RGB").crop(box)
    diff = ImageChops.difference(obj.convert("RGB"), under).convert("L").point(lambda v: 255 if v else 0)
    if not ImageChops.multiply(diff, obj.getchannel("A")).getbbox():
        identical += 1
print(f"objects inside {inside}, identical {identical}, outside {len(outside)}: {outside[:20]}")
EOF
```

Expected: 111 rooms and 642 objects in the manifest; `identical` well above 0. An `identical` count of 0 means the IMHD position is not the draw position: stop and report to the user before Task 4. Record the three numbers for `NOTES.md` (Task 9).

---

### Task 3: Fork the Atlantis kit

**Files:**
- Create: `thedig-texture-enhancement/` with copies of the Atlantis kit's modules, tests, graphs, Makefile, scripts, `pyproject.toml`, `.gitignore`; `atl_recreate.py` → `dig_recreate.py`, `test_atl_recreate.py` → `test_dig_recreate.py`.

**Interfaces:**
- Produces: the Atlantis behaviour under Dig names: module `dig_recreate`, env prefix `DIG_`, `comfy_client.OUTPUT_PREFIX == "dig"`, staged inputs `__dig_<name>_<part>.png`, default source `../thedig-textures-exporter/out`. Tests still run on Atlantis-shaped (P-mode) fixtures; Task 4 switches them.

- [ ] **Step 1: Copy and rename**

```bash
cd ~/code/thedig-hd-bundle && mkdir thedig-texture-enhancement && cd thedig-texture-enhancement
A=~/code/atlantis-hd-bundle/atlantis-texture-enhancement
cp $A/{colour_match,comfy_client,geometry_check,prompts,room_geometry,rooms_file,source_tree,testkit}.py .
cp $A/test_{colour_match,comfy_client,geometry_check,prompts,room_geometry,rooms_file,source_tree,scripts}.py .
cp $A/atl_recreate.py dig_recreate.py && cp $A/test_atl_recreate.py test_dig_recreate.py
cp $A/recreation_qwen21_i2i.json $A/recreation_qwen2511_canny.json $A/Makefile $A/run_batch.sh $A/run_server.sh $A/pyproject.toml $A/.gitignore .
sed -i -e 's/atl_recreate/dig_recreate/g' -e 's/ATL_/DIG_/g' -e 's/__atl_/__dig_/g' \
       -e 's#"atl"#"dig"#g' -e 's#"atl/#"dig/#g' -e 's#output/atl/#output/dig/#g' \
       -e 's/atlantis-textures-exporter/thedig-textures-exporter/g' *.py Makefile run_batch.sh
sed -i -e 's/Atlantis Background Regen/The Dig Background Regen/' -e 's/the Atlantis background/The Dig background/' Makefile
sed -i -e 's/the Atlantis regeneration driver/The Dig regeneration driver/' run_batch.sh
sed -i -e 's/^name = "atlantis_regen"/name = "thedig_regen"/' \
       -e 's/^description = .*/description = "Caption, render and review high-definition 4x recreations of The Dig room backgrounds and room objects with ComfyUI (Qwen-Image) and a local Qwen3.8 VLM"/' pyproject.toml
grep -rn "atl\b\|__atl\|ATL_" --include=*.py --include=Makefile --include=*.sh . ; echo "grep exit $?"
```

Expected: the final grep prints nothing (`grep exit 1`).

- [ ] **Step 2: Remove the Atlantis real-corpus tests**

They would read the Dig manifest at the new default path. Delete:
- in `testkit.py`: `REAL_SRC`, `REAL_SKIP_ROOMS`, `needs_real_corpus`, `real_rooms` and their comment (Task 4 re-adds Dig versions);
- in `test_room_geometry.py`: the `@testkit.needs_real_corpus` decorator and `class RealCorpusTests` up to the line before the next `class`;
- in `test_dig_recreate.py`: from `@testkit.needs_real_corpus` to the `if __name__ == "__main__":` block (keep that block).

- [ ] **Step 3: Run the suite**

Run: `make install && make check && make test`
Expected: `check ok`, all tests pass.

- [ ] **Step 4: Commit**

```bash
cd ~/code/thedig-hd-bundle
git add thedig-texture-enhancement
git commit -m "feat(kit): fork the Atlantis kit as thedig-texture-enhancement

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Read the Dig manifest (rooms, objects, colour keys)

**Files:**
- Rewrite: `thedig-texture-enhancement/source_tree.py`
- Modify: `thedig-texture-enhancement/testkit.py` (source builders), `room_geometry.py` (colour keys instead of indices), `dig_recreate.py` (open_rgba)
- Rewrite: `thedig-texture-enhancement/test_source_tree.py`
- Modify: `test_room_geometry.py` (fixture images)

**Interfaces:**
- Produces (source_tree): `SCALE = 4`, `TRANSPARENT_KEY = 0xFFFFFFFF`, `SourceError`, `Room(number, rel, width, height, has_alpha)` with `.key` (`room_NNN`), `.out_name`, `.out_size`, `.mode`; `Obj(key, room, rel, x, y, width, height, has_alpha, placement_error=None)` with `.out_name`, `.out_size`, `.mode`, `.room_key`, `.box`; `Source(root, rooms, objects)`; `load(root) -> Source`; `select(source, numbers) -> list[Room]`; `select_objects(source, keys) -> list[Obj]`; `objects_of(source, numbers) -> list[Obj]`; `open_rgba(root, asset) -> Image (RGBA)`; `colour_keys(image) -> np.ndarray (h, w) uint32`; `file_sha256(path) -> str`.
- Produces (testkit): `room(number, width, height, *, seed=None, wrap=None, right_margin=0, flat=None, alpha_rows=0, rgba=False)`, `obj(key, room, x, y, width, height, *, seed=None, identical=False, alpha=False)`, `DEFAULT_ROOMS`, `DEFAULT_OBJECTS`, `room_pixels(spec)`, `to_image(pixels, alpha=None)`, `room_image(spec)`, `make_source(root, rooms=DEFAULT_ROOMS, objects=DEFAULT_OBJECTS, tool_version="0.2.0") -> Path`, `rewrite_manifest(src, change)`, `REAL_SRC`, `needs_real_corpus`, `real_rooms()`, `REAL_SKIP_ROOMS`.
- Produces (room_geometry): `build_guide(image, method)`, `plan_room(image)`, `apply_fixups(image, plan, source)` take the RGBA source image; `indices` and `to_rgb` are gone.

- [ ] **Step 1: Rewrite testkit's source builders**

Replace `testkit.py` from its module docstring through `rewrite_manifest` (keep `write_rooms`, `run_cli`, `vlm_stub`, `shift_right`, `fake_render`, `comfy_stub` as they are) with:

```python
"""Shared test support: a miniature thedig-textures-exporter output, a rooms.yaml
writer, the ComfyUI and vLLM patch stacks, a fake window renderer, a
CLI-capture helper, and where the real corpus is.

The real source tree is thedig-textures-exporter's `out/`: la1/roomNNN.png and
la1/objNNN_SS.png, RGB or RGBA per the manifest's has_alpha, and manifest.json
(tool_version 0.2.0 or later: room on every la1: entry, x and y on objects).
"""

import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

import dig_recreate as a
import comfy_client
import source_tree
from rooms_file import RoomEntry, save_rooms

# The real corpus: thedig-textures-exporter's output, and the rooms the shipped
# rooms.yaml marks skip (one flat colour, line charts, a sprite sheet).
REAL_SRC = Path(os.environ.get("DIG_SRC")
                or Path(__file__).resolve().parent.parent / "thedig-textures-exporter" / "out")
REAL_SKIP_ROOMS = (1, 86, 88, 93, 103, 104)


def _real_corpus_loads():
    try:
        source_tree.load(REAL_SRC)
        return True
    except (source_tree.SourceError, OSError):
        return False


needs_real_corpus = unittest.skipUnless(
    (REAL_SRC / "manifest.json").is_file() and _real_corpus_loads(),
    "no loadable thedig-textures-exporter 0.2.0 output")


def real_rooms():
    """The real corpus's scene and insert rooms (source_tree.Room)."""
    return [room for room in source_tree.load(REAL_SRC).rooms
            if room.number not in REAL_SKIP_ROOMS]


# Indices 2-13 lie far apart (RGB distance over 64), so de-dithering keeps
# every block edge; index 0 is the margin and transparent colour.
BASE = [(0, 0, 0), (255, 255, 255), (200, 40, 40), (40, 200, 40), (40, 40, 200),
        (200, 200, 40), (200, 40, 200), (40, 200, 200), (120, 60, 20), (20, 120, 60),
        (60, 20, 120), (230, 140, 60), (60, 140, 230), (140, 230, 60)]
PALETTE = BASE + [(i, i, i) for i in range(len(BASE), 256)]


def room(number, width, height, *, seed=None, wrap=None, right_margin=0, flat=None,
         alpha_rows=0, rgba=False):
    """A room for make_source: random 16-pixel blocks of indices 2-13 (seeded by
    `seed`, default the room number); `wrap=(period, span)` copies columns
    [0, span) onto [period, period + span); `right_margin` columns of index 0;
    `flat=I` makes the whole room index I; `alpha_rows` transparent rows at the
    top (index 0, alpha 0); `rgba` writes RGBA even with nothing transparent."""
    return {"room": number, "width": width, "height": height,
            "seed": number if seed is None else seed, "wrap": wrap,
            "right_margin": right_margin, "flat": flat, "alpha_rows": alpha_rows,
            "rgba": rgba or bool(alpha_rows)}


def obj(key, room_number, x, y, width, height, *, seed=None, identical=False, alpha=False):
    """An object image for make_source at (x, y) in room `room_number`:
    `identical` copies the room's pixels under it; otherwise random 4-pixel
    blocks of indices 2-13 seeded by `seed` (default: from the key). `alpha`
    makes its outer 2-pixel ring transparent."""
    return {"key": key, "room": room_number, "x": x, "y": y, "width": width,
            "height": height, "seed": seed, "identical": identical, "alpha": alpha}


DEFAULT_ROOMS = (
    room(1, 320, 144),                                          # one window
    room(2, 568, 144),                                          # two windows
    room(3, 1152, 144, wrap=(840, 224), right_margin=88),       # a wraparound
    room(4, 16, 200, flat=0),                                   # a placeholder (skip)
)

DEFAULT_OBJECTS = (
    obj("obj010_01", 1, 40, 24, 48, 32, identical=True),        # state 01 = the room beneath
    obj("obj010_02", 1, 40, 24, 48, 32),                        # state 02 differs: render
    obj("obj011_01", 1, 200, 60, 40, 40, alpha=True),           # a sprite with alpha
    obj("obj012_01", 4, 0, 0, 8, 8),                            # in a skip room: copy
    obj("obj013_01", 1, 300, 100, 40, 40),                      # sticks out of room 1
    obj("obj014_01", 2, 500, 16, 32, 24),                       # in the two-window room
)


def room_pixels(spec):
    """The room's palette indices, a (height, width) uint8 array."""
    h, w = spec["height"], spec["width"]
    if spec["flat"] is not None:
        return np.full((h, w), spec["flat"], np.uint8)
    rng = np.random.default_rng(spec["seed"])
    blocks = rng.integers(2, len(BASE), size=(-(-h // 16), -(-w // 16)), dtype=np.uint8)
    pixels = np.kron(blocks, np.ones((16, 16), np.uint8))[:h, :w].copy()
    if spec["wrap"]:
        period, span = spec["wrap"]
        pixels[:, period:period + span] = pixels[:, :span]
    if spec["right_margin"]:
        pixels[:, w - spec["right_margin"]:] = 0
    if spec["alpha_rows"]:
        pixels[:spec["alpha_rows"]] = 0
    return pixels


def room_alpha(spec):
    """(h, w) uint8 alpha of an RGBA room, or None for an RGB one."""
    if not spec["rgba"]:
        return None
    alpha = np.full((spec["height"], spec["width"]), 255, np.uint8)
    alpha[:spec["alpha_rows"]] = 0
    return alpha


def object_pixels(spec, rooms):
    h, w, x, y = spec["height"], spec["width"], spec["x"], spec["y"]
    if spec["identical"]:
        under = room_pixels(next(r for r in rooms if r["room"] == spec["room"]))
        return under[y:y + h, x:x + w].copy()
    seed = spec["seed"] if spec["seed"] is not None else sum(map(ord, spec["key"]))
    rng = np.random.default_rng(seed)
    blocks = rng.integers(2, len(BASE), size=(-(-h // 4), -(-w // 4)), dtype=np.uint8)
    return np.kron(blocks, np.ones((4, 4), np.uint8))[:h, :w].copy()


def object_alpha(spec):
    if not spec["alpha"]:
        return None
    alpha = np.zeros((spec["height"], spec["width"]), np.uint8)
    alpha[2:-2, 2:-2] = 255
    return alpha


def to_image(pixels, alpha=None):
    """An RGB image of palette indices `pixels`, RGBA with `alpha` when given;
    transparent pixels take index 0's colour, like the exporter writes them."""
    rgb = np.array(PALETTE, np.uint8)[pixels]
    if alpha is None:
        return Image.fromarray(rgb)
    rgb[alpha == 0] = PALETTE[0]
    return Image.fromarray(np.dstack([rgb, alpha]))


def room_image(spec):
    return to_image(room_pixels(spec), room_alpha(spec))


def _asset(name, width, height, has_alpha, **placement):
    return {"id": f"la1:{name}", "kind": "la1_bitmap", "source": "DIG.LA1", "frame": None,
            "name": name, "width": width, "height": height, "has_alpha": has_alpha,
            "palette": "0" * 64, "path": f"la1/{name}.png", **placement}


def make_source(root, rooms=DEFAULT_ROOMS, objects=DEFAULT_OBJECTS, tool_version="0.2.0"):
    """Write <root>/out like `thedig-textures extract --only la1` and return it."""
    src = Path(root) / "out"
    (src / "la1").mkdir(parents=True, exist_ok=True)
    assets = []
    for spec in rooms:
        name = f"room{spec['room']:03d}"
        room_image(spec).save(src / "la1" / f"{name}.png")
        assets.append(_asset(name, spec["width"], spec["height"], spec["rgba"],
                             room=spec["room"]))
    for spec in objects:
        to_image(object_pixels(spec, rooms), object_alpha(spec)).save(
            src / "la1" / f"{spec['key']}.png")
        assets.append(_asset(spec["key"], spec["width"], spec["height"], spec["alpha"],
                             room=spec["room"], x=spec["x"], y=spec["y"]))
    # Kinds the kit ignores, with no files behind them.
    assets.append({"id": "akos:costume001_000", "kind": "la1_bitmap", "source": "DIG.LA1",
                   "frame": None, "name": "costume001_000", "width": 8, "height": 11,
                   "has_alpha": True, "palette": "0" * 64, "path": "la1/costume001_000.png"})
    assets.append({"id": "san:sq1:00000", "kind": "san_frame", "source": "VIDEO/SQ1.SAN",
                   "frame": 0, "name": None, "width": 320, "height": 200, "has_alpha": False,
                   "palette": "0" * 64, "path": "san/SQ1/00000.png"})
    (src / "manifest.json").write_text(json.dumps(
        {"tool": "thedig-textures", "tool_version": tool_version,
         "extracted_at": "2026-09-25T00:00:00Z", "game_root": "0" * 64,
         "counts": {"san_frames": 1, "nut_images": 0, "la1_bitmaps": len(assets) - 1,
                    "errors": 0},
         "assets": assets}, indent=1))
    return src


def rewrite_manifest(src, change):
    """Load <src>/manifest.json, let change(assets) edit it in place, save it."""
    path = Path(src) / "manifest.json"
    doc = json.loads(path.read_text())
    change(doc["assets"])
    path.write_text(json.dumps(doc, indent=1))
```

Delete the old `indexed_image` helper and the `hashlib` import.

- [ ] **Step 2: Write the failing source_tree tests**

Replace `test_source_tree.py` with:

```python
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

import source_tree
import testkit
from source_tree import SourceError


class SourceTreeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.src = testkit.make_source(self.tmp)

    def test_loads_rooms_and_objects_and_ignores_other_kinds(self):
        source = source_tree.load(self.src)
        self.assertEqual([r.number for r in source.rooms], [1, 2, 3, 4])
        room = source.rooms[2]
        self.assertEqual((room.key, room.out_name, room.rel), ("room_003", "room_003.png",
                                                               Path("la1/room003.png")))
        self.assertEqual(((room.width, room.height), room.out_size, room.mode),
                         ((1152, 144), (4608, 576), "RGB"))
        self.assertEqual([o.key for o in source.objects],
                         ["obj010_01", "obj010_02", "obj011_01", "obj012_01", "obj013_01",
                          "obj014_01"])
        sprite = source.objects[2]
        self.assertEqual((sprite.room, sprite.room_key, sprite.box, sprite.mode,
                          sprite.out_name, sprite.out_size),
                         (1, "room_001", (200, 60, 240, 100), "RGBA", "obj011_01.png",
                          (160, 160)))
        self.assertIsNone(sprite.placement_error)

    def test_an_object_outside_its_room_loads_with_a_placement_error(self):
        testkit.rewrite_manifest(self.src, lambda assets: assets.append(
            dict(next(a for a in assets if a["name"] == "obj014_01"),
                 id="la1:obj099_01", name="obj099_01", room=77)))
        by_key = {o.key: o for o in source_tree.load(self.src).objects}
        self.assertRegex(by_key["obj013_01"].placement_error, r"not inside room_001 \(320x144\)")
        self.assertRegex(by_key["obj099_01"].placement_error, "room 77 is not in the manifest")

    def test_refuses_a_manifest_that_disagrees_with_its_files(self):
        def edit(field, value, name="room001"):
            def change(assets):
                next(a for a in assets if a.get("name") == name)[field] = value
            return change

        def drop(field, name):
            def change(assets):
                del next(a for a in assets if a.get("name") == name)[field]
            return change

        cases = {
            "missing file": (edit("path", "la1/room999.png"), "file not found"),
            "size": (edit("width", 336), "the manifest says 336x144"),
            "strips": (edit("width", 322), "multiple of 8"),
            "escaping path": (edit("path", "../x.png"), "relative path inside"),
            "room number": (edit("room", 2), "room001 must be room 1"),
            "mode": (edit("has_alpha", True), "mode RGB, expected RGBA"),
            "no placement": (drop("x", "obj010_01"), '"x" must be an integer'),
            "no room": (drop("room", "obj010_01"), '"room" must be a positive integer'),
            "odd name": (edit("name", "sprite7"), "unexpected la1 asset name"),
            "duplicate": (lambda assets: next(a for a in assets if a.get("name") == "room002")
                          .update(name="room001", room=1), "duplicate room 1"),
            "no rooms": (lambda assets: assets.clear(), "lists no rooms"),
        }
        for name, (change, message) in cases.items():
            with self.subTest(name):
                src = testkit.make_source(self.tmp / name)
                testkit.rewrite_manifest(src, change)
                with self.assertRaisesRegex(SourceError, message):
                    source_tree.load(src)

    def test_refuses_an_old_or_foreign_manifest(self):
        with self.subTest("0.1.0 has no placement"):
            src = testkit.make_source(self.tmp / "old", tool_version="0.1.0")
            with self.assertRaisesRegex(SourceError, "re-extract with thedig-textures >= 0.2.0"):
                source_tree.load(src)
        with self.subTest("unreadable image"):
            (self.src / "la1/room001.png").write_bytes(b"not a png")
            with self.assertRaisesRegex(SourceError, "not a readable image"):
                source_tree.load(self.src)
        with self.subTest("no manifest"):
            with self.assertRaisesRegex(SourceError, "not found"):
                source_tree.load(self.tmp / "nowhere")

    def test_selection(self):
        source = source_tree.load(self.src)
        self.assertEqual([r.number for r in source_tree.select(source, [3, 1, 3])], [1, 3])
        self.assertEqual(len(source_tree.select(source, None)), 4)
        with self.assertRaisesRegex(SourceError, "room 9"):
            source_tree.select(source, [9])
        self.assertEqual([o.key for o in source_tree.objects_of(source, [2, 4])],
                         ["obj012_01", "obj014_01"])
        self.assertEqual([o.key for o in source_tree.select_objects(source, ["obj014_01"])],
                         ["obj014_01"])
        with self.assertRaisesRegex(SourceError, "obj999_01"):
            source_tree.select_objects(source, ["obj999_01"])

    def test_images_and_colour_keys(self):
        source = source_tree.load(self.src)
        room = source_tree.open_rgba(self.src, source.rooms[0])
        self.assertEqual((room.mode, room.size), ("RGBA", (320, 144)))
        keys = source_tree.colour_keys(room)
        r, g, b = testkit.PALETTE[int(testkit.room_pixels(testkit.DEFAULT_ROOMS[0])[0, 0])]
        self.assertEqual(int(keys[0, 0]), (r << 16) | (g << 8) | b)
        sprite = source_tree.open_rgba(self.src, source.objects[2])
        sprite_keys = source_tree.colour_keys(sprite)
        self.assertTrue((sprite_keys[:2] == source_tree.TRANSPARENT_KEY).all())
        self.assertFalse((sprite_keys[2:-2, 2:-2] == source_tree.TRANSPARENT_KEY).any())


@testkit.needs_real_corpus
class RealCorpusTests(unittest.TestCase):
    def test_the_real_manifest(self):
        source = source_tree.load(testkit.REAL_SRC)
        self.assertEqual((len(source.rooms), len(source.objects)), (111, 642))
        rooms = {r.number: r for r in source.rooms}
        self.assertEqual((rooms[27].width, rooms[27].height), (512, 780))
        self.assertEqual({r.number for r in source.rooms if r.has_alpha}, {32, 34, 85, 88, 107})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest test_source_tree -v`
Expected: FAIL/ERROR (old `source_tree` wants P-mode rooms with `role`).

- [ ] **Step 4: Rewrite `source_tree.py`**

```python
"""Read and validate thedig-textures' manifest.json: which rooms and room
objects exist, their native sizes, their placement and their files.

The source tree is thedig-textures-exporter's output (`thedig-textures extract`):
la1/roomNNN.png and la1/objNNN_SS.png, RGB when the manifest's has_alpha is
false and RGBA when it is true, and manifest.json (tool_version 0.2.0 or later:
"room" on every la1: entry, "x" and "y" on every object). SAN, NUT and AKOS
entries are ignored. This module is its only reader. It never writes: DIG_SRC
is read in place.
"""
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

SCALE = 4                       # every output is exactly 4x its native size
TOOL = "thedig-textures"
MIN_TOOL_VERSION = (0, 2, 0)    # the first manifest with room, x and y
TRANSPARENT_KEY = 0xFFFFFFFF    # the colour key of a transparent pixel; no RGB colour has it
_ROOM_NAME = re.compile(r"^room(\d{3})$")
_OBJECT_NAME = re.compile(r"^obj\d{3,}_[0-9A-F]{2}$")


class SourceError(ValueError):
    """The source tree disagrees with its manifest, or a selection is not in it."""


@dataclass(frozen=True)
class Room:
    number: int
    rel: Path           # the PNG, relative to the source root
    width: int          # native size
    height: int
    has_alpha: bool

    @property
    def key(self):
        """The rooms.yaml and reviews.yaml key, audit folder and output name stem."""
        return f"room_{self.number:03d}"

    @property
    def out_name(self):
        return f"{self.key}.png"

    @property
    def out_size(self):
        return (self.width * SCALE, self.height * SCALE)

    @property
    def mode(self):
        return "RGBA" if self.has_alpha else "RGB"


@dataclass(frozen=True)
class Obj:
    key: str            # the manifest name, objNNN_SS: reviews key, audit folder, output stem
    room: int
    rel: Path
    x: int              # native room position of the top-left pixel (may be negative)
    y: int
    width: int
    height: int
    has_alpha: bool
    placement_error: str | None = None   # why it cannot be placed in its room; None when it can

    @property
    def room_key(self):
        return f"room_{self.room:03d}"

    @property
    def box(self):
        return (self.x, self.y, self.x + self.width, self.y + self.height)

    @property
    def out_name(self):
        return f"{self.key}.png"

    @property
    def out_size(self):
        return (self.width * SCALE, self.height * SCALE)

    @property
    def mode(self):
        return "RGBA" if self.has_alpha else "RGB"


@dataclass(frozen=True)
class Source:
    root: Path
    rooms: tuple        # of Room, by number
    objects: tuple      # of Obj, by key


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _version(text):
    try:
        return tuple(int(part) for part in str(text).split("."))
    except ValueError:
        return ()


def _int(record, field, where, minimum=None):
    value = record.get(field)
    if type(value) is not int or (minimum is not None and value < minimum):
        kind = "a positive integer" if minimum == 1 else "an integer"
        raise SourceError(f'{where}: "{field}" must be {kind}, got {value!r}')
    return value


def _checked_file(root, record, where, width, height, has_alpha):
    rel = record.get("path")
    if (not isinstance(rel, str) or not rel or rel.startswith("/")
            or ".." in Path(rel).parts):
        raise SourceError(f'{where}: "path" must be a relative path inside the source tree')
    path = root / rel
    if not path.is_file():
        raise SourceError(f"{where} ({rel}): file not found")
    try:
        with Image.open(path) as im:
            mode, size = im.mode, im.size
    except OSError as error:
        raise SourceError(f"{where} ({rel}): not a readable image: {error}") from error
    want = "RGBA" if has_alpha else "RGB"
    if mode != want:
        raise SourceError(f"{where} ({rel}): mode {mode}, expected {want}")
    if size != (width, height):
        raise SourceError(f"{where} ({rel}): is {size[0]}x{size[1]}, the manifest says "
                          f"{width}x{height}")
    return Path(rel)


def load(root):
    """Every room and room object the manifest lists, each checked against its file.

    An object whose room is missing or whose rectangle leaves its room loads
    with a placement_error; everything else wrong with the manifest raises.
    """
    root = Path(root)
    manifest = root / "manifest.json"
    if not manifest.is_file():
        raise SourceError(f"{manifest}: not found - run thedig-textures extract --only la1")
    try:
        doc = json.loads(manifest.read_text())
    except ValueError as error:
        raise SourceError(f"{manifest}: invalid JSON: {error}") from error
    if not isinstance(doc, dict) or doc.get("tool") != TOOL:
        raise SourceError(f'{manifest}: not a {TOOL} manifest')
    if _version(doc.get("tool_version")) < MIN_TOOL_VERSION:
        raise SourceError(f"{manifest}: tool_version {doc.get('tool_version')!r} has no object "
                          "placement - re-extract with thedig-textures >= 0.2.0")
    assets = doc.get("assets")
    if not isinstance(assets, list):
        raise SourceError(f'{manifest}: expected an "assets" list')
    rooms, objects = {}, {}
    for i, record in enumerate(assets):
        if (not isinstance(record, dict) or record.get("kind") != "la1_bitmap"
                or not str(record.get("id", "")).startswith("la1:")):
            continue
        where = f"{manifest}: assets[{i}]"
        name = record.get("name")
        width, height = _int(record, "width", where, 1), _int(record, "height", where, 1)
        has_alpha = record.get("has_alpha")
        if type(has_alpha) is not bool:
            raise SourceError(f'{where}: "has_alpha" must be true or false')
        number = _int(record, "room", where, 1)
        if isinstance(name, str) and (match := _ROOM_NAME.match(name)):
            if int(match.group(1)) != number:
                raise SourceError(f"{where}: {name} must be room {int(match.group(1))}, "
                                  f"the manifest says {number}")
            if width % 8:
                # SMAP images are built from 8-pixel strips; every window width relies on it.
                raise SourceError(f'{where}: "width" must be a multiple of 8, got {width}')
            if number in rooms:
                raise SourceError(f"{where}: duplicate room {number}")
            rel = _checked_file(root, record, where, width, height, has_alpha)
            rooms[number] = Room(number, rel, width, height, has_alpha)
        elif isinstance(name, str) and _OBJECT_NAME.match(name):
            x, y = _int(record, "x", where), _int(record, "y", where)
            if name in objects:
                raise SourceError(f"{where}: duplicate object {name}")
            rel = _checked_file(root, record, where, width, height, has_alpha)
            objects[name] = Obj(name, number, rel, x, y, width, height, has_alpha)
        else:
            raise SourceError(f"{where}: unexpected la1 asset name {name!r}")
    if not rooms:
        raise SourceError(f"{manifest}: lists no rooms")
    placed = []
    for key in sorted(objects):
        o = objects[key]
        room = rooms.get(o.room)
        error = None
        if room is None:
            error = f"room {o.room} is not in the manifest"
        elif o.x < 0 or o.y < 0 or o.x + o.width > room.width or o.y + o.height > room.height:
            error = (f"{o.x},{o.y} {o.width}x{o.height} is not inside {room.key} "
                     f"({room.width}x{room.height})")
        placed.append(Obj(o.key, o.room, o.rel, o.x, o.y, o.width, o.height, o.has_alpha,
                          error))
    return Source(root, tuple(rooms[n] for n in sorted(rooms)), tuple(placed))


def select(source, numbers=None):
    """The rooms `numbers` names, by number; every room when it is empty or None."""
    if not numbers:
        return list(source.rooms)
    by_number = {room.number: room for room in source.rooms}
    unknown = sorted({n for n in numbers if n not in by_number})
    if unknown:
        raise SourceError("not in the manifest: room " + ", ".join(map(str, unknown)))
    return [by_number[n] for n in sorted(set(numbers))]


def select_objects(source, keys):
    """The objects `keys` names, by key."""
    by_key = {o.key: o for o in source.objects}
    unknown = sorted({k for k in keys if k not in by_key})
    if unknown:
        raise SourceError("not in the manifest: " + ", ".join(unknown))
    return [by_key[k] for k in sorted(set(keys))]


def objects_of(source, numbers):
    """The objects of the rooms `numbers`, by key."""
    wanted = set(numbers)
    return [o for o in source.objects if o.room in wanted]


def open_rgba(root, asset):
    """The asset's image, loaded, as RGBA (alpha 255 everywhere for an RGB file)."""
    with Image.open(Path(root) / asset.rel) as im:
        return im.convert("RGBA")


def colour_keys(image):
    """(h, w) uint32 R<<16 | G<<8 | B of each pixel; TRANSPARENT_KEY where alpha is 0."""
    a = np.asarray(image.convert("RGBA"), dtype=np.uint32)
    keys = (a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]
    keys[a[..., 3] == 0] = TRANSPARENT_KEY
    return keys
```

- [ ] **Step 5: Switch room_geometry to colour keys**

In `room_geometry.py`: change `from source_tree import SCALE` to `from source_tree import SCALE, colour_keys`; delete `indices` and `to_rgb`; then

```python
def build_guide(image, method=DEDITHER_METHOD):
    native = dedither(image.convert("RGB"), method)
    full = native.resize((native.width * SCALE, native.height * SCALE),
                         Image.Resampling.LANCZOS)
    return Guide(native, full)
```

In `plan_room(image)` replace `pixels = indices(indexed)` with `pixels = colour_keys(image)`. In `apply_fixups(image, plan, source)` rename the third parameter and use `flat = source.convert("RGB").resize(out.size, Image.Resampling.NEAREST)` and `w, rows = source.width, source.height`. In the `Margins` comment and `_flat_run` docstring, "palette index" becomes "colour".

In `test_room_geometry.py`: `fixture_room` returns `testkit.room_image(spec)`; replace every `testkit.indexed_image(pixels)` with `testkit.to_image(pixels)`; delete `test_to_rgb_uses_the_exact_palette`; rename local variables `indexed` to `image`.

- [ ] **Step 6: Switch the driver to RGBA sources**

In `dig_recreate.py` replace every `source_tree.open_indexed(` with `source_tree.open_rgba(` and rename the variables `indexed` → `image` (`caption_images`, `finish_room`, `render_room`, `write_nearest`, `plan_line`, `review_images`). In `caption_images`, `rgb = image.convert("RGB")`. Update the module docstring's source sentence to "The source tree is thedig-textures-exporter's output; its manifest.json (read by source_tree) decides which rooms and objects exist." and the `--src` help to `"thedig-textures-exporter output: manifest.json and la1/ (default: %(default)s, or DIG_SRC)"`.

- [ ] **Step 7: Run everything**

Run: `make check && make test`
Expected: PASS (the real-corpus class skips until Task 2 Step 7's `out/` exists; with it, it passes).

- [ ] **Step 8: Commit**

```bash
git add thedig-texture-enhancement
git commit -m "feat(kit): read the Dig manifest: rooms, objects, placement, colour keys

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: 2D window plan with padded heights

**Files:**
- Modify: `thedig-texture-enhancement/room_geometry.py` (constants, `Window`, `plan_axis`, `RoomPlan`, `plan_room`, `pad_rows`, `build_guide`)
- Test: `thedig-texture-enhancement/test_room_geometry.py`

**Interfaces:**
- Produces: `WINDOW_HEIGHT = 240`, `ALIGN = 8`; `Window(x0, x1, y0, y1)` with `.width`, `.height`, `.box -> (x0, y0, x1, y1)`, `.box4 -> 4x box`; `plan_axis(start, end, size) -> tuple[(a, b), ...]`; `RoomPlan(margins, wrap, span, rows, windows, height)` where `span=(x0, x1)`, `rows=(y0, y1)`, `windows` row by row, `height` = the room height rounded up to `ALIGN`; `pad_rows(image, height) -> Image`; `build_guide` returns `Guide(native, full)` with `native` unpadded and `full` = the padded native upscaled 4x. `plan_windows` is removed.

- [ ] **Step 1: Write the failing tests**

In `test_room_geometry.py` add `def boxes(windows): return [w.box for w in windows]` and replace `WindowPlanTests` with:

```python
class WindowPlanTests(unittest.TestCase):
    def test_known_plans(self):
        cases = {
            (0, 320, 320): [(0, 320)],
            (64, 240, 320): [(64, 240)],
            (0, 568, 320): [(0, 320), (248, 568)],
            (0, 840, 320): [(0, 320), (168, 488), (344, 664), (520, 840)],
            (0, 232, 240): [(0, 232)],
            (0, 400, 240): [(0, 240), (160, 400)],
            (0, 472, 240): [(0, 240), (112, 352), (232, 472)],
            (0, 784, 240): [(0, 240), (136, 376), (272, 512), (408, 648), (544, 784)],
        }
        for (start, end, size), expected in cases.items():
            with self.subTest(span=(start, end, size)):
                self.assertEqual(list(rg.plan_axis(start, end, size)), expected)

    def test_rules_hold_on_both_axes(self):
        for size in (rg.WINDOW_HEIGHT, rg.WINDOW_WIDTH):
            for end in range(size + 8, 2000, 8):
                with self.subTest(size=size, end=end):
                    spans = rg.plan_axis(0, end, size)
                    self.assertEqual((spans[0][0], spans[-1][1]), (0, end))
                    for a, b in spans:
                        self.assertEqual((b - a, a % 8), (size, 0))
                    for (a0, a1), (b0, _) in zip(spans, spans[1:]):
                        self.assertGreaterEqual(a1 - b0, rg.WINDOW_OVERLAP)
                        self.assertLess(a0, b0)
```

In `RoomPlanTests` change `spans(x.windows)` assertions to `boxes(...)`: one-window room `[(0, 0, 320, 144)]`; two-window room `[(0, 0, 320, 144), (248, 0, 568, 144)]`; margins test expects `plan.span == (64, 240)` and `boxes(plan.windows) == [(64, 0, 240, 200)]`. Leave the `stitch_boundaries` assertions for Task 6. Add:

```python
    def test_a_tall_room_is_padded_and_planned_in_rows(self):
        plan = rg.plan_room(testkit.to_image(testkit.room_pixels(testkit.room(9, 352, 470))))
        self.assertEqual((plan.height, plan.span, plan.rows), (472, (0, 352), (0, 472)))
        self.assertEqual(boxes(plan.windows),
                         [(0, 0, 320, 240), (32, 0, 352, 240),
                          (0, 112, 320, 352), (32, 112, 352, 352),
                          (0, 232, 320, 472), (32, 232, 352, 472)])
        for win in plan.windows:
            self.assertEqual((win.width * 4 % 32, win.height * 4 % 32), (0, 0))

    def test_top_and_bottom_margins_trim_the_rows(self):
        pixels = testkit.room_pixels(testkit.room(9, 320, 144))
        pixels[:28], pixels[-26:] = 0, 0
        plan = rg.plan_room(testkit.to_image(pixels))
        self.assertEqual((plan.margins.top, plan.margins.bottom, plan.rows), (28, 26, (24, 120)))

    def test_a_wraparound_taller_than_one_window_row_is_refused(self):
        spec = testkit.room(9, 1152, 480, wrap=(840, 224))
        with self.assertRaisesRegex(ValueError, "taller than one window row"):
            rg.plan_room(testkit.to_image(testkit.room_pixels(spec)))
```

In `GuideTests` add:

```python
    def test_the_guide_is_padded_to_whole_strips(self):
        image = testkit.to_image(testkit.room_pixels(testkit.room(9, 352, 230)))
        guide = rg.build_guide(image)
        self.assertEqual((guide.native.size, guide.full.size), ((352, 230), (1408, 928)))
        padded = rg.pad_rows(image.convert("RGB"), 232)
        last = np.asarray(image.convert("RGB"))[-1]
        self.assertTrue((np.asarray(padded)[230:] == last).all())
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m unittest test_room_geometry -v`
Expected: FAIL/ERROR (`plan_axis`, `pad_rows`, `WINDOW_HEIGHT` missing).

- [ ] **Step 3: Implement**

In `room_geometry.py`:

```python
WINDOW_WIDTH = 320          # the widest window, native columns
WINDOW_HEIGHT = 240         # the tallest window, native rows (the spike checks it)
WINDOW_OVERLAP = 64         # the least overlap between neighbouring windows, on each axis
ALIGN = 8                   # window edges and the padded canvas height, native px
```

```python
def pad_rows(image, height):
    """`image` with its last row repeated down to `height` rows (a copy when it is tall enough)."""
    if image.height >= height:
        return image.copy()
    out = Image.new(image.mode, (image.width, height))
    out.paste(image, (0, 0))
    last = image.crop((0, image.height - 1, image.width, image.height))
    out.paste(last.resize((image.width, height - image.height)), (0, image.height))
    return out


@dataclass(frozen=True)
class Guide:
    native: Image.Image     # de-dithered at native size: what the geometry check compares with
    full: Image.Image       # native padded to ALIGN rows, upscaled 4x (Lanczos)


def build_guide(image, method=DEDITHER_METHOD):
    native = dedither(image.convert("RGB"), method)
    padded = pad_rows(native, ALIGN * math.ceil(native.height / ALIGN))
    full = padded.resize((padded.width * SCALE, padded.height * SCALE),
                         Image.Resampling.LANCZOS)
    return Guide(native, full)
```

```python
@dataclass(frozen=True)
class Window:
    x0: int                 # native columns [x0, x1) and rows [y0, y1)
    x1: int
    y0: int
    y1: int

    @property
    def width(self):
        return self.x1 - self.x0

    @property
    def height(self):
        return self.y1 - self.y0

    @property
    def box(self):
        return (self.x0, self.y0, self.x1, self.y1)

    @property
    def box4(self):
        return tuple(v * SCALE for v in self.box)


def plan_axis(start, end, size):
    """Spans (a, b) over [start, end): at most `size` long, neighbours overlapping
    by at least WINDOW_OVERLAP, each start `start` plus a multiple of ALIGN, the
    first at `start` and the last flush with `end`."""
    overlap = WINDOW_OVERLAP
    span = end - start
    if span <= size:
        return ((start, end),)
    n = math.ceil((span - overlap) / (size - overlap))
    while True:
        step = (span - size) / (n - 1)
        starts = [start + ALIGN * math.floor(i * step / ALIGN) for i in range(n - 1)] + [end - size]
        if all(a + size - b >= overlap for a, b in zip(starts, starts[1:])):
            return tuple((s, s + size) for s in starts)
        n += 1


@dataclass(frozen=True)
class RoomPlan:
    margins: Margins
    wrap: Wrap | None
    span: tuple             # (x0, x1): the native columns the windows cover
    rows: tuple             # (y0, y1): the native rows the windows cover, within `height`
    windows: tuple          # of Window, row by row, left to right
    height: int             # the canvas height: the room's rows rounded up to ALIGN


def plan_room(image):
    """Margins, wraparound and windows of one room.

    Both spans skip whole margin lines, rounded out to ALIGN, so every window's
    4x size is a multiple of 32; the rows may run into the padding below the
    room. A wraparound room's span ends at its period and it has one window
    row. Raises ValueError for a room with nothing to render.
    """
    pixels = colour_keys(image)
    h, w = pixels.shape
    margins = blank_margins(pixels)
    if margins.left >= w:
        raise ValueError("the room is one flat colour: nothing to render (set kind: skip)")
    content_end = w - margins.right
    wrap = find_wrap(pixels, content_end)
    if wrap and wrap.period < WINDOW_WIDTH:
        raise ValueError(f"the wraparound period {wrap.period} is narrower than one "
                         f"window ({WINDOW_WIDTH}); lower WINDOW_WIDTH")
    height = ALIGN * math.ceil(h / ALIGN)
    start = ALIGN * (margins.left // ALIGN)
    end = wrap.period if wrap else min(w, ALIGN * math.ceil(content_end / ALIGN))
    if wrap:
        if height > WINDOW_HEIGHT:
            raise ValueError(f"a wraparound room taller than one window row ({height} > "
                             f"{WINDOW_HEIGHT} rows) needs a design change")
        top, bottom = 0, height
    else:
        top = ALIGN * (margins.top // ALIGN)
        bottom = min(height, ALIGN * math.ceil((h - margins.bottom) / ALIGN))
    columns = plan_axis(start, end, WINDOW_WIDTH)
    rows = plan_axis(top, bottom, WINDOW_HEIGHT)
    windows = tuple(Window(x0, x1, y0, y1) for y0, y1 in rows for x0, x1 in columns)
    return RoomPlan(margins, wrap, (start, end), (top, bottom), windows, height)
```

Delete `plan_windows` and the multiple-of-8 width check at the end of the old `plan_room`.

- [ ] **Step 4: Run to verify the plan tests pass**

Run: `.venv/bin/python -m unittest test_room_geometry.WindowPlanTests test_room_geometry.RoomPlanTests test_room_geometry.GuideTests -v`
Expected: PASS. Then run `make test`: everything passes. `stitch_from`, `stitch_boundaries`, `window_inputs` and `paste_window` stay as they are until Task 6, and the driver keeps working because every driver fixture room is one full-height row (no padding, no row margins), so `Window.x0/x1` and the full-height guide mean what they meant.

- [ ] **Step 5: Commit**

```bash
git add thedig-texture-enhancement
git commit -m "feat(kit): plan rooms as a 2D window grid over a padded canvas

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: 2D composites, stitch, seams and the driver's render loop

**Files:**
- Modify: `thedig-texture-enhancement/room_geometry.py` (`neighbours`, `stitch_origin`, `window_inputs`, `paste_window`, `Boundaries`, `stitch_boundaries`, `_mask_row` reused)
- Modify: `thedig-texture-enhancement/geometry_check.py` (`check` with boxes and row seams)
- Modify: `thedig-texture-enhancement/prompts.py` (`window_note`)
- Modify: `thedig-texture-enhancement/dig_recreate.py` (`caption_images`, `finish_room`, `render_room`, `plan_line`, `review_images`)
- Test: `test_room_geometry.py`, `test_geometry_check.py`, `test_prompts.py`, `test_dig_recreate.py`

**Interfaces:**
- Consumes: Task 5's `Window`, `RoomPlan`, `Guide`.
- Produces: `neighbours(plan, index) -> (left | None, up | None)`; `stitch_origin(window, left, up) -> (x, y)`; `window_inputs(guide_full, canvas, window, left, up) -> (crop, composite, mask)`; `paste_window(canvas, window, left, up, rendered)`; `Boundaries(columns: list[int], rows: list[int])` (4x); `stitch_boundaries(plan) -> Boundaries`; `geometry_check.check(render, source, windows=(), boundaries=(), reference=None, rows=())` where `windows` are native `(x0, y0, x1, y1)` boxes and `rows` are 4x row boundaries; `prompts.window_note(box, area) -> str`; `dig_recreate.finish_room(canvas, guide, plan, image, strength) -> (final, result, boundaries)` with `final` exactly `(4w, 4h)`.

- [ ] **Step 1: Write the failing tests**

`test_room_geometry.py` — in `RoomPlanTests.test_fixture_rooms`, change the three boundary assertions to `rg.stitch_boundaries(one) == rg.Boundaries([], [])`, `rg.stitch_boundaries(two).columns == [1136]`, `rg.stitch_boundaries(wrap).columns == [320, 976, 1664, 2368, 3040, 3360]`. Update the existing window-input tests' calls: `rg.window_inputs(guide, canvas, window, previous)` becomes `rg.window_inputs(guide, canvas, window, previous, None)` and `rg.paste_window(canvas, window, previous, rendered)` becomes `rg.paste_window(canvas, window, previous, None, rendered)`. Add:

```python
class GridTests(unittest.TestCase):
    def setUp(self):
        self.plan = rg.plan_room(testkit.to_image(testkit.room_pixels(testkit.room(9, 352, 470))))
        self.guide = noise((1408, 1888), seed=1)
        self.canvas = noise((1408, 1888), seed=2)

    def test_neighbours_and_boundaries(self):
        w = self.plan.windows
        self.assertEqual(rg.neighbours(self.plan, 0), (None, None))
        self.assertEqual(rg.neighbours(self.plan, 1), (w[0], None))
        self.assertEqual(rg.neighbours(self.plan, 3), (w[2], w[1]))
        self.assertEqual(rg.stitch_origin(w[3], w[2], w[1]), (176, 176))
        self.assertEqual(rg.stitch_boundaries(self.plan), rg.Boundaries([704], [704, 1168]))

    def test_an_inner_window_keeps_an_l_of_what_is_painted(self):
        w = self.plan.windows
        crop, composite, mask = rg.window_inputs(self.guide, self.canvas, w[3], w[2], w[1])
        self.assertEqual(crop.size, (1280, 960))
        m = np.asarray(mask)
        self.assertEqual((m[0, 0], m[0, -1], m[-1, 0], m[-1, -1]), (0, 0, 0, 255))
        c, canvas = np.asarray(composite), np.asarray(self.canvas)
        # overlap with the upper window: native rows 112-240, all columns of the window
        self.assertTrue((c[:512] == canvas[448:960, 128:1408]).all())
        # overlap with the left window: native columns 32-320, all rows of the window
        self.assertTrue((c[:, :1152] == canvas[448:1408, 128:1280]).all())

    def test_paste_starts_at_the_stitch_origin(self):
        w = self.plan.windows
        before = np.asarray(self.canvas).copy()
        rendered = noise((1280, 960), seed=3)
        rg.paste_window(self.canvas, w[3], w[2], w[1], rendered)
        after, r = np.asarray(self.canvas), np.asarray(rendered)
        self.assertTrue((after[704:1408, 704:1408] == r[256:, 576:]).all())
        self.assertTrue((after[:704] == before[:704]).all())
        self.assertTrue((after[:, :704] == before[:, :704]).all())
```

`test_geometry_check.py` — convert every `windows=[(x0, x1), ...]` argument to boxes `[(x0, 0, x1, <source height>), ...]`. Add:

```python
    def test_row_seams_and_a_lower_window_shift(self):
        source = noise_image((64, 64), seed=11)
        render = source.resize((256, 256), Image.Resampling.LANCZOS)
        with self.subTest("a horizontal seam"):
            arr = np.asarray(render).copy()
            arr[128:] = np.clip(arr[128:].astype(int) + 90, 0, 255).astype(np.uint8)
            result = gc.check(Image.fromarray(arr), source, rows=[128])
            self.assertGreater(result.seam_ratios[-1], gc.SEAM_WARN)
        with self.subTest("only the lower window slid"):
            arr = np.asarray(render).copy()
            arr[128:, 8:] = arr[128:, :-8]
            result = gc.check(Image.fromarray(arr), source,
                              windows=[(0, 0, 64, 32), (0, 32, 64, 64)])
            self.assertLess(abs(result.window_shifts[0][0]), gc.MAX_SHIFT)
            self.assertGreaterEqual(abs(result.window_shifts[1][0]), gc.MAX_SHIFT)
```

(If the module has no `noise_image` helper, add `def noise_image(size, seed): rng = np.random.default_rng(seed); w, h = size; return Image.fromarray(rng.integers(0, 256, (h, w, 3), dtype=np.uint8))` at the top, smoothed with `.filter(ImageFilter.GaussianBlur(1))` so Lanczos keeps its edges.)

`test_prompts.py` — replace the `window_note` line of `test_window_note_and_corrections` with:

```python
        note = p.window_note((248, 0, 568, 144), (0, 0, 568, 144))
        self.assertIn("from 44% to 100% of the room's width", note)
        self.assertNotIn("height", note)
        tall = p.window_note((32, 112, 352, 352), (0, 0, 352, 472))
        self.assertIn("from 9% to 100% of the room's width and from 24% to 75% of its height",
                      tall)
```

`test_dig_recreate.py` — in `RenderRoomTests.test_a_one_window_room` expect `record["windows"] == [[0, 0, 320, 144]]` and `assertNotIn("one window of a large room", ...)`. Add to `DriverFixture`:

```python
    def use_rooms(self, rooms, objects=()):
        """Swap in a source tree holding `rooms` and `objects`, and a rooms.yaml for them."""
        self.src = testkit.make_source(self.root / "alt", rooms=rooms, objects=objects)
        self.source = source_tree.load(self.src)
        testkit.write_rooms(self.rooms_file, rooms=rooms)
```

and to `RenderRoomTests`:

```python
    def test_a_tall_room_renders_in_a_grid_and_keeps_its_size(self):
        self.use_rooms((testkit.room(5, 352, 470),))
        self.entries = load_rooms(self.rooms_file)
        (_, result), stub = self.render(5)
        self.assertTrue(result.passed, result.issues)
        self.assertEqual(stub.render.call_count, 6)
        with Image.open(self.dst / "room_005.png") as im:
            self.assertEqual((im.size, im.mode), ((1408, 1880), "RGB"))
        record = self.record(5)
        self.assertEqual((record["windows"][3], record["padded_height"]), ([32, 112, 352, 352], 472))
        self.assertEqual(len(record["geometry"]["seam_ratios"]), 3)
```

- [ ] **Step 2: Run to verify failure**

Run: `make test`
Expected: FAIL/ERROR in the new tests (`neighbours`, `Boundaries`, `rows=` unknown).

- [ ] **Step 3: Implement room_geometry**

Replace `stitch_from`, `stitch_boundaries`, `_mask`, `window_inputs` and `paste_window` with:

```python
def neighbours(plan, index):
    """(left, up): the windows before plan.windows[index] in its row and in its
    column, or None. The windows are a grid in row order."""
    win = plan.windows[index]
    left = up = None
    for other in plan.windows[:index]:
        if other.y0 == win.y0 and other.x0 < win.x0:
            left = other
        if other.x0 == win.x0 and other.y0 < win.y0:
            up = other
    return left, up


def stitch_origin(window, left, up):
    """The native (x, y) from which `window`'s render replaces the stitch: the
    middle of its overlap with each neighbour, or its own edge where it has none."""
    x = window.x0 if left is None else window.x0 + (left.x1 - window.x0) // 2
    y = window.y0 if up is None else window.y0 + (up.y1 - window.y0) // 2
    return x, y


@dataclass(frozen=True)
class Boundaries:
    columns: list           # 4x columns where the stitch switches renders (and the wrap's joins)
    rows: list              # 4x rows where it does


def stitch_boundaries(plan):
    xs, ys = set(), set()
    for k, win in enumerate(plan.windows):
        left, up = neighbours(plan, k)
        x, y = stitch_origin(win, left, up)
        if left is not None:
            xs.add(x * SCALE)
        if up is not None:
            ys.add(y * SCALE)
    if plan.wrap:
        q, period = WINDOW_WIDTH // 4, plan.wrap.period
        xs |= {(period - q) * SCALE, q * SCALE, period * SCALE}
    return Boundaries(sorted(xs), sorted(ys))


def _full(n):
    return np.full(n, 255, np.uint8)


def window_inputs(guide, canvas, window, left, up):
    """(guide crop, composite, mask) for rendering `window`, all 4x.

    `guide` is the padded 4x guide and `canvas` the stitch so far. The composite
    is the guide crop with its overlaps with `left` and `up` taken from the
    canvas. The mask (255 paints, 0 keeps) is the minimum of a column ramp and a
    row ramp: each holds its overlap's outer half and ramps across its inner
    half, so the kept region is an L; a first window is painted whole.
    """
    box = window.box4
    crop = guide.crop(box)
    composite = crop.copy()
    w4, h4 = crop.size
    mask_x, mask_y = _full(w4), _full(h4)
    if left is not None:
        overlap = left.x1 - window.x0
        composite.paste(canvas.crop((box[0], box[1], left.x1 * SCALE, box[3])), (0, 0))
        mask_x = _mask_row(w4, (overlap // 2) * SCALE, overlap * SCALE)
    if up is not None:
        overlap = up.y1 - window.y0
        composite.paste(canvas.crop((box[0], box[1], box[2], up.y1 * SCALE)), (0, 0))
        mask_y = _mask_row(h4, (overlap // 2) * SCALE, overlap * SCALE)
    mask = np.minimum(mask_x[None, :], mask_y[:, None])
    return crop, composite, Image.fromarray(mask)


def paste_window(canvas, window, left, up, rendered):
    """Stitch `rendered`, the window's 4x render, into `canvas` from its stitch origin."""
    x, y = stitch_origin(window, left, up)
    ox, oy = (x - window.x0) * SCALE, (y - window.y0) * SCALE
    canvas.paste(rendered.crop((ox, oy, rendered.width, rendered.height)), (x * SCALE, y * SCALE))
```

`seam_inputs` keeps using `guide.height` (a wraparound room is one row of full padded height).

- [ ] **Step 4: Implement the 2D gate**

In `geometry_check.check`:

```python
def check(render, source, windows=(), boundaries=(), reference=None, rows=()):
    """Compare the 4x `render` with its de-dithered native `source` (both RGB).

    `windows` are native (x0, y0, x1, y1) boxes, clipped to the source.
    `boundaries` are 4x stitch columns and `rows` 4x stitch rows. A seam ratio is
    the render's step at a boundary over its local steps; with a 4x `reference`
    (the guide) it is divided by the reference's own ratio there, so a boundary
    that falls on a real edge of the source is not called a seam.
    """
```

In the window loops use `for k, (x0, y0, x1, y1) in enumerate(windows, 1):` with `base[y0:y1, x0:x1]` / `small[y0:y1, x0:x1]` / `strong[y0:y1, x0:x1]` / `kept[y0:y1, x0:x1]`. Replace the seam loop with:

```python
    ratios = []
    turned = render.transpose(Image.Transpose.TRANSPOSE)
    turned_ref = None if reference is None else reference.transpose(Image.Transpose.TRANSPOSE)
    for image, ref, positions in ((render, reference, boundaries), (turned, turned_ref, rows)):
        for x in positions:
            ratio = seam_ratio(image, x)
            if ref is not None:
                ratio = round(ratio / max(1.0, seam_ratio(ref, x)), 3)
            ratios.append(ratio)
```

and update the `GeometryResult.seam_ratios` comment to "per column boundary, then per row boundary; warnings only".

- [ ] **Step 5: Implement the window note**

In `prompts.py`:

```python
def window_note(box, area):
    """What one window of a large room is told about its place in the room:
    its native `box` (x0, y0, x1, y1) within the windows' `area`."""
    x0, y0, x1, y1 = box
    ax0, ay0, ax1, ay1 = area
    parts = []
    if (x0, x1) != (ax0, ax1):
        parts.append(f"from {(x0 - ax0) / (ax1 - ax0):.0%} to {(x1 - ax0) / (ax1 - ax0):.0%} "
                     "of the room's width")
    if (y0, y1) != (ay0, ay1):
        parts.append(f"from {(y0 - ay0) / (ay1 - ay0):.0%} to {(y1 - ay0) / (ay1 - ay0):.0%} "
                     "of its height")
    return ("This image is one window of a large room: it shows the part " + " and ".join(parts)
            + ". Paint only what this reference window shows; objects the observations place "
            "elsewhere in the room must not appear in it.")
```

- [ ] **Step 6: Wire the driver**

In `dig_recreate.py`:

```python
def caption_images(src, room):
    """What the VLM sees: the room at 2x, then each window at 4x when there are several."""
    image = source_tree.open_rgba(src, room)
    rgb = image.convert("RGB")
    images = [rgb.resize((rgb.width * 2, rgb.height * 2), Image.Resampling.NEAREST)]
    plan = room_geometry.plan_room(image)
    if len(plan.windows) > 1:
        for win in plan.windows:
            crop = rgb.crop((win.x0, win.y0, win.x1, min(win.y1, rgb.height)))
            images.append(crop.resize((crop.width * SCALE, crop.height * SCALE),
                                      Image.Resampling.NEAREST))
    return images


def finish_room(canvas, guide, plan, image, strength):
    """The stitched 4x `canvas`, cropped to the room's exact 4x size,
    colour-matched toward the guide by `strength`, fixed up, and checked against
    the de-dithered source: (final image, GeometryResult, Boundaries)."""
    if canvas.size != guide.full.size:
        raise RuntimeError(f"the stitched room is {canvas.width}x{canvas.height}, "
                           f"expected {guide.full.width}x{guide.full.height}")
    size = (image.width * SCALE, image.height * SCALE)
    reference = guide.full.crop((0, 0) + size)
    matched = colour_match.match(canvas.crop((0, 0) + size), reference, strength)
    final = room_geometry.apply_fixups(matched, plan, image)
    boundaries = room_geometry.stitch_boundaries(plan)
    result = geometry_check.check(final, guide.native, [w.box for w in plan.windows],
                                  boundaries.columns, reference=reference,
                                  rows=[y for y in boundaries.rows if y < size[1]])
    return final, result, boundaries
```

In `render_room`, replace the window loop with:

```python
        area = (plan.span[0], plan.rows[0], plan.span[1], plan.rows[1])
        for k, window in enumerate(plan.windows):
            left, up = room_geometry.neighbours(plan, k)
            crop, composite, mask = room_geometry.window_inputs(guide.full, canvas, window,
                                                                left, up)
            note = window_note(window.box, area) if len(plan.windows) > 1 else ""
            rendered = render(f"window-{k + 1}", crop, composite, mask, note)
            room_geometry.paste_window(canvas, window, left, up, rendered)
```

(delete the `start, end = plan.span` and `previous` lines), print seam warnings with labels:

```python
        seams = ([("column", x) for x in boundaries.columns]
                 + [("row", y) for y in boundaries.rows if y < image.height * SCALE])
        for (axis, at), ratio in zip(seams, result.seam_ratios):
            if ratio > geometry_check.SEAM_WARN:
                print(f"  warning: {room.key} seam at 4x {axis} {at}: step {ratio:.1f}x the "
                      "local texture", flush=True)
```

and in the record write `"window_height": room_geometry.WINDOW_HEIGHT`, `"windows": [list(w.box) for w in plan.windows]`, `"padded_height": plan.height` (keep the other fields).

`plan_line`: windows as `" ".join(label(w) for w in plan.windows)` where `label(w)` is `f"{w.x0}-{w.x1}"` when all windows share one row, else `f"{w.x0}-{w.x1}/{w.y0}-{w.y1}"`; add `f"padded to {plan.height} rows"` to `extras` when `plan.height != image.height`.

`review_images`: `box = (win.x0 * SCALE, win.y0 * SCALE, win.x1 * SCALE, min(win.y1 * SCALE, render.height))`.

- [ ] **Step 7: Run everything**

Run: `make check && make test`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add thedig-texture-enhancement
git commit -m "feat(kit): render rooms through a 2D window grid with L-shaped continuation

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Transparent rooms and RGBA outputs

**Files:**
- Modify: `room_geometry.py` (`fill_transparent`, `opaque_mask`, `with_alpha`, `build_guide`)
- Modify: `colour_match.py` (`match(..., mask=None)`, `lab_stats(image, mask=None)`)
- Modify: `geometry_check.py` (`check(..., opaque=None, min_edges=1)`)
- Modify: `dig_recreate.py` (`finish_room(..., has_alpha=False)`, `render_room`, `write_nearest`, `cmd_verify`, `alpha_matches`)
- Test: `test_room_geometry.py`, `test_colour_match.py`, `test_geometry_check.py`, `test_dig_recreate.py`

**Interfaces:**
- Produces: `room_geometry.fill_transparent(image) -> RGB Image`; `room_geometry.opaque_mask(image, scale=1) -> np.ndarray bool`; `room_geometry.with_alpha(image, source) -> RGBA Image`; `colour_match.match(render, guide, strength=1.0, mask=None)` (statistics over `mask` pixels, applied to every pixel); `geometry_check.check(..., opaque=None, min_edges=1)`; `dig_recreate.alpha_matches(path, source) -> bool`; `dig_recreate.finish_room(canvas, guide, plan, image, strength, has_alpha=False)`.

- [ ] **Step 1: Write the failing tests**

`test_room_geometry.py`:

```python
class AlphaTests(unittest.TestCase):
    def test_fill_transparent_takes_the_nearest_opaque_colour(self):
        a = np.zeros((1, 5, 4), np.uint8)
        a[0, 0] = (200, 0, 0, 255)
        a[0, 4] = (0, 0, 200, 255)
        out = np.asarray(rg.fill_transparent(Image.fromarray(a)))
        self.assertEqual([tuple(p) for p in out[0]],
                         [(200, 0, 0), (200, 0, 0), (100, 0, 100), (0, 0, 200), (0, 0, 200)])
        opaque = testkit.room_image(testkit.room(9, 32, 16))
        self.assertEqual(rg.fill_transparent(opaque).tobytes(), opaque.convert("RGB").tobytes())

    def test_with_alpha_scales_the_source_alpha_exactly(self):
        source = testkit.room_image(testkit.room(9, 32, 16, alpha_rows=5))
        out = rg.with_alpha(noise((128, 64), seed=4), source)
        alpha = np.asarray(out.getchannel("A"))
        self.assertEqual(out.mode, "RGBA")
        self.assertTrue((alpha[:20] == 0).all() and (alpha[20:] == 255).all())
        self.assertTrue((rg.opaque_mask(source, 4) == (alpha > 0)).all())
```

`test_colour_match.py`:

```python
    def test_a_mask_limits_the_statistics(self):
        arr = np.full((8, 16, 3), 50, np.uint8)
        arr[:, 8:] = 250                                  # outside the mask
        render = Image.fromarray(arr)
        guide = Image.new("RGB", (16, 8), (100, 100, 100))
        mask = np.zeros((8, 16), bool)
        mask[:, :8] = True
        inside = np.asarray(cm.match(render, guide, 1.0, mask=mask))[:, :8]
        self.assertTrue((np.abs(inside.astype(int) - 100) <= 1).all())
        unmasked = np.asarray(cm.match(render, guide, 1.0))[:, :8]
        self.assertTrue((np.abs(unmasked.astype(int) - 100) > 1).any())
```

`test_geometry_check.py`:

```python
    def test_transparent_pixels_do_not_count_as_lost_edges(self):
        source = Image.new("RGB", (32, 32), (40, 40, 40))
        source.paste((220, 220, 220), (0, 0, 32, 8))     # an edge along row 8
        render = Image.new("RGB", (128, 128), (40, 40, 40))  # the edge is gone
        opaque = np.ones((32, 32), bool)
        opaque[:12] = False                               # the edge lies in the transparent part
        self.assertLess(gc.check(render, source).edge_agreement, gc.MIN_EDGE_AGREEMENT)
        self.assertEqual(gc.check(render, source, opaque=opaque).edge_agreement, 1.0)
        self.assertEqual(gc.check(render, source, min_edges=10_000).edge_agreement, 1.0)
```

`test_dig_recreate.py`, in `RenderRoomTests`:

```python
    def test_transparent_rooms_keep_their_alpha(self):
        self.use_rooms((testkit.room(5, 320, 144, alpha_rows=40), testkit.room(6, 320, 144, rgba=True)))
        self.entries = load_rooms(self.rooms_file)
        for number, transparent_rows in ((5, 160), (6, 0)):   # room 32's case: RGBA, all opaque
            with self.subTest(room=number):
                (_, result), _ = self.render(number)
                self.assertTrue(result.passed, result.issues)
                path = self.dst / f"room_{number:03d}.png"
                with Image.open(path) as im:
                    self.assertEqual((im.size, im.mode), ((1280, 576), "RGBA"))
                    alpha = np.asarray(im.getchannel("A"))
                self.assertTrue((alpha[:transparent_rows] == 0).all())
                self.assertTrue((alpha[transparent_rows:] == 255).all())
                self.assertTrue(a.alpha_matches(path, source_tree.open_rgba(self.src, self.room(number))))
```

and in `VerifyTests`:

```python
    def test_alpha_and_mode_are_verified(self):
        self.use_rooms((testkit.room(5, 320, 144, alpha_rows=40),))
        with testkit.comfy_stub(comfy_dir=self.comfy_dir, render=testkit.fake_render()):
            self.assertEqual(self.run_cli("batch")[0], 0)
        self.assertEqual(self.run_cli("verify")[0], 0)
        path = self.dst / "room_005.png"
        record_path = self.dst / ".quality" / "room_005" / "attempt-1.json"
        for image, code in ((Image.new("RGBA", (1280, 576)), "WRONGALPHA"),
                            (Image.new("RGB", (1280, 576)), "WRONGMODE")):
            with self.subTest(code):
                image.save(path)
                record = json.loads(record_path.read_text())
                record["output_sha256"] = source_tree.file_sha256(path)   # only the pixels are wrong
                record_path.write_text(json.dumps(record))
                _, out, _ = self.run_cli("verify")
                self.assertIn(f"{code:10} room_005", out)
```

- [ ] **Step 2: Run to verify failure**

Run: `make test`
Expected: FAIL/ERROR (`fill_transparent`, `mask=`, `opaque=`, `alpha_matches` missing).

- [ ] **Step 3: Implement room_geometry**

```python
def fill_transparent(image):
    """`image` as RGB with every transparent pixel set to the mean of its nearest
    opaque 4-neighbours, filled outward ring by ring; an opaque image is returned
    as it is, and an image with no opaque pixel keeps its RGB."""
    a = np.asarray(image.convert("RGBA"))
    known = a[..., 3] > 0
    rgb = a[..., :3].astype(np.int64)
    if known.all() or not known.any():
        return Image.fromarray(a[..., :3].copy())
    h, w = known.shape
    while not known.all():
        pk = np.pad(known, 1)
        pr = np.pad(rgb, ((1, 1), (1, 1), (0, 0)))
        total = np.zeros_like(rgb)
        count = np.zeros((h, w), np.int64)
        for dy, dx in ((0, 1), (2, 1), (1, 0), (1, 2)):
            near = pk[dy:dy + h, dx:dx + w]
            total += pr[dy:dy + h, dx:dx + w] * near[..., None]
            count += near
        new = ~known & (count > 0)
        rgb[new] = total[new] // count[new][:, None]
        known = known | new
    return Image.fromarray(rgb.astype(np.uint8))


def opaque_mask(image, scale=1):
    """(h * scale, w * scale) bool: where `image` is opaque, scaled by nearest neighbour."""
    opaque = np.asarray(image.convert("RGBA"))[..., 3] > 0
    return np.kron(opaque, np.ones((scale, scale), bool)) if scale > 1 else opaque


def with_alpha(image, source):
    """The 4x `image` as RGBA, its alpha `source`'s alpha scaled up by nearest neighbour."""
    alpha = source.convert("RGBA").getchannel("A").resize(image.size, Image.Resampling.NEAREST)
    out = image.convert("RGB").convert("RGBA")
    out.putalpha(alpha)
    return out
```

and in `build_guide`: `native = dedither(fill_transparent(image), method)`.

- [ ] **Step 4: Implement the masked colour match**

In `colour_match.py`:

```python
def _stats(lab, mask=None):
    pixels = lab.reshape(-1, 3) if mask is None else lab[mask]
    return pixels.mean(axis=0), pixels.std(axis=0)


def lab_stats(image, mask=None):
    """(means, stds): three floats each, over the CIE L*, a*, b* bands, over the
    pixels `mask` (an (h, w) bool array) marks, or all of them."""
    means, stds = _stats(_to_lab(image), mask)
    return tuple(float(v) for v in means), tuple(float(v) for v in stds)


def match(render, guide, strength=1.0, mask=None):
    """The render shifted and scaled per Lab band toward `guide`'s mean and
    spread, blended by `strength`, with both images' statistics taken over the
    pixels `mask` marks (all when None) and the transfer applied to every pixel.
    Returns a new RGB image of the render's size; strength 0 returns the raw
    pixels unchanged (no Lab round trip)."""
    if strength == 0:
        return render.convert("RGB").copy()
    lab = _to_lab(render)
    means, stds = _stats(lab, mask)
    target_means, target_stds = lab_stats(guide, mask)
    # (keep the existing 1e-6 comment and the gain/moved/return lines unchanged)
```

- [ ] **Step 5: Implement the gate options**

In `geometry_check.check` add parameters `opaque=None, min_edges=1`. After `strong, kept = edge_maps(base, small)`:

```python
    if opaque is not None:
        strong, kept = strong & opaque, kept & opaque
    agreement = round(_fraction(strong, kept, min_edges), 4)
```

Docstring lines: "`opaque` (native bool) keeps transparent pixels out of edge agreement. `min_edges` is the least strong-edge count for the whole image to be judged (an object's context window passes MIN_WINDOW_EDGES)."

- [ ] **Step 6: Wire the driver**

```python
def alpha_matches(path, source):
    """True when the image at `path` is RGBA with `source`'s alpha scaled 4x nearest."""
    want = source.convert("RGBA").getchannel("A").resize(
        (source.width * SCALE, source.height * SCALE), Image.Resampling.NEAREST)
    with Image.open(path) as im:
        return im.mode == "RGBA" and im.getchannel("A").tobytes() == want.tobytes()
```

`finish_room` gains `has_alpha=False`:

```python
    opaque = room_geometry.opaque_mask(image)
    partial = not opaque.all()
    matched = colour_match.match(canvas.crop((0, 0) + size), reference, strength,
                                 mask=room_geometry.opaque_mask(image, SCALE) if partial else None)
    final = room_geometry.apply_fixups(matched, plan, image)
    boundaries = room_geometry.stitch_boundaries(plan)
    result = geometry_check.check(final, guide.native, [w.box for w in plan.windows],
                                  boundaries.columns, reference=reference,
                                  rows=[y for y in boundaries.rows if y < size[1]],
                                  opaque=opaque if partial else None)
    if has_alpha:
        final = room_geometry.with_alpha(final, image)
    return final, result, boundaries
```

`render_room` calls `finish_room(canvas, guide, plan, image, args.match_strength, room.has_alpha)`. `write_nearest` saves `source_tree.open_rgba(args.src, room).convert(room.mode).resize(room.out_size, Image.Resampling.NEAREST)`. In `cmd_verify`, compare `info[1] != room.mode` (detail `f"is {info[1]}, expected {room.mode}"`) and, before the `UNRECORDED` check, `elif room.has_alpha and not alpha_matches(dst, source_tree.open_rgba(args.src, room)): code, detail = "WRONGALPHA", "the alpha is not the source's, 4x nearest"`.

- [ ] **Step 7: Add the real-corpus gate test**

At the end of `test_dig_recreate.py`, before the `__main__` block:

```python
@testkit.needs_real_corpus
class RealCorpusTests(unittest.TestCase):
    def test_a_perfect_render_of_every_room_passes_the_gate(self):
        for room in testkit.real_rooms():
            with self.subTest(room=room.key):
                image = source_tree.open_rgba(testkit.REAL_SRC, room)
                guide = room_geometry.build_guide(image)
                plan = room_geometry.plan_room(image)
                final, result, _ = a.finish_room(guide.full.copy(), guide, plan, image,
                                                 a.DEFAULT_MATCH_STRENGTH, room.has_alpha)
                self.assertEqual((final.size, final.mode), (room.out_size, room.mode))
                self.assertTrue(result.passed, result.issues)
```

- [ ] **Step 8: Run everything**

Run: `make check && make test`
Expected: PASS. With the real corpus present the new class takes a few minutes; a room that fails here is a gate or planning bug to fix before any render, never a threshold to loosen.

- [ ] **Step 9: Commit**

```bash
git add thedig-texture-enhancement
git commit -m "feat(kit): fill transparent rooms for rendering and keep their exact alpha

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Room style, Dig prompts and the seeded rooms.yaml

**Files:**
- Modify: `rooms_file.py` (`RoomEntry.style`, `RoomEntry.skip_objects`, `STYLES`)
- Modify: `prompts.py` (Dig caption question with MEDIUM, `section`, `medium_style`, `PAINTED_RULES`, `RENDERED_RULES`, `STYLE_RULES`, `negative_prompt`, `render_prompt(style=)`, `REVIEW_QUESTION`, `review_room(style=)`)
- Modify: `dig_recreate.py` (caption fills style; render and review use it)
- Create: `thedig-texture-enhancement/rooms.yaml`
- Test: `test_rooms_file.py`, `test_prompts.py`, `test_dig_recreate.py`

**Interfaces:**
- Produces: `rooms_file.STYLES = ("painted", "rendered")`; `RoomEntry(kind, caption="", style="", skip_objects=())`; `prompts.section(caption, label) -> str | None`; `prompts.medium_style(caption) -> "painted" | "rendered"`; `prompts.negative_prompt(style) -> str`; `prompts.render_prompt(caption, kind, corrections=(), note="", reference=DEFAULT_REFERENCE, style="painted")`; `prompts.STYLE_RULES: dict[str, str]`; `prompts.review_room(pairs, overview, kind, caption, http, base_url, model, key, style="painted")`; `prompts.PAINTED_NEGATIVE`, `prompts.RENDERED_NEGATIVE`.

- [ ] **Step 1: Write the failing tests**

`test_rooms_file.py`:

```python
    def test_style_and_skip_objects(self):
        path = self.tmp / "rooms.yaml"
        entries = {"room_001": RoomEntry("scene", "SCENE: x", "rendered", ("obj010_02",)),
                   "room_002": RoomEntry("insert")}
        save_rooms(path, entries)
        self.assertEqual(load_rooms(path), entries)
        text = path.read_text()
        self.assertIn("style: rendered", text)
        self.assertEqual(text.count("style"), 1, msg="a blank style is not written")
        self.assertEqual(text.count("skip_objects"), 1, msg="an empty list is not written")
        cases = {
            "bad style": ("room_001:\n  kind: scene\n  style: oil\n", '"style" must be'),
            "not a list": ("room_001:\n  kind: scene\n  skip_objects: obj010_02\n",
                           '"skip_objects" must be a list'),
            "bad key": ("room_001:\n  kind: scene\n  skip_objects: [door]\n",
                        "'door' is not an object key"),
        }
        for name, (text, message) in cases.items():
            with self.subTest(name):
                path.write_text(text)
                with self.assertRaisesRegex(RoomsFileError, message):
                    load_rooms(path)
```

(`self.tmp` as in the module's existing fixtures; create it in `setUp` if the class has none.)

`test_prompts.py`:

```python
    def test_medium_picks_the_style_and_the_rules(self):
        cases = {
            "SCENE: a shuttle\nMEDIUM: pre-rendered 3D, hard CGI shading\nVIEW: side": "rendered",
            "SCENE: a cave\n**MEDIUM:** mixed: painted rock, a 3D model of the tram": "rendered",
            "SCENE: a cave\nMEDIUM: painted, soft airbrushed gradients": "painted",
            "SCENE: a cave\nVIEW: wide": "painted",
        }
        for caption, style in cases.items():
            with self.subTest(caption=caption):
                self.assertEqual(p.medium_style(caption), style)
        rendered = p.render_prompt("SCENE: x", "scene", style="rendered")
        self.assertTrue(rendered.startswith(p.RENDERED_RULES.format(reference=p.DEFAULT_REFERENCE)))
        self.assertIn("The Dig", p.render_prompt("SCENE: x", "scene"))
        self.assertNotIn("CGI", p.negative_prompt("rendered"))
        self.assertIn("CGI", p.negative_prompt("painted"))
        self.assertIn("MEDIUM:", p.CAPTION_QUESTION)
```

`test_dig_recreate.py` (import `replace` from `dataclasses`, `save_rooms` from `rooms_file`, `RENDERED_NEGATIVE` from `prompts`). In `CaptionTests`:

```python
    def test_caption_fills_a_blank_style_from_medium(self):
        caption = "SCENE: a test room.\nMEDIUM: pre-rendered 3D\nTEXT: none"
        with testkit.vlm_stub(caption=lambda *a_, **k: caption):
            code, _, err = self.run_cli("caption", "--room", "1", "--force")
        self.assertEqual(code, 0, err)
        entries = load_rooms(self.rooms_file)
        self.assertEqual(entries["room_001"].style, "rendered")
        save_rooms(self.rooms_file, {**entries, "room_001": replace(entries["room_001"],
                                                                    style="painted")})
        with testkit.vlm_stub(caption=lambda *a_, **k: caption):
            self.run_cli("caption", "--room", "1", "--force")
        self.assertEqual(load_rooms(self.rooms_file)["room_001"].style, "painted")
```

In `RenderRoomTests` (`test_a_one_window_room` keeps `PAINTED_NEGATIVE`: a blank style renders as painted):

```python
    def test_a_rendered_room_gets_the_rendered_rules(self):
        entries = load_rooms(self.rooms_file)
        self.entries = {**entries, "room_001": replace(entries["room_001"], style="rendered")}
        _, stub = self.render(1)
        kw = stub.render.call_args.kwargs
        self.assertEqual(kw["negative"], RENDERED_NEGATIVE)
        self.assertTrue(kw["positive"].startswith("Recreate "))
```

- [ ] **Step 2: Run to verify failure**

Run: `make test`
Expected: FAIL/ERROR.

- [ ] **Step 3: Implement rooms_file**

```python
KINDS = ("scene", "insert", "skip")
STYLES = ("painted", "rendered")
REVIEW_SOURCES = ("review", "geometry")
_KEY = re.compile(r"^room_\d{3}$")
_OBJECT_KEY = re.compile(r"^obj\d{3,}_[0-9A-F]{2}$")


@dataclass(frozen=True)
class RoomEntry:
    kind: str
    caption: str = ""
    style: str = ""             # painted | rendered; "" until caption fills it (renders as painted)
    skip_objects: tuple = ()    # object keys written as a nearest-neighbour 4x
```

In `load_rooms`: allowed fields `{"kind", "caption", "style", "skip_objects"}`; then

```python
        style = entry.get("style") or ""
        if style and style not in STYLES:
            raise RoomsFileError(f'{where}: "style" must be one of {", ".join(STYLES)}, '
                                 f"got {style!r}")
        skip = entry.get("skip_objects") or []
        if not isinstance(skip, list):
            raise RoomsFileError(f'{where}: "skip_objects" must be a list of object keys')
        for key_ in skip:
            if not isinstance(key_, str) or not _OBJECT_KEY.match(key_):
                raise RoomsFileError(f"{where}: {key_!r} is not an object key (objNNN_SS)")
        result[key] = RoomEntry(kind, caption, style, tuple(skip))
```

`save_rooms`:

```python
def save_rooms(path, rooms):
    def entry(e):
        out = {"kind": e.kind}
        if e.style:
            out["style"] = e.style
        out["caption"] = normalize_text(e.caption)
        if e.skip_objects:
            out["skip_objects"] = list(e.skip_objects)
        return out
    _dump({key: entry(rooms[key]) for key in sorted(rooms)}, path)
```

Update the module docstring to mention `style` and `skip_objects`.

- [ ] **Step 4: Implement the Dig prompts**

In `prompts.py` replace `CAPTION_QUESTION`, `SECTION_LABELS`, `PAINTED_RULES`, `REVIEW_QUESTION` and add the rest:

```python
CAPTION_QUESTION = '''Image 1 is a background from The Dig (LucasArts, 1995), a 256-colour point-and-click adventure game whose backgrounds are hand-painted or pre-rendered 3D. Any further images are windows of the same room, row by row from the top left. Describe it for an artist who will recreate it in high definition with exactly the same composition. Report only what the images show; this is observation, not creative writing.
Use these short labelled sections:
SCENE: the kind of place (interior, exterior, close-up insert, map, device screen), its architecture and atmosphere.
MEDIUM: painted, pre-rendered 3D, or mixed, with one sentence of visible evidence (brushwork, airbrushed gradients, hard CGI shading, specular highlights, ray-traced reflections).
VIEW: viewpoint, framing and perspective.
LAYOUT: the major objects and surfaces, each with its horizontal position as a fraction of the room's width (0 is the left edge, 1 the right edge) and its vertical position as a fraction of its height (0 top, 1 bottom), relative size and occlusion. Cover foreground, middle and background.
OBJECTS: doors, openings, machines, crystals, plates, furniture and props, with their open or closed states; say absent if there are none.
LIGHTING: light sources, their direction, the exposure and the shadows. Dark areas stay dark.
PALETTE: the dominant colours of each major area.
TEXT: every piece of lettering or glyph writing that is legible, transcribed verbatim with its position; write none if there is none. Do not guess at illegible text.
INVARIANTS: the composition and object relationships that must survive recreation. Mark ambiguity instead of inventing detail.
The game draws its characters separately, so say "no people" unless people are painted into the background itself. Do not prescribe a style, lens or colour grade. Keep under 600 words.'''

SECTION_LABELS = ("SCENE", "MEDIUM", "VIEW", "LAYOUT", "OBJECTS", "LIGHTING", "PALETTE",
                  "TEXT", "INVARIANTS")

STYLES = ("painted", "rendered")

PAINTED_RULES = '''Repaint {reference} as a high-definition hand-painted background for a classic point-and-click adventure game, in the manner of the painted backgrounds of mid-1990s LucasArts adventures such as The Dig: confident painterly brushwork, rich but faithful colour, soft painted light and shadow, crisp readable shapes.
Keep the exact composition. Every object, edge, opening and horizon stays where the reference puts it, at the same size and in the same perspective; nothing is moved, added, removed or resized. Add no people, creatures or characters that the reference does not show.
Keep the reference's colours, time of day, light sources and shadow pattern. Dark areas stay dark and flat black areas stay flat black.
Replace the dithering and blocky pixels with painted texture and fine detail that suit each material: rock, sand, crystal, alien metal, water, sky. No photograph, no 3D render, no pixel art, no border or frame.'''

RENDERED_RULES = '''Recreate {reference} as a high-definition pre-rendered 3D background for a classic point-and-click adventure game, in the manner of the pre-rendered scenes of mid-1990s LucasArts adventures such as The Dig: clean modelled surfaces, crisp geometry, smooth gradients, specular highlights and soft ray-traced light, at a much higher resolution than the reference.
Keep the exact composition. Every object, edge, opening and horizon stays where the reference puts it, at the same size and in the same perspective; nothing is moved, added, removed or resized. Add no people, creatures or characters that the reference does not show.
Keep the reference's colours, time of day, light sources and shadow pattern. Dark areas stay dark and flat black areas stay flat black.
Replace the blocky pixels and colour banding with clean, detailed surfaces that suit each material: hull plating, glass, rock, dust, starfield, metal. No photograph, no painting, no pixel art, no border or frame.'''

PAINTED_NEGATIVE = ("photograph, photorealistic, 3D render, CGI, pixel art, dithering, jpeg "
                    "artifacts, blurry, noisy, people, characters, figures, extra objects, "
                    "changed text, extra text, watermark, signature, frame, border")
RENDERED_NEGATIVE = ("photograph, photorealistic, painting, brush strokes, pixel art, dithering, "
                     "jpeg artifacts, blurry, noisy, people, characters, figures, extra objects, "
                     "changed text, extra text, watermark, signature, frame, border")

STYLE_RULES = {
    "painted": "the recreation looks like a photograph or a 3D render, or keeps the original's "
               "flat, dithered pixels instead of painted detail",
    "rendered": "the recreation looks like a photograph or a painting instead of clean "
                "pre-rendered 3D, or keeps the original's blocky pixels and banding",
}

REVIEW_QUESTION = '''The images come in pairs. In each pair the first image is one window of the authoritative original background of a 1995 adventure game (smoothed and enlarged), and the second is the same window of a high-definition recreation. The last image is the whole recreation, downscaled. Judge fidelity first, then style. New fine detail replacing the original's pixels is the goal and is never a reason to reject.
Reject when:
1. layout: an object, edge, opening or horizon is added, dropped, moved or resized, the perspective or framing changed, or a person, creature or character appears that the original lacks;
2. style: {style_rule};
3. lettering (close-up inserts only): legible lettering differs from the expected lettering below, or became illegible;
4. seams: a visible vertical or horizontal seam, a doubled object or repeated detail where windows meet, or a jump in colour or texture between neighbouring windows in the whole recreation.
Return ONLY JSON: {"accepted": true or false, "issues": ["one specific problem: its window number, its screen position and a concrete correction"]}. Accept only if there are no significant problems; use an empty issues list when accepted. At most six issues.'''
```

Replace `text_section` with:

```python
def section(caption, label):
    """The caption's `label` section, stripped, or None when it is absent or empty.

    Labels may be bold or italic (the VLM sometimes writes **TEXT:**); a section
    runs to the next label or the end.
    """
    labels = "|".join(SECTION_LABELS)
    pattern = re.compile(rf"^[ \t]*[*_#]*[ \t]*({labels})[ \t]*[*_]*[ \t]*:[*_]*", re.M)
    matches = list(pattern.finditer(caption))
    for i, match in enumerate(matches):
        if match.group(1) != label:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(caption)
        return caption[match.end():end].strip() or None
    return None


def text_section(caption):
    """The caption's TEXT section, or None when it is absent or says there is none."""
    text = section(caption, "TEXT")
    if text is None or text.lower().rstrip(".") in _NONE:
        return None
    return text


_RENDERED = re.compile(r"pre-?rendered|\b3d\b|\bcgi\b|computer[- ]generated", re.I)


def medium_style(caption):
    """The style the caption's MEDIUM implies: "rendered" when it mentions
    pre-rendered, 3D, CGI or computer-generated art, else "painted"."""
    return "rendered" if _RENDERED.search(section(caption, "MEDIUM") or "") else "painted"


def negative_prompt(style):
    return RENDERED_NEGATIVE if style == "rendered" else PAINTED_NEGATIVE
```

`render_prompt(caption, kind, corrections=(), note="", reference=DEFAULT_REFERENCE, style="painted")` starts `parts = [(RENDERED_RULES if style == "rendered" else PAINTED_RULES).format(reference=reference)]`; the rest is unchanged. `review_room(..., key, style="painted")` builds `question = (REVIEW_QUESTION.replace("{style_rule}", STYLE_RULES.get(style, STYLE_RULES["painted"])) + f"\nThis room has {len(pairs)} window(s). Kind: {kind}. Style: {style or 'painted'}. Expected lettering: {lettering or 'none'}.")`.

- [ ] **Step 5: Wire the driver**

`from dataclasses import replace` in `dig_recreate.py`; import `RENDERED_NEGATIVE`, `medium_style`, `negative_prompt` instead of `PAINTED_NEGATIVE` where it was only the negative. In `cmd_caption`: `entries[room.key] = replace(entry, caption=caption, style=entry.style or medium_style(caption))`. In `render_room`: `style = entry.style or "painted"`, `negative = negative_prompt(style)`; pass `style=style` to `render_prompt` and `negative=negative` to `render_window`, and write `negative` into the prompt log. In `cmd_review`: pass `style=entry.style or "painted"` to `review_room`.

- [ ] **Step 6: Seed rooms.yaml**

```bash
cd ~/code/thedig-hd-bundle/thedig-texture-enhancement && .venv/bin/python - <<'EOF'
from rooms_file import RoomEntry, save_rooms
SKIP = {1, 86, 88, 93, 103, 104}                  # flat, line charts, the sprite sheet
INSERT = {28, 35, 51, 59, 69, 76, 79, 106, 107}   # map, plates, PenUltimator, title
save_rooms("rooms.yaml", {f"room_{n:03d}": RoomEntry("skip" if n in SKIP else
                                                      "insert" if n in INSERT else "scene")
                          for n in range(1, 112)})
EOF
```

Add to `test_rooms_file.py`:

```python
    def test_the_shipped_rooms_file_loads(self):
        rooms = load_rooms(Path(__file__).resolve().parent / "rooms.yaml")
        self.assertEqual(len(rooms), 111)
        self.assertEqual(sorted(k for k, e in rooms.items() if e.kind == "skip"),
                         ["room_001", "room_086", "room_088", "room_093", "room_103", "room_104"])
```

- [ ] **Step 7: Run everything**

Run: `make check && make test`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add thedig-texture-enhancement
git commit -m "feat(kit): Dig prompts, per-room painted/rendered style, seeded rooms.yaml

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: De-dither option and the room spike

**Files:**
- Modify: `room_geometry.py` (`DEDITHER_METHODS` gains `"none"`), `dig_recreate.py` (`--dedither`, `render_options`), `Makefile` (`dedither=`)
- Create: `thedig-texture-enhancement/NOTES.md`
- Test: `test_room_geometry.py`, `test_dig_recreate.py`, `test_scripts.py`

**Interfaces:**
- Produces: `room_geometry.dedither(rgb, "none")` returns `rgb.convert("RGB")`; batch option `--dedither {palette-smooth,gaussian,none}` (default `room_geometry.DEDITHER_METHOD`) read as `args.dedither`, passed to `build_guide` and recorded as `"dedither"`; `dig_recreate.render_options(parser)` adds `--dry-run`, `--no-memory-check`, `--force`, `--match-strength`, `--workflow`, `--dedither` (reused by `objects` in Task 11); make arg `dedither=`.

- [ ] **Step 1: Write the failing tests**

`test_room_geometry.py`, in `GuideTests.test_dedither_softens_the_checkerboard`'s neighbour, add:

```python
    def test_dedither_none_is_the_identity(self):
        board = checkerboard((100, 100, 100), (130, 130, 130))
        self.assertEqual(rg.dedither(board, "none").tobytes(), board.tobytes())
```

`test_dig_recreate.py`: give `RenderRoomTests.render` a `dedither=room_geometry.DEDITHER_METHOD` keyword and build `args = argparse.Namespace(src=self.src, dst=self.dst, match_strength=0.5, dedither=dedither)`; add

```python
    def test_the_dedither_method_is_recorded(self):
        self.render(1, dedither="none")
        self.assertEqual(self.record(1)["dedither"], "none")
```

`test_scripts.py`: add `("batch", "room=11", "dedither=none"): "./run_batch.sh batch --room 11 --dedither none"`.

- [ ] **Step 2: Run to verify failure**

Run: `make test`
Expected: FAIL.

- [ ] **Step 3: Implement**

`room_geometry.py`: `DEDITHER_METHODS = ("palette-smooth", "gaussian", "none")` and at the top of `dedither`: `if method == "none": return rgb.convert("RGB")`.

`dig_recreate.py`: move the batch options into

```python
def render_options(p):
    """The options of the two render stages, batch and objects."""
    p.add_argument("--dry-run", action="store_true",
                   help="print the plan without contacting ComfyUI or writing files")
    p.add_argument("--no-memory-check", action="store_true",
                   help=f"skip the {MEMORY_FLOOR_GB} GB available-memory guard")
    p.add_argument("--force", action="store_true",
                   help="render the selection again, even when done or stuck")
    p.add_argument("--match-strength", type=match_strength, default=default_match_strength(),
                   metavar="X",
                   help="how far each render moves toward its source's colours, 0 to 1 "
                        "(default: %(default)s, or DIG_MATCH_STRENGTH)")
    p.add_argument("--workflow", choices=sorted(comfy_client.WORKFLOWS),
                   default=default_workflow(), metavar="NAME",
                   help="render workflow: " + ", ".join(sorted(comfy_client.WORKFLOWS))
                        + " (default: %(default)s, or DIG_WORKFLOW)")
    p.add_argument("--dedither", choices=room_geometry.DEDITHER_METHODS,
                   default=room_geometry.DEDITHER_METHOD,
                   help="how the guide smooths the source's dithering (default: %(default)s)")
```

and call it for `batch`. In `render_room` use `room_geometry.build_guide(image, args.dedither)` and record `"dedither": args.dedither`.

`Makefile`: `dedither ?=`, and in `BATCH_ARGS` insert `$(if $(dedither),--dedither $(dedither))` just before `$(FORCE_ARG)`; mention `dedither=` in the batch and dry-run help strings.

- [ ] **Step 4: Run and commit**

Run: `make check && make test` → PASS.

```bash
git add thedig-texture-enhancement
git commit -m "feat(kit): choose the guide's de-dither method per batch

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Run the spike (manual, GB10, services one at a time)**

1. vLLM up (`docker start lmcache-server vllm-server`), ComfyUI down: `make caption room="2 4 11 27 43 60"`. Open each room image next to its caption in `rooms.yaml` and correct misreadings; confirm `style` is `rendered` for 2 and 4 and `painted` for 11, 43, 60 (fix by hand if not). The Atlantis run changed 61 of 91 captions this way.
2. vLLM down (`docker stop vllm-server lmcache-server`), ComfyUI up (`make server`). `make dry-run room="2 4 11 27 43 60"`: room 27 shows `x-x/y-y` windows and "padded to 784 rows".
3. `make batch room="2 4 11 27 43 60" dst=data/spike/smooth`
4. `make batch room="11 43 60" dst=data/spike/none dedither=none force=1`
5. For each room read `data/spike/*/.quality/room_NNN/attempt-1.json` (`geometry.shift`, `window_shifts`, `edge_agreement`, `seam_ratios`, `seconds`) and view the outputs next to the sources; show the user side-by-side sheets.
6. If room 27 is rejected for shift in its lower windows on seeds 42 and 43, set `WINDOW_HEIGHT = 200` locally, `make batch room=27 dst=data/spike/h200 force=1`, and compare.
7. Watch the wide rooms (2: 976 px) for **caption leak**: an object from another window painted into this one (the Atlantis full run's main review failure). Note any.

- [ ] **Step 6: Record the decisions**

Create `NOTES.md`:

```markdown
# Live checks, spikes and runs

Measured facts behind the kit's constants. Newest last.

## Extraction (Task 2)

<date>: `thedig-textures extract --only la1` 0.2.0: 111 rooms, 642 objects;
<inside> objects inside their rooms, <identical> identical to the room beneath,
<outside> outside: <list>.

## Room spike (<date>, GB10)

Rooms 2, 4 (rendered), 11, 43, 60 (painted), 27 (512x780), seed 42, match strength 0.5.

| Variant | Rooms | s a window | Promoted | Worst shift | Lowest edge |
|---|---|---|---|---|---|
| ... one row per variant, from the attempt records ... |

Decisions (the user's, from the sheets):
- `DEDITHER_METHOD`: <palette-smooth | none>, because <evidence>.
- `WINDOW_HEIGHT`: <240 | 200>, because <evidence>.
- `RENDERED_RULES`: <kept | changed to …>, because <evidence>.
- Caption leak: <none seen | rooms …>.
```

filling every `<…>` with the measured values and the user's choices (these are data slots for the spike's results, not open design questions). Apply the chosen constants in `room_geometry.py` (`DEDITHER_METHOD`, `WINDOW_HEIGHT`) and re-run `make test`.

```bash
git add thedig-texture-enhancement/NOTES.md thedig-texture-enhancement/room_geometry.py thedig-texture-enhancement/rooms.yaml
git commit -m "docs(kit): record the room spike and its decisions

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: `object_geometry` — classification, context, inputs, compose, check

**Files:**
- Create: `thedig-texture-enhancement/object_geometry.py`
- Create: `thedig-texture-enhancement/test_object_geometry.py`

**Interfaces:**
- Consumes: `source_tree.SCALE`, `source_tree.colour_keys`, `source_tree.TRANSPARENT_KEY`; `room_geometry.ALIGN`, `dedither`, `fill_transparent`, `pad_rows`, `DEDITHER_METHOD`; `colour_match.match(..., mask=)`; `geometry_check.check(..., min_edges=)`, `geometry_check.MIN_WINDOW_EDGES`, `GeometryResult`.
- Produces: `CONTEXT_MARGIN = 32`, `MIN_CONTEXT = 128`, `MASK_GROW = 2`, `MASK_SOFTEN = 4`; `diff_mask(obj, room, x, y) -> bool (h, w)`; `classify(obj, room, x, y) -> "identical" | "render"`; `context_box(x, y, width, height, room_width, room_height) -> (x0, y0, x1, y1)`; `draw_object(room, obj, x, y) -> RGB Image`; `ObjectInputs(box, guide, base, composite, mask, changed, native, rect)`; `object_inputs(room_hd, room, obj, x, y, method=DEDITHER_METHOD) -> ObjectInputs`; `compose(rendered, inputs, strength) -> RGB Image`; `object_crop(final, inputs, x, y, width, height) -> RGB Image`; `identical_output(room_hd, x, y, width, height) -> RGB Image`; `check_object(final, inputs) -> GeometryResult`.

- [ ] **Step 1: Write the failing tests**

```python
import unittest

import numpy as np
from PIL import Image

import object_geometry as og
import room_geometry as rg
import source_tree
import testkit


def spec(key):
    return next(o for o in testkit.DEFAULT_OBJECTS if o["key"] == key)


def images(key, rooms=testkit.DEFAULT_ROOMS):
    o = spec(key)
    room_spec = next(r for r in rooms if r["room"] == o["room"])
    room = testkit.room_image(room_spec).convert("RGBA")
    obj = testkit.to_image(testkit.object_pixels(o, rooms), testkit.object_alpha(o)).convert("RGBA")
    return o, room, obj


def promoted(room):
    """A stand-in for the promoted room: its own guide at exactly 4x."""
    guide = rg.build_guide(room)
    return guide.full.crop((0, 0, room.width * 4, room.height * 4))


class ClassifyTests(unittest.TestCase):
    def test_identical_render_and_the_diff(self):
        for key, expected in (("obj010_01", "identical"), ("obj010_02", "render"),
                              ("obj011_01", "render")):
            with self.subTest(key):
                o, room, obj = images(key)
                self.assertEqual(og.classify(obj, room, o["x"], o["y"]), expected)
        o, room, obj = images("obj011_01")
        diff = og.diff_mask(obj, room, o["x"], o["y"])
        self.assertFalse(diff[:2].any(), msg="transparent pixels never count as changed")
        self.assertTrue(diff[2:-2, 2:-2].any())


class ContextTests(unittest.TestCase):
    def test_context_boxes(self):
        cases = {   # (x, y, w, h, room_w, room_h): box
            "middle, widened": ((200, 60, 40, 40, 568, 144), (152, 16, 280, 144)),
            "left edge, widened": ((40, 24, 48, 32, 320, 144), (0, 0, 128, 128)),
            "right edge, widened": ((280, 100, 40, 40, 320, 144), (192, 16, 320, 144)),
            "a room smaller than the minimum": ((0, 0, 8, 8, 16, 200), (0, 0, 16, 128)),
            "into the padding": ((100, 200, 40, 30, 352, 230), (56, 104, 184, 232)),
        }
        for name, (args, expected) in cases.items():
            with self.subTest(name):
                box = og.context_box(*args)
                self.assertEqual(box, expected)
                self.assertTrue(all(v % 8 == 0 for v in box))


class InputTests(unittest.TestCase):
    def setUp(self):
        self.o, self.room, self.obj = images("obj010_02")
        self.hd = promoted(self.room)
        self.inputs = og.object_inputs(self.hd, self.room, self.obj, self.o["x"], self.o["y"])

    def test_sizes_mask_and_composite(self):
        i = self.inputs
        self.assertEqual(i.box, (0, 0, 128, 128))
        for image in (i.guide, i.base, i.composite, i.mask):
            self.assertEqual(image.size, (512, 512))
        m = np.asarray(i.mask)
        self.assertTrue((m[i.changed] == 255).all())
        self.assertEqual(m[-1, -1], 0)
        keep = m == 0
        self.assertTrue((np.asarray(i.composite)[keep] == np.asarray(i.base)[keep]).all())
        self.assertTrue((np.asarray(i.composite)[i.changed] == np.asarray(i.guide)[i.changed]).all())
        self.assertEqual((i.native.size, i.rect), ((128, 128), (40, 24, 88, 56)))

    def test_a_perfect_render_passes_and_a_stray_paste_is_caught(self):
        final = og.compose(self.inputs.composite, self.inputs, 0.5)
        result = og.check_object(final, self.inputs)
        self.assertTrue(result.passed, result.issues)
        crop = og.object_crop(final, self.inputs, self.o["x"], self.o["y"], 48, 32)
        self.assertEqual(crop.size, (192, 128))
        final.paste((255, 0, 255), (500, 500, 512, 512))       # outside the mask
        self.assertIn("pixels outside the object mask differ from the promoted room",
                      " ".join(og.check_object(final, self.inputs).issues))
        slid = og.compose(testkit.shift_right(self.inputs.composite), self.inputs, 0.5)
        issues = " ".join(og.check_object(slid, self.inputs).issues)
        self.assertIn("window 1 is shifted", issues, msg="an object that slid 2 px is caught")

    def test_identical_output_is_the_promoted_crop(self):
        out = og.identical_output(self.hd, 40, 24, 48, 32)
        self.assertEqual(out.tobytes(), self.hd.crop((160, 96, 352, 224)).tobytes())

    def test_a_room_with_a_ragged_height(self):
        rooms = (testkit.room(9, 352, 230),)
        o = testkit.obj("obj050_01", 9, 100, 200, 40, 30)
        room = testkit.room_image(rooms[0]).convert("RGBA")
        obj = testkit.to_image(testkit.object_pixels(o, rooms)).convert("RGBA")
        inputs = og.object_inputs(promoted(room), room, obj, 100, 200)
        self.assertEqual((inputs.box, inputs.composite.size, inputs.native.size),
                         ((56, 104, 184, 232), (512, 512), (128, 126)))
        final = og.compose(inputs.composite, inputs, 0.5)
        self.assertTrue(og.check_object(final, inputs).passed)


@testkit.needs_real_corpus
class RealCorpusTests(unittest.TestCase):
    def test_every_placed_object_classifies(self):
        source = source_tree.load(testkit.REAL_SRC)
        rooms = {r.number: source_tree.open_rgba(testkit.REAL_SRC, r) for r in source.rooms}
        counts = {"identical": 0, "render": 0}
        for o in source.objects:
            if o.placement_error:
                continue
            obj = source_tree.open_rgba(testkit.REAL_SRC, o)
            counts[og.classify(obj, rooms[o.room], o.x, o.y)] += 1
        self.assertGreater(counts["identical"], 0)
        self.assertGreater(counts["render"], 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m unittest test_object_geometry -v`
Expected: ERROR (`No module named 'object_geometry'`).

- [ ] **Step 3: Implement `object_geometry.py`**

```python
"""Room object geometry: which object images need a render, the context window
around one, its guide, composite and mask over the promoted room, the finished
context window, the object's crop and the check.

Pure image maths on Pillow images and numpy arrays, like room_geometry; talks
to no service and knows no file layout. Positions are native room pixels
unless a name says 4x. An object is repainted in place: only its changed
pixels (grown a little) are painted, everything else is the promoted room.
"""
import math
from dataclasses import dataclass, replace

import numpy as np
from PIL import Image, ImageFilter

import colour_match
import geometry_check
import room_geometry
from source_tree import SCALE, TRANSPARENT_KEY, colour_keys

CONTEXT_MARGIN = 32     # native px of room around the object rectangle
MIN_CONTEXT = 128       # the least context width and height, where the room allows
MASK_GROW = 2           # native px the changed area grows into the room, for blending
MASK_SOFTEN = 4         # 4x px of box blur on the grown mask's edge
ALIGN = room_geometry.ALIGN


def diff_mask(obj, room, x, y):
    """(h, w) bool: the object's opaque pixels whose colour differs from the
    room pixel beneath them."""
    o = colour_keys(obj)
    under = colour_keys(room)[y:y + obj.height, x:x + obj.width]
    return (o != TRANSPARENT_KEY) & (o != under)


def classify(obj, room, x, y):
    """"identical" when the object shows exactly the room beneath it, else "render"."""
    return "render" if diff_mask(obj, room, x, y).any() else "identical"


def _axis(lo, hi, size):
    """[lo, hi) grown by CONTEXT_MARGIN, to at least MIN_CONTEXT, on ALIGN,
    inside [0, size rounded up to ALIGN)."""
    limit = ALIGN * math.ceil(size / ALIGN)
    lo = ALIGN * (max(0, lo - CONTEXT_MARGIN) // ALIGN)
    hi = min(limit, ALIGN * math.ceil((hi + CONTEXT_MARGIN) / ALIGN))
    if hi - lo < MIN_CONTEXT:
        lo = max(0, lo - ALIGN * math.ceil((MIN_CONTEXT - (hi - lo)) / 2 / ALIGN))
        hi = min(limit, max(hi, lo + MIN_CONTEXT))
        lo = max(0, min(lo, hi - MIN_CONTEXT))
    return lo, hi


def context_box(x, y, width, height, room_width, room_height):
    """The native context window (x0, y0, x1, y1) around the object rectangle,
    on the room padded to ALIGN rows, so its 4x size is a multiple of 32."""
    x0, x1 = _axis(x, x + width, room_width)
    y0, y1 = _axis(y, y + height, room_height)
    return (x0, y0, x1, y1)


def draw_object(room, obj, x, y):
    """The native room as RGB, its transparent pixels filled, with the object's
    opaque pixels drawn at (x, y)."""
    scene = room_geometry.fill_transparent(room)
    rgba = obj.convert("RGBA")
    scene.paste(rgba.convert("RGB"), (x, y), rgba.getchannel("A").point(lambda v: 255 if v else 0))
    return scene


def _dilate(mask, steps):
    h, w = mask.shape
    for _ in range(steps):
        p = np.pad(mask, 1)
        out = np.zeros_like(mask)
        for dy in range(3):
            for dx in range(3):
                out |= p[dy:dy + h, dx:dx + w]
        mask = out
    return mask


def _up(mask):
    return np.kron(mask, np.ones((SCALE, SCALE), bool))


@dataclass(frozen=True)
class ObjectInputs:
    box: tuple              # native context window (x0, y0, x1, y1)
    guide: Image.Image      # 4x: the room with the object drawn, de-dithered, Lanczos
    base: Image.Image       # 4x: the promoted room's crop (padded rows repeat its last row)
    composite: Image.Image  # 4x: base with the guide pasted over the changed pixels
    mask: Image.Image       # L, 4x: 255 paints, 0 keeps base
    changed: np.ndarray     # 4x bool: the object's changed pixels (colour-match statistics)
    native: Image.Image     # native context guide cut to the room's real rows: the gate's source
    rect: tuple             # the object rectangle within the context window, native (x0, y0, x1, y1)


def object_inputs(room_hd, room, obj, x, y, method=room_geometry.DEDITHER_METHOD):
    """Everything one object render needs, over the promoted 4x `room_hd`."""
    box = context_box(x, y, obj.width, obj.height, room.width, room.height)
    x0, y0, x1, y1 = box
    padded = ALIGN * math.ceil(room.height / ALIGN)
    scene = room_geometry.dedither(draw_object(room, obj, x, y), method)
    ctx = room_geometry.pad_rows(scene, padded).crop(box)
    guide = ctx.resize((ctx.width * SCALE, ctx.height * SCALE), Image.Resampling.LANCZOS)
    box4 = tuple(v * SCALE for v in box)
    base = room_geometry.pad_rows(room_hd.convert("RGB"), padded * SCALE).crop(box4)
    changed_native = np.zeros((y1 - y0, x1 - x0), bool)
    changed_native[y - y0:y - y0 + obj.height, x - x0:x - x0 + obj.width] = diff_mask(obj, room, x, y)
    changed = _up(changed_native)
    paint = _up(_dilate(changed_native, MASK_GROW))
    soft = Image.fromarray(paint.astype(np.uint8) * 255).filter(ImageFilter.BoxBlur(MASK_SOFTEN))
    mask = np.asarray(soft).copy()
    mask[changed] = 255
    composite = base.copy()
    composite.paste(guide, (0, 0), Image.fromarray(changed.astype(np.uint8) * 255))
    native = scene.crop((x0, y0, x1, min(y1, room.height)))
    rect = (x - x0, y - y0, x - x0 + obj.width, y - y0 + obj.height)
    return ObjectInputs(box, guide, base, composite, Image.fromarray(mask), changed, native, rect)


def compose(rendered, inputs, strength):
    """The finished context window: the render colour-matched toward the guide
    over the changed pixels, laid over the base through the mask."""
    matched = colour_match.match(rendered, inputs.guide, strength, mask=inputs.changed)
    return Image.composite(matched, inputs.base, inputs.mask)


def object_crop(final, inputs, x, y, width, height):
    """The object's rectangle out of the finished context window, 4x RGB."""
    left, top = (x - inputs.box[0]) * SCALE, (y - inputs.box[1]) * SCALE
    return final.crop((left, top, left + width * SCALE, top + height * SCALE)).convert("RGB")


def identical_output(room_hd, x, y, width, height):
    """An identical object's output: the promoted room's crop of its rectangle."""
    return room_hd.convert("RGB").crop((x * SCALE, y * SCALE, (x + width) * SCALE,
                                        (y + height) * SCALE))


def check_object(final, inputs):
    """geometry_check over the context window's real rows, with the object
    rectangle as its one window: the unchanged room around an object would
    hide the object's own drift in the whole-window measures. A sparse window
    reads 1.0. Plus: every pixel the mask keeps is the promoted room's, byte
    for byte."""
    render = final.convert("RGB").crop((0, 0, final.width, inputs.native.height * SCALE))
    result = geometry_check.check(render, inputs.native, windows=[inputs.rect],
                                  min_edges=geometry_check.MIN_WINDOW_EDGES)
    keep = np.asarray(inputs.mask) == 0
    if not np.array_equal(np.asarray(final.convert("RGB"))[keep], np.asarray(inputs.base)[keep]):
        result = replace(result, issues=result.issues + (
            "geometry: pixels outside the object mask differ from the promoted room",))
    return result
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m unittest test_object_geometry -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add thedig-texture-enhancement/object_geometry.py thedig-texture-enhancement/test_object_geometry.py
git commit -m "feat(kit): object geometry: classify, context window, masked inputs, check

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: The `objects` stage

**Files:**
- Modify: `dig_recreate.py` (options `--obj-dst`, `--object`; status helpers take `dst`; `object_selection`, `object_status`, `render_object`, `write_nearest_object`, `cmd_objects`)
- Modify: `rooms_file.py` (`load_reviews`/`save_reviews` accept object keys)
- Modify: `prompts.py` (`OBJECT_NOTE`)
- Modify: `testkit.py` (`write_rooms(..., skip_objects=None)`), `Makefile` (`objects`, `objects-dry-run`, `object=`, `obj_dst=`)
- Test: `test_dig_recreate.py`, `test_rooms_file.py`, `test_scripts.py`

**Interfaces:**
- Consumes: Task 10's `object_geometry` API; Task 4's `Obj`, `select_objects`, `objects_of`; Task 7's `with_alpha`, `alpha_matches`; Task 8's `negative_prompt`, `render_prompt(style=)`.
- Produces: `OBJ_DST_ROOT` (`DIG_OBJ_DST`, default `data/objects-ai`); common options `--obj-dst`, `--object KEY` (repeatable); `room_status(dst, item, reviews)`, `corrections_for(dst, item, reviews)`, `fallback_for(dst, item, workflow)` (first parameter is now the output root); `object_selection(args) -> list[Obj]`; `object_status(args, obj, reviews, room_sha) -> (status, attempt)` adding `stale`; `render_object(args, workflow, obj, room, entry, corrections, cls) -> (attempt, GeometryResult)`; object audit files `data/objects-ai/.quality/objNNN_SS/attempt-N.{json,png,prompt.txt,error.txt}` and `attempt-N.tiles/object.{guide,composite,mask}.png`, `object.png`; record fields `attempt, class, room, room_sha256, geometry, promoted, output_sha256, seconds` plus for renders `workflow, seed, reference ("composite"), dedither, context, match`; ComfyUI name `<objNNN_SS>_a<N>-object`; `prompts.OBJECT_NOTE`.

- [ ] **Step 1: Write the failing tests**

`test_rooms_file.py`:

```python
    def test_reviews_take_room_and_object_keys(self):
        path = self.tmp / "reviews.yaml"
        reviews = {"room_001": Review(1, True, ()),
                   "obj010_02": Review(2, False, ("halo",), "geometry")}
        save_reviews(path, reviews)
        self.assertEqual(load_reviews(path), reviews)
        path.write_text("door:\n  attempt: 1\n  accepted: true\n  issues: []\n")
        with self.assertRaisesRegex(RoomsFileError, "is not a room or object key"):
            load_reviews(path)
        rooms = self.tmp / "rooms.yaml"
        rooms.write_text("obj010_02:\n  kind: scene\n")
        with self.assertRaisesRegex(RoomsFileError, "is not a room key"):
            load_rooms(rooms)
```

`testkit.write_rooms`: add `skip_objects=None` (a mapping room number → list of keys) and pass `tuple(skip_objects.get(n, ()))` into each `RoomEntry`.

`test_dig_recreate.py`: in `DriverFixture.setUp` add `self.obj_dst = self.root / "objects"` and pass `"--obj-dst", str(self.obj_dst)` in `run_cli`. Update the direct `a.room_status(args, room, {})` call to `a.room_status(self.dst, room, {})`. Add:

```python
class ObjectTests(DriverFixture):
    def setUp(self):
        super().setUp()
        self.batch_rooms()

    def batch_rooms(self, *extra, transform=None):
        with testkit.comfy_stub(comfy_dir=self.comfy_dir, render=testkit.fake_render(transform)):
            code, _, err = self.run_cli("batch", "--room", "1", "--room", "2", "--room", "4", *extra)
        self.assertEqual(code, 0, err)

    def objects(self, *extra, transform=None, render=None):
        with testkit.comfy_stub(comfy_dir=self.comfy_dir,
                                render=render or testkit.fake_render(transform)) as stub:
            code, out, err = self.run_cli("objects", *extra)
        return code, out, err, stub

    def object_record(self, key, attempt=1):
        return json.loads((self.obj_dst / ".quality" / key / f"attempt-{attempt}.json").read_text())

    def test_classifies_renders_copies_and_reports_a_bad_placement(self):
        code, out, err, stub = self.objects()
        self.assertEqual(code, 0, err)
        self.assertIn("render 3, identical 1, copy 1, waiting 0, done 0, stuck 0, badplace 1", out)
        self.assertIn("BADPLACE obj013_01", err)
        names = sorted(c.kwargs["name"] for c in stub.render.call_args_list)
        self.assertEqual(names, ["obj010_02_a1-object", "obj011_01_a1-object",
                                 "obj014_01_a1-object"])
        self.assertEqual({c.kwargs["reference"] for c in stub.render.call_args_list}, {"composite"})
        room_sha = source_tree.file_sha256(self.dst / "room_001.png")
        with Image.open(self.obj_dst / "obj010_01.png") as im, \
                Image.open(self.dst / "room_001.png") as room:
            self.assertEqual((im.size, im.mode), ((192, 128), "RGB"))
            self.assertEqual(im.tobytes(), room.crop((160, 96, 352, 224)).tobytes())
        self.assertEqual((self.object_record("obj010_01")["class"],
                          self.object_record("obj010_01")["room_sha256"]), ("identical", room_sha))
        record = self.object_record("obj010_02")
        self.assertEqual((record["class"], record["promoted"], record["context"]),
                         ("render", True, [0, 0, 128, 128]))
        sprite = self.obj_dst / "obj011_01.png"
        self.assertTrue(a.alpha_matches(sprite, source_tree.open_rgba(
            self.src, next(o for o in self.source.objects if o.key == "obj011_01"))))
        with Image.open(self.obj_dst / "obj012_01.png") as im:        # skip room: nearest copy
            self.assertEqual(im.size, (32, 32))
        self.assertFalse((self.obj_dst / "obj013_01.png").exists())
        code, out, _, stub = self.objects()
        self.assertEqual((code, stub.render.call_count), (0, 0))
        self.assertIn("done 5", out)

    def test_objects_wait_for_their_room_and_follow_its_changes(self):
        self.objects()
        (self.dst / "room_002.png").unlink()
        code, out, _, stub = self.objects("--room", "2")
        self.assertIn("waiting 1", out)
        self.assertEqual(stub.render.call_count, 0)
        self.batch_rooms("--force", transform=lambda im: Image.eval(im, lambda v: min(255, v + 3)))
        code, out, err, stub = self.objects("--room", "1")
        self.assertEqual(code, 0, err)
        self.assertEqual(stub.render.call_count, 2)                    # obj010_02, obj011_01 stale
        self.assertEqual(self.object_record("obj010_01", 2)["room_sha256"],
                         source_tree.file_sha256(self.dst / "room_001.png"))

    def test_a_geometry_rejection_is_retried_with_the_layout_correction(self):
        code, out, _, _ = self.objects("--object", "obj010_02", transform=testkit.shift_right)
        self.assertEqual(code, 0)
        self.assertEqual(load_reviews(self.reviews)["obj010_02"].source, "geometry")
        _, _, _, stub = self.objects("--object", "obj010_02")
        self.assertIn(GEOMETRY_CORRECTION, stub.render.call_args.kwargs["positive"])
        self.assertTrue(self.object_record("obj010_02", 2)["promoted"])

    def test_skip_objects_are_copied_not_rendered(self):
        testkit.write_rooms(self.rooms_file, skip_objects={1: ["obj010_02"]})
        _, out, _, stub = self.objects("--object", "obj010_02")
        self.assertEqual(stub.render.call_count, 0)
        with Image.open(self.obj_dst / "obj010_02.png") as im:
            self.assertEqual(im.size, (192, 128))

    def test_a_failed_object_does_not_stop_the_others(self):
        def render(workflow, **kw):
            if kw["name"].startswith("obj010_02"):
                raise RuntimeError("ComfyUI execution failed")
            return testkit.fake_render()(workflow, **kw)
        code, out, err, stub = self.objects(render=render)
        self.assertEqual(code, 1)
        self.assertIn("ERROR rendering obj010_02", err)
        self.assertTrue((self.obj_dst / "obj011_01.png").is_file())
        self.assertTrue((self.obj_dst / ".quality" / "obj010_02" / "attempt-1.error.txt").is_file())
        stub.sweep.assert_any_call("obj010_02", self.comfy_dir)

    def test_dry_run_lists_without_rendering(self):
        code, out, _, stub = self.objects("--dry-run")
        self.assertEqual((code, stub.render.call_count, stub.is_up.call_count), (0, 0, 0))
        self.assertIn("render    obj010_02 in room_001 -> 192x128", out)
        self.assertIn("identical obj010_01 in room_001", out)
        self.assertFalse(self.obj_dst.exists())
```

(Import `load_reviews` from `rooms_file` and `GEOMETRY_CORRECTION` from `prompts` at the top of the test module if not there.)

`test_scripts.py`: add `("objects", "room=1", "object=obj010_02", "force=1"): "./run_batch.sh objects --room 1 --object obj010_02 --force"` and `("objects-dry-run",): "./run_batch.sh objects --dry-run"`.

- [ ] **Step 2: Run to verify failure**

Run: `make test`
Expected: FAIL/ERROR (`invalid choice: 'objects'`, unknown `--obj-dst`).

- [ ] **Step 3: Implement rooms_file keys**

```python
_REVIEW_KEY = re.compile(r"^(room_\d{3}|obj\d{3,}_[0-9A-F]{2})$")
```

Give `_read_mapping(path, optional, key=_KEY, label="a room key (room_NNN)")` the pattern and its error label; `load_reviews` calls it with `key=_REVIEW_KEY, label="a room or object key"`. The error reads `f"{path}: {k!r} is not {label}"`.

- [ ] **Step 4: Implement the object note**

In `prompts.py`:

```python
OBJECT_NOTE = '''This image is a close crop of a finished high-definition room around one object of the original. Only the object's area is repainted; everything around it is already finished. Recreate the object in the same style, light, colour and detail as its surroundings, keeping its outline, size and position exactly where the reference shows it, with no halo or edge between it and the room.'''
```

- [ ] **Step 5: Implement the driver**

Constants and options:

```python
OBJ_DST_ROOT = _env_path("DIG_OBJ_DST", REPO / "data" / "objects-ai")
```

In `common(p)`:

```python
        p.add_argument("--obj-dst", type=Path, default=OBJ_DST_ROOT,
                       help="object output tree (default: %(default)s, or DIG_OBJ_DST)")
        p.add_argument("--object", action="append", metavar="KEY",
                       help="process object KEY (objNNN_SS) only (repeatable)")
```

Change `room_status(args, room, reviews)` to `room_status(dst, item, reviews)` (use `audit_dir(dst, item)` and `(dst / item.out_name).is_file()`), `corrections_for(args, room, reviews)` to `corrections_for(dst, item, reviews)`, `fallback_for(args, room, workflow)` to `fallback_for(dst, item, workflow)`; update `cmd_batch` to pass `args.dst`.

Add:

```python
def object_selection(args):
    """--object keys when given, else the objects of the selected rooms."""
    if args.object:
        return source_tree.select_objects(args.source, args.object)
    return source_tree.objects_of(args.source, [room.number for room in selection(args)])


def object_status(args, obj, reviews, room_sha):
    """room_status of the object, plus stale: done, but painted over a room
    output other than the current one (room_sha)."""
    status, attempt = room_status(args.obj_dst, obj, reviews)
    if status == "done":
        record = promoted_record(audit_dir(args.obj_dst, obj),
                                 source_tree.file_sha256(args.obj_dst / obj.out_name))
        if record is None or record.get("room_sha256") != room_sha:
            return "stale", attempt
    return status, attempt


def write_nearest_object(args, obj):
    """A skipped object's output: its source enlarged 4x, nearest neighbour."""
    save_image_atomic(source_tree.open_rgba(args.src, obj).convert(obj.mode)
                      .resize(obj.out_size, Image.Resampling.NEAREST), args.obj_dst / obj.out_name)


def render_object(args, workflow, obj, room, entry, corrections, cls):
    """Write one object image over its promoted room: an identical object is
    the room's crop; a render object is repainted in its context window,
    composed through its mask and checked. Promote it when the check holds.

    Returns (attempt, GeometryResult). A render that raises writes
    attempt-N.error.txt and no record, as render_room does.
    """
    audit = audit_dir(args.obj_dst, obj)
    audit.mkdir(parents=True, exist_ok=True)
    attempt = latest_attempt(audit) + 1
    tiles = audit / f"attempt-{attempt}.tiles"
    tiles.mkdir()
    seed = SEED + attempt - 1
    started = time.monotonic()
    stage = None
    try:
        room_image = source_tree.open_rgba(args.src, room)
        obj_image = source_tree.open_rgba(args.src, obj)
        room_path = args.dst / room.out_name
        record = {"attempt": attempt, "class": cls, "room": room.key,
                  "room_sha256": source_tree.file_sha256(room_path)}
        with Image.open(room_path) as im:
            room_hd = im.convert("RGB")
        if cls == "identical":
            out = object_geometry.identical_output(room_hd, obj.x, obj.y, obj.width, obj.height)
            result = geometry_check.GeometryResult((0.0, 0.0), (), 1.0, (), (), ())
        else:
            inputs = object_geometry.object_inputs(room_hd, room_image, obj_image, obj.x, obj.y,
                                                   args.dedither)
            style = entry.style or "painted"
            positive = render_prompt(entry.caption, entry.kind, corrections, OBJECT_NOTE,
                                     workflow.reference, style)
            negative = negative_prompt(style)
            paths = {}
            for part, image in (("guide", inputs.guide), ("composite", inputs.composite),
                                ("mask", inputs.mask)):
                paths[part] = tiles / f"object.{part}.png"
                image.save(paths[part])
            stage = "object"
            saved = comfy_client.render_window(
                workflow, guide=paths["guide"], composite=paths["composite"], mask=paths["mask"],
                reference="composite", positive=positive, negative=negative, seed=seed,
                name=f"{obj.key}_a{attempt}-object", url=COMFY_URL, comfy_dir=COMFY_DIR)
            raw = tiles / "object.png"
            shutil.move(saved, raw)
            with Image.open(raw) as im:
                rendered = im.convert("RGB")
            if rendered.size != inputs.composite.size:
                raise RuntimeError(f"object came back {rendered.width}x{rendered.height}, "
                                   f"expected {inputs.composite.width}x{inputs.composite.height}")
            stage = None
            write_atomic(audit / f"attempt-{attempt}.prompt.txt",
                         f"workflow: {workflow.name}\n\n--- object ---\n{positive}\n\n"
                         f"--- negative ---\n{negative}\n")
            final = object_geometry.compose(rendered, inputs, args.match_strength)
            final.save(audit / f"attempt-{attempt}.png")
            result = object_geometry.check_object(final, inputs)
            out = object_geometry.object_crop(final, inputs, obj.x, obj.y, obj.width, obj.height)
            record.update({"workflow": workflow.name, "seed": seed, "reference": "composite",
                           "dedither": args.dedither, "context": list(inputs.box),
                           "match": {"rule": colour_match.RULE,
                                     "strength": args.match_strength}})
        if obj.has_alpha:
            out = room_geometry.with_alpha(out, obj_image)
        sha = None
        if result.passed:
            dst = args.obj_dst / obj.out_name
            save_image_atomic(out, dst)
            sha = source_tree.file_sha256(dst)
        record.update({"geometry": result.as_dict(), "promoted": result.passed,
                       "output_sha256": sha, "seconds": round(time.monotonic() - started, 1)})
        write_atomic(audit / f"attempt-{attempt}.json", json.dumps(record, indent=2))
        return attempt, result
    except BaseException as error:
        write_atomic(audit / f"attempt-{attempt}.error.txt",
                     f"workflow: {workflow.name}\nseed: {seed}\nwindow: {stage or 'none'}\n"
                     f"seconds: {time.monotonic() - started:.1f}\n"
                     f"error: {type(error).__name__}: {error}\n")
        raise


def object_stuck_line(obj):
    return (f"  STUCK   {obj.key}: rejected {MAX_ATTEMPTS} times - fix {obj.room_key}'s caption, "
            f"or add it to skip_objects, then: make objects object={obj.key} force=1")


def cmd_objects(args):
    workflow = comfy_client.WORKFLOWS[args.workflow]
    objs = object_selection(args)
    entries = load_entries(args)
    reviews = load_reviews(args.reviews, optional=True)
    rooms = {room.number: room for room in args.source.rooms}
    copies, work, waiting, bad, stuck = [], [], [], [], []
    done = 0
    for obj in objs:
        if obj.placement_error:
            bad.append(obj)
            continue
        room = rooms[obj.room]
        entry = entries[room.key]
        if entry.kind == "skip" or obj.key in entry.skip_objects:
            if args.force or not (args.obj_dst / obj.out_name).is_file():
                copies.append(obj)
            else:
                done += 1
            continue
        if room_status(args.dst, room, reviews)[0] != "done":
            waiting.append(obj)
            continue
        room_sha = source_tree.file_sha256(args.dst / room.out_name)
        status, _ = object_status(args, obj, reviews, room_sha)
        if not args.force and status == "done":
            done += 1
            continue
        obj_workflow = workflow
        if not args.force and status == "stuck":
            obj_workflow = fallback_for(args.obj_dst, obj, workflow)
            if obj_workflow is None:
                stuck.append(obj)
                continue
        cls = object_geometry.classify(source_tree.open_rgba(args.src, obj),
                                       source_tree.open_rgba(args.src, room), obj.x, obj.y)
        work.append((obj, room, entry, cls, corrections_for(args.obj_dst, obj, reviews),
                     obj_workflow))

    renders = [item for item in work if item[3] == "render"]
    print(f"workflow: {workflow.name}  match strength: {args.match_strength}")
    print(f"{len(objs)} object(s): render {len(renders)}, identical {len(work) - len(renders)}, "
          f"copy {len(copies)}, waiting {len(waiting)}, done {done}, stuck {len(stuck)}, "
          f"badplace {len(bad)}")
    for obj in bad:
        print(f"  BADPLACE {obj.key}: {obj.placement_error}", file=sys.stderr)
    if args.dry_run:
        for obj in copies:
            w, h = obj.out_size
            print(f"  copy      {obj.key} -> {w}x{h} nearest")
        for obj, room, _, cls, corrections, obj_workflow in work:
            w, h = obj.out_size
            extras = [f"{len(corrections)} correction(s)"] if corrections else []
            if obj_workflow is not workflow:
                extras.append(f"fallback: {obj_workflow.name}")
            print(f"  {cls:9} {obj.key} in {room.key} -> {w}x{h}"
                  + ("  " + "; ".join(extras) if extras else ""))
        for obj in waiting:
            print(f"  waiting   {obj.key}: {obj.room_key} is not done")
        for obj in stuck:
            print(object_stuck_line(obj))
        return 0
    args.obj_dst.mkdir(parents=True, exist_ok=True)
    for obj in copies:
        write_nearest_object(args, obj)
        print(f"  copy      {obj.key} (nearest 4x)")
    if not work:
        for obj in stuck:
            print(object_stuck_line(obj), file=sys.stderr)
        return 1 if stuck else 0
    for needed in dict.fromkeys(item[5] for item in renders):
        code = comfy_preflight(needed, args.no_memory_check)
        if code is not None:
            return code
    try:
        promoted = rejected = failed = 0
        for i, (obj, room, entry, cls, corrections, obj_workflow) in enumerate(work, 1):
            note = f" with {len(corrections)} correction(s)" if corrections else ""
            print(f"[{i}/{len(work)}] {cls} {obj.key} ({room.key}){note}", flush=True)
            try:
                attempt, result = render_object(args, obj_workflow, obj, room, entry,
                                                corrections, cls)
            except KeyboardInterrupt:
                comfy_client.sweep_outputs(obj.key, COMFY_DIR)
                raise
            except Exception as error:
                failed += 1
                swept = comfy_client.sweep_outputs(obj.key, COMFY_DIR)
                extra = f" (removed {swept} stray output file(s))" if swept else ""
                print(f"  ERROR rendering {obj.key}: {error}{extra}", file=sys.stderr, flush=True)
                continue
            if result.passed:
                promoted += 1
                print(f"  promoted attempt {attempt}", flush=True)
                continue
            rejected += 1
            reviews[obj.key] = Review(attempt, False, result.issues, "geometry")
            save_reviews(args.reviews, reviews)
            print(f"  rejected attempt {attempt}: " + "; ".join(result.issues), flush=True)
            if room_status(args.obj_dst, obj, reviews)[0] == "stuck":
                if fallback_for(args.obj_dst, obj, workflow) is None:
                    stuck.append(obj)
        for obj in stuck:
            print(object_stuck_line(obj), file=sys.stderr)
        print(f"done: promoted={promoted} rejected={rejected} failed={failed} "
              f"copied={len(copies)} done={done} stuck={len(stuck)} badplace={len(bad)}")
        return 1 if failed or stuck else 0
    finally:
        if renders:
            free_comfy_models()
```

Imports: `import object_geometry`; from prompts add `OBJECT_NOTE`, `negative_prompt`. Parser:

```python
    objects = sub.add_parser("objects", help="render room objects over their promoted rooms")
    common(objects)
    render_options(objects)
    objects.set_defaults(func=cmd_objects)
```

Update the module docstring's stage list with `objects`.

- [ ] **Step 6: Makefile**

```make
object ?=
obj_dst ?=
ARGS = $(foreach r,$(room),--room $(r)) $(foreach o,$(object),--object $(o)) \
       $(if $(src),--src "$(src)") $(if $(dst),--dst "$(dst)") $(if $(obj_dst),--obj-dst "$(obj_dst)")
```

```make
objects-dry-run: install ## [STEP 2c] Preview what objects would do (room=, object=, workflow=, force=1)
	./run_batch.sh objects --dry-run $(ARGS) $(BATCH_ARGS)

objects: install ## [STEP 2b] Render room objects over their promoted rooms; stop vLLM first (room=, object=, workflow=, strength=, dedither=, memcheck=0, force=1)
	./run_batch.sh objects $(ARGS) $(BATCH_ARGS)
```

Add both to `.PHONY`.

- [ ] **Step 7: Run everything**

Run: `make check && make test`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add thedig-texture-enhancement
git commit -m "feat(kit): objects stage: repaint room objects in context over their promoted room

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Object review and verify

**Files:**
- Modify: `prompts.py` (`OBJECT_REVIEW_BATCH`, `OBJECT_REVIEW_QUESTION`, `pair_image`, `_json_text`, `_verdict`, `parse_object_reviews`, `review_objects`; `parse_review` refactored onto `_json_text`/`_verdict`)
- Modify: `dig_recreate.py` (`cmd_review` reviews objects after rooms; `cmd_verify` audits objects)
- Modify: `testkit.py` (`vlm_stub(..., objects=None)`)
- Test: `test_prompts.py`, `test_dig_recreate.py`

**Interfaces:**
- Produces: `prompts.OBJECT_REVIEW_BATCH = 8`; `prompts.pair_image(guide, render, gap=16) -> Image`; `prompts.parse_object_reviews(text, keys) -> dict[key, {"accepted", "issues"}]`; `prompts.review_objects(items, overview, style, http, base_url, model, key) -> dict` where `items` is `[(key, guide, render), ...]`; `dig_recreate.verify_object(args, obj, entries, rooms) -> (code, detail) | None`; testkit's `vlm_stub(objects=callable)` patches `dig_recreate.review_objects`.

- [ ] **Step 1: Write the failing tests**

`test_prompts.py`:

```python
    def test_parse_object_reviews(self):
        text = ('```json\n{"objects": {"obj010_02": {"accepted": false, "issues": ["a halo"]},'
                ' "obj011_01": {"accepted": true, "issues": []},'
                ' "obj014_01": {"accepted": true, "issues": ["contradiction"]},'
                ' "obj999_01": {"accepted": true, "issues": []}}}\n```')
        result = p.parse_object_reviews(text, ["obj010_02", "obj011_01", "obj014_01", "obj012_01"])
        self.assertEqual(result, {"obj010_02": {"accepted": False, "issues": ["a halo"]},
                                  "obj011_01": {"accepted": True, "issues": []}})
        with self.assertRaisesRegex(ValueError, "objects mapping"):
            p.parse_object_reviews('{"accepted": true}', ["obj010_02"])
        pair = p.pair_image(Image.new("RGB", (40, 30)), Image.new("RGB", (40, 30)))
        self.assertEqual(pair.size, (96, 30))
```

`test_dig_recreate.py`, in `ObjectTests`:

```python
    def test_review_judges_rendered_objects_per_room(self):
        self.objects()
        seen = []

        def review(items, overview, style, *rest):
            seen.append(sorted(k for k, _, _ in items))
            return {"obj010_02": {"accepted": False, "issues": ["a halo around the lever"]},
                    "obj011_01": {"accepted": True, "issues": []}}

        with testkit.vlm_stub(review=lambda *a_, **k: {"accepted": True, "issues": []},
                              objects=review, free=None):
            code, out, err = self.run_cli("review")
        self.assertEqual(code, 0, err)
        self.assertEqual(seen, [["obj010_02", "obj011_01"], ["obj014_01"]])
        reviews = load_reviews(self.reviews)
        self.assertEqual((reviews["obj010_02"].accepted, reviews["obj011_01"].accepted),
                         (False, True))
        self.assertNotIn("obj014_01", reviews)                         # no verdict: unreviewed
        self.assertNotIn("obj010_01", reviews)                         # identical: never reviewed
        _, _, _, stub = self.objects("--object", "obj010_02")
        self.assertIn("a halo around the lever", stub.render.call_args.kwargs["positive"])

    def test_verify_audits_objects(self):
        self.objects()
        code, out, _ = self.run_cli("verify")
        self.assertEqual(code, 1)
        self.assertIn("BADPLACE   obj013_01", out)
        self.assertNotIn("obj010_02", out)
        self.batch_rooms("--force", transform=lambda im: Image.eval(im, lambda v: min(255, v + 3)))
        code, out, _ = self.run_cli("verify", "--room", "1")
        self.assertIn("STALE      obj010_02", out)
        Image.new("RGB", (32, 32)).save(self.obj_dst / "obj011_01.png")
        code, out, _ = self.run_cli("verify", "--object", "obj011_01")
        self.assertIn("WRONGSIZE  obj011_01", out)
        self.assertNotIn("room_", out)
```

- [ ] **Step 2: Run to verify failure**

Run: `make test`
Expected: FAIL/ERROR.

- [ ] **Step 3: Implement the prompts**

```python
OBJECT_REVIEW_BATCH = 8     # objects per VLM request: each is one image, plus the room overview

OBJECT_REVIEW_QUESTION = '''Each of the first {count} images shows one object of a room from a 1995 adventure game as two halves side by side: on the left the authoritative original with a little of the room around it (smoothed and enlarged), on the right the same crop after the object was recreated in high definition over the already recreated room. The last image is the whole recreated room, downscaled. The objects are, in order: {keys}.
Reject an object when:
1. layout: its outline, size or position changed, part of it is missing, or something was added around it;
2. blending: it does not match the surrounding room's style, light or colour, or a visible edge or halo separates it from the room;
3. style: {style_rule}.
Return ONLY JSON: {"objects": {"<key>": {"accepted": true or false, "issues": ["one specific problem and a concrete correction"]}}} with one entry for each object key above. Use an empty issues list when accepted. At most three issues per object.'''


def pair_image(guide, render, gap=16):
    """`guide` and `render` side by side on black, `gap` px apart."""
    out = Image.new("RGB", (guide.width + gap + render.width, max(guide.height, render.height)))
    out.paste(guide.convert("RGB"), (0, 0))
    out.paste(render.convert("RGB"), (guide.width + gap, 0))
    return out


def _json_text(text, required):
    """The JSON object in the VLM's answer that has the key `required`,
    tolerating fences and chatter."""
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for i in range(1, len(parts), 2):
            chunk = parts[i].strip()
            if chunk.startswith("json"):
                chunk = chunk[4:].strip()
            try:
                value = json.loads(chunk)
            except ValueError:
                continue
            if isinstance(value, dict) and required in value:
                return chunk
    elif not text.startswith("{") and "{" in text and "}" in text:
        return text[text.find("{"):text.rfind("}") + 1].strip()
    return text


def _verdict(value):
    """{"accepted", "issues"} from one verdict mapping, or ValueError."""
    if not isinstance(value, dict) or type(value.get("accepted")) is not bool:
        raise ValueError("VLM review must contain a boolean accepted verdict")
    issues = value.get("issues")
    if not isinstance(issues, list) or any(not isinstance(x, str) or not x.strip() for x in issues):
        raise ValueError("VLM review must contain a list of nonempty issue strings")
    if value["accepted"] != (not issues):
        raise ValueError("VLM review verdict contradicts its issues")
    return {"accepted": value["accepted"], "issues": issues}


def parse_review(text):
    """{"accepted", "issues"} from the VLM's answer, tolerating fences and chatter."""
    return _verdict(json.loads(_json_text(text, "accepted")))


def parse_object_reviews(text, keys):
    """{key: {"accepted", "issues"}} for each of `keys` the answer judges
    validly. A key it misses, an invalid or contradictory entry, and a key not
    asked about are left out."""
    value = json.loads(_json_text(text, "objects"))
    objects = value.get("objects") if isinstance(value, dict) else None
    if not isinstance(objects, dict):
        raise ValueError("VLM object review must contain an objects mapping")
    result = {}
    for key in keys:
        try:
            result[key] = _verdict(objects.get(key))
        except ValueError:
            continue
    return result


def review_objects(items, overview, style, http, base_url, model, key):
    """The VLM's verdicts on up to OBJECT_REVIEW_BATCH objects of one room:
    `items` is [(key, guide crop, render crop), ...]."""
    keys = [k for k, _, _ in items]
    question = (OBJECT_REVIEW_QUESTION.replace("{count}", str(len(items)))
                .replace("{keys}", ", ".join(keys))
                .replace("{style_rule}", STYLE_RULES.get(style, STYLE_RULES["painted"])))
    images = [pair_image(guide, render) for _, guide, render in items] + [overview]
    return parse_object_reviews(_ask(question, images, http, base_url, model, key,
                                     json_mode=True, max_tokens=300 * len(items) + 200,
                                     timeout=REVIEW_TIMEOUT), keys)
```

- [ ] **Step 4: Implement the driver**

`testkit.vlm_stub(..., objects=None)`: when given, `mocks.objects = stack.enter_context(patch.object(a, "review_objects", side_effect=objects))`.

In `cmd_review`, after the rooms loop and before the summary, review objects:

```python
    rooms_by_number = {room.number: room for room in args.source.rooms}
    by_room = {}
    for obj in object_selection(args):
        if obj.placement_error:
            continue
        audit = audit_dir(args.obj_dst, obj)
        attempt = latest_attempt(audit)
        record = read_record(audit, attempt) if attempt else None
        review = current_review(reviews, obj, attempt)
        if (record is None or not record.get("promoted") or record.get("class") != "render"
                or not (args.obj_dst / obj.out_name).is_file()
                or (review is not None and review.attempt >= attempt and not args.force)):
            continue
        by_room.setdefault(obj.room, []).append((obj, attempt))
    for number, todo in sorted(by_room.items()):
        room = rooms_by_number[number]
        entry = entries[room.key]
        with Image.open(args.dst / room.out_name) as im:
            overview = im.convert("RGB")
        for start in range(0, len(todo), OBJECT_REVIEW_BATCH):
            chunk = todo[start:start + OBJECT_REVIEW_BATCH]
            print(f"review {len(chunk)} object(s) of {room.key}", flush=True)
            items = []
            for obj, attempt in chunk:
                audit = audit_dir(args.obj_dst, obj)
                with Image.open(audit / f"attempt-{attempt}.tiles" / "object.guide.png") as g, \
                        Image.open(audit / f"attempt-{attempt}.png") as r:
                    items.append((obj.key, g.convert("RGB"), r.convert("RGB")))
            try:
                verdicts = review_objects(items, overview, entry.style or "painted",
                                          comfy_client.http_json, VLM_BASE_URL, VLM_MODEL,
                                          VLM_API_KEY)
            except Exception as error:
                failed += len(chunk)
                for obj, attempt in chunk:
                    write_atomic(audit_dir(args.obj_dst, obj)
                                 / f"attempt-{attempt}.review-error.txt", str(error))
                print(f"  ERROR reviewing {room.key}'s objects: {error}", file=sys.stderr,
                      flush=True)
                continue
            for obj, attempt in chunk:
                verdict = verdicts.get(obj.key)
                if verdict is None:
                    print(f"  {obj.key}: no verdict; it stays unreviewed", flush=True)
                    continue
                write_atomic(audit_dir(args.obj_dst, obj) / f"attempt-{attempt}.review.json",
                             json.dumps(verdict, indent=2))
                reviews[obj.key] = Review(attempt, verdict["accepted"],
                                          tuple(verdict["issues"]), "review")
                save_reviews(args.reviews, reviews)
                if verdict["accepted"]:
                    accepted += 1
                    print(f"  {obj.key}: accepted")
                else:
                    rejected += 1
                    print(f"  {obj.key}: rejected: " + "; ".join(verdict["issues"]))
```

(`rooms = selection(args)` at the top of `cmd_review` becomes `[] if args.object and not args.room else selection(args)` so `--object` alone reviews only objects.)

`cmd_verify`:

```python
def verify_object(args, obj, entries, rooms):
    """(code, detail) for an object output that breaks the contract, or None."""
    if obj.placement_error:
        return "BADPLACE", obj.placement_error
    dst = args.obj_dst / obj.out_name
    if not dst.is_file():
        return "MISSING", ""
    info = image_info(dst)
    if info is None:
        return "UNREADABLE", ""
    if info[0] != obj.out_size:
        want = obj.out_size
        return "WRONGSIZE", f"is {info[0][0]}x{info[0][1]}, expected {want[0]}x{want[1]}"
    if info[1] != obj.mode:
        return "WRONGMODE", f"is {info[1]}, expected {obj.mode}"
    if obj.has_alpha and not alpha_matches(dst, source_tree.open_rgba(args.src, obj)):
        return "WRONGALPHA", "the alpha is not the source's, 4x nearest"
    room = rooms[obj.room]
    entry = entries[room.key]
    if entry.kind == "skip" or obj.key in entry.skip_objects:
        return None
    record = promoted_record(audit_dir(args.obj_dst, obj), source_tree.file_sha256(dst))
    if record is None:
        return "UNRECORDED", f"no attempt record promoted this file - run: make objects object={obj.key} force=1"
    room_out = args.dst / room.out_name
    if not room_out.is_file() or record.get("room_sha256") != source_tree.file_sha256(room_out):
        return "STALE", f"painted over an older {room.key} - run: make objects object={obj.key}"
    return None
```

In `cmd_verify`: `rooms = [] if args.object and not args.room else selection(args)`; after the rooms loop:

```python
    by_number = {room.number: room for room in args.source.rooms}
    objs = object_selection(args)
    for obj in objs:
        problem = verify_object(args, obj, entries, by_number)
        if problem is None:
            continue
        bad += 1
        code, detail = problem
        print(f"{code:10} {obj.key}" + (f"  {detail}" if detail else ""))
    print(f"verify: {len(rooms)} room(s), {len(objs)} object(s), {bad} problem(s)")
```

replacing the old summary line (update the existing verify test's expected summary text accordingly).

- [ ] **Step 5: Run everything**

Run: `make check && make test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add thedig-texture-enhancement
git commit -m "feat(kit): review rendered objects per room and audit objects in verify

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: Documentation

**Files:**
- Create: `thedig-texture-enhancement/README.md`, `thedig-texture-enhancement/AGENTS.md`, `thedig-texture-enhancement/CLAUDE.md` (a symlink to `AGENTS.md`)
- Modify: `~/code/thedig-hd-bundle/README.md` only if a command or path changed

**Interfaces:**
- Consumes: every earlier task's commands, files and constants; `NOTES.md`.

- [ ] **Step 1: Write README.md (the user view)**

Model it on the Atlantis kit's README section by section, with these Dig contents:
- Title "The Dig Background and Object Regeneration"; what it regenerates (111 rooms, 642 object images, exactly 4x) and with which models (the same two workflows, Qwen3.8-27B).
- Input `../thedig-textures-exporter/out/` (0.2.0, `DIG_SRC`); outputs `data/rooms-ai/room_NNN.png`, `data/objects-ai/objNNN_SS.png` (`DIG_DST`, `DIG_OBJ_DST`). Personal use only; never commit art.
- Pipeline diagram (spec §4) and steps: `make caption` → edit `rooms.yaml` (caption, `style`, `skip_objects`) → `make batch` → `make objects` → `make review` → repeat batch/objects for rejects → `make verify`.
- Swapping services (copy the Atlantis table and the `/free` curl).
- Rooms: kinds table (§7), styles, `skip_objects`; transparent rooms keep exact alpha; tall rooms render in a padded grid.
- Objects: classes (identical, render, skip), `waiting`, `stale`, `BADPLACE`, the context window.
- Checks: the room and object gates (§11); STUCK and the fallback (Atlantis text, `make objects object=… force=1` for objects).
- Outputs and the audit folder (both trees).
- Commands table (§13 plus `objects-dry-run`, `dedither=`, `object=`, `obj_dst=`).
- Setup (the Atlantis model list verbatim) and the project structure table including `object_geometry.py` and `NOTES.md`.

- [ ] **Step 2: Write AGENTS.md (the agent view)**

Adapt the Atlantis `AGENTS.md` §1–§5 to the Dig names and add:
- §1 rules: the source is thedig-textures-exporter ≥ 0.2.0; outputs RGB or RGBA per `has_alpha` with exact alpha; objects are painted only over a `done` room and record `room_sha256`; `stale`/`waiting`/`BADPLACE` semantics; never loosen the gate.
- §2 module table with `object_geometry.py` ("classification, context window, object inputs and mask, compose, crop, check" / "must not talk to services or know files").
- §3 render path: padding, 2D grid, L masks, transparent fill, alpha attach; the object path (Task 10's steps in order); the node-id paragraphs copied from Atlantis unchanged.
- §4 prompts: MEDIUM → style, the two rule sets and negatives, `OBJECT_NOTE`, the object review batch of 8.
- §5 testing: the Atlantis rules, `DEFAULT_ROOMS` and `DEFAULT_OBJECTS` described, the real-corpus classes (source_tree, room gate, object classification).
- §6: "Live checks, spikes and runs are in `NOTES.md`."
- Pointers to the bundle-root spec and plan.

Then `ln -s AGENTS.md CLAUDE.md`.

- [ ] **Step 3: Check the docs against the code**

Run: `make help` and compare every target and argument with the README's command table; `grep -n "ATL_\|atl_\|Atlantis" README.md AGENTS.md` must only hit sentences that name the Atlantis kit as the origin.

- [ ] **Step 4: Commit**

```bash
git add thedig-texture-enhancement/README.md thedig-texture-enhancement/AGENTS.md thedig-texture-enhancement/CLAUDE.md README.md
git commit -m "docs(kit): README, AGENTS.md for the Dig kit

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: Object spike, then the full run (manual, GB10)

**Files:**
- Modify: `thedig-texture-enhancement/NOTES.md`, `rooms.yaml` (captions, styles, skip_objects)

**Interfaces:**
- Consumes: everything. The spec placed the multi-state flicker check in the spike (§14); it runs here because it needs the object stage.

- [ ] **Step 1: Object spike**

1. Pick the spike room with the most object states: `.venv/bin/python -c "import source_tree as s, collections; src=s.load('../thedig-textures-exporter/out'); c=collections.Counter(o.key[:-3] for o in src.objects if o.room in (2,4,11,27,43,60)); print(c.most_common(3))"`.
2. ComfyUI up: `make objects room=<N> dst=data/spike/<chosen> obj_dst=data/spike/objects`.
3. Show the user the states of the multi-state object as a strip (each `objNNN_SS.png` in order) and as a flip-book GIF (`Image.save(..., save_all=True, duration=150)`) under `data/spike/`. Also show two single-state render objects over their room.
4. Record in `NOTES.md` under "## Object spike": the counts (identical / render / copy / badplace), seconds per object, gate results, and the user's verdict on flicker.
5. **If the user judges it flickers:** stop and write the chained-states addition (spec §10.4: state k > 01 uses state k−1's promoted render in the composite's object area, at denoise 0.6) as a new task in this plan, with tests, before the full run. Do not build it otherwise.

- [ ] **Step 2: Full run**

1. vLLM up: `make caption`. Read every caption against its room image and fix misreadings and `style` (budget: the Atlantis run changed two thirds of its captions). Check each insert's TEXT section.
2. vLLM down, ComfyUI up: `make dry-run`, then `make batch`. Repeat `make batch` until nothing is new, rejected or failed; handle STUCK rooms by caption edits.
3. `make objects`; repeat until nothing is new, rejected or failed. Add hopeless objects to `skip_objects` with the user's agreement.
4. ComfyUI down, vLLM up: `make review`. Then batch/objects again for rejects; repeat review.
5. `make verify` → `verify: 111 room(s), 642 object(s), <n> problem(s)` where the only problems are `BADPLACE` objects listed in `NOTES.md`.
6. Record the run in `NOTES.md` (Atlantis's "Full run" format: first-attempt rejections, fallback promotions, review rejections and false ones, caption leaks).

- [ ] **Step 3: Commit**

```bash
git add thedig-texture-enhancement/NOTES.md thedig-texture-enhancement/rooms.yaml
git commit -m "docs(kit): record the object spike and the full run

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4: Finish the branch**

Use superpowers:finishing-a-development-branch to merge `feat/dig-regeneration` into `main` (and push only if the user approved the remote in Task 1 Step 6).
