#!/usr/bin/env python3
"""Regenerate The Dig room backgrounds as
painted high-definition art at exactly 4x, re-import-safe.

Human-paced stages, each a subcommand:

  caption   observe every scene and insert room with the local vLLM and write
            its caption into rooms.yaml
  batch     render every captioned room through ComfyUI window by window,
            stitch, colour-match, fix up and check its geometry; promote it into
            the output tree when the geometry holds; re-render the rooms
            reviews.yaml rejects; write skip rooms as a nearest-neighbour 4x
  objects   repaint every room object over its promoted room, in its context
            window; promote it when its geometry holds; re-render the objects
            reviews.yaml rejects; write skip objects as a nearest-neighbour 4x
  review    compare every promoted room with its source through the vLLM and
            write reviews.yaml
  verify    audit the output tree against the manifest, the 4x rule and the
            attempt records

The source tree is thedig-textures-exporter's output; its manifest.json (read by
source_tree) decides which rooms and objects exist. Services are external: vLLM
(Qwen/Qwen3.8-27B on :8000) and ComfyUI (:8188) are started by the user; this
driver only checks that they answer.
"""
import argparse
import json
import os
import re
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path

from PIL import Image

import colour_match
import comfy_client
import geometry_check
import object_geometry
import room_geometry
import source_tree
from prompts import (GEOMETRY_CORRECTION, OBJECT_NOTE, SEAM_NOTE, OBJECT_REVIEW_BATCH,
                     caption_room, medium_style, negative_prompt, render_prompt, review_objects,
                     review_room, room_wide_caption, vlm_is_serving, window_note)
from rooms_file import (Review, RoomsFileError, check_coverage, load_reviews, load_rooms,
                        save_reviews, save_rooms)
from source_tree import SourceError

REPO = Path(__file__).resolve().parent


def _env_path(name, default):
    return Path(os.environ.get(name) or default).expanduser()


SRC_ROOT = _env_path("DIG_SRC", REPO.parent / "thedig-textures-exporter" / "out")
DST_ROOT = _env_path("DIG_DST", REPO / "data" / "rooms-ai")
OBJ_DST_ROOT = _env_path("DIG_OBJ_DST", REPO / "data" / "objects-ai")
ROOMS_FILE = _env_path("DIG_ROOMS", REPO / "rooms.yaml")
REVIEWS_FILE = _env_path("DIG_REVIEWS", REPO / "reviews.yaml")
COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
COMFY_DIR = _env_path("COMFY_DIR", Path.home() / "ComfyUI")
VLM_BASE_URL = os.environ.get("VLM_BASE_URL", "http://127.0.0.1:8000/v1")
VLM_MODEL = os.environ.get("VLM_MODEL", "Qwen/Qwen3.8-27B")
VLM_API_KEY = os.environ.get("VLM_API_KEY", "")
MEMORY_FLOOR_GB = 45
SEED = 42                   # attempt N of a room uses SEED + N - 1 for every window
MAX_ATTEMPTS = 4            # a room with this many judged attempts, the latest rejected, waits
DEFAULT_MATCH_STRENGTH = 0.5
REFERENCE = "guide"         # what a window's encoder sees: "guide" or "composite"
SCALE = source_tree.SCALE
_ATTEMPT = re.compile(r"^attempt-(\d+)(\.|$)")


class UsageError(Exception):
    """Bad arguments or a precondition the user must fix; reported without a traceback."""


def fail(msg):
    print(f"error: {msg}", file=sys.stderr)
    return 2


def write_atomic(path, text):
    """Write `text` to `path` through <path>.tmp and a rename."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def save_image_atomic(image, path):
    """Save `image` as a PNG at `path` through <path>.pending and a rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + ".pending")
    image.save(pending, format="PNG")
    os.replace(pending, path)


def selection(args):
    return source_tree.select(args.source, args.room)


def load_entries(args):
    """rooms.yaml, checked to cover exactly the manifest's rooms."""
    entries = load_rooms(args.rooms_file)
    check_coverage(entries, [room.key for room in args.source.rooms], args.rooms_file)
    return entries


# ---- audit folder -----------------------------------------------------------

def audit_dir(dst_root, room):
    return dst_root / ".quality" / room.key


def latest_attempt(audit):
    """The highest N among the audit folder's attempt-N.* entries, 0 when none.
    A failed attempt leaves attempt-N.tiles/ behind and still uses up N."""
    if not audit.is_dir():
        return 0
    return max((int(m.group(1)) for p in audit.iterdir() if (m := _ATTEMPT.match(p.name))),
               default=0)


def read_record(audit, attempt):
    """attempt-N.json as a mapping, or None when it is missing or unreadable."""
    try:
        value = json.loads((audit / f"attempt-{attempt}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def current_review(reviews, room, latest):
    """reviews.yaml's verdict on the room, or None when there is none or it is
    stale: an attempt later than the audit folder's latest, left behind when
    the folder was cleared."""
    review = reviews.get(room.key)
    return None if review is None or review.attempt > latest else review


def promoted_record(audit, sha):
    """The latest attempt record that promoted an output with this sha256, or None."""
    for attempt in range(latest_attempt(audit), 0, -1):
        record = read_record(audit, attempt)
        if record and record.get("promoted") and record.get("output_sha256") == sha:
            return record
    return None


def image_info(path):
    """(size, mode) of the image at `path`, or None when it does not decode."""
    try:
        with Image.open(path) as im:
            return im.size, im.mode
    except OSError:
        return None


def alpha_matches(path, source):
    """True when the image at `path` is RGBA with `source`'s alpha scaled 4x nearest."""
    want = source.convert("RGBA").getchannel("A").resize(
        (source.width * SCALE, source.height * SCALE), Image.Resampling.NEAREST)
    with Image.open(path) as im:
        return im.mode == "RGBA" and im.getchannel("A").tobytes() == want.tobytes()


# ---- verify -----------------------------------------------------------------

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


def cmd_verify(args):
    rooms = [] if args.object and not args.room else selection(args)
    entries = load_entries(args)
    bad = 0
    for room in rooms:
        dst = args.dst / room.out_name
        info = image_info(dst) if dst.is_file() else None
        want = room.out_size
        if not dst.is_file():
            code, detail = "MISSING", ""
        elif info is None:
            code, detail = "UNREADABLE", ""
        elif info[0] != want:
            code, detail = "WRONGSIZE", f"is {info[0][0]}x{info[0][1]}, expected {want[0]}x{want[1]}"
        elif info[1] != room.mode:
            code, detail = "WRONGMODE", f"is {info[1]}, expected {room.mode}"
        elif room.has_alpha and not alpha_matches(dst, source_tree.open_rgba(args.src, room)):
            code, detail = "WRONGALPHA", "the alpha is not the source's, 4x nearest"
        elif (entries[room.key].kind != "skip" and promoted_record(
                audit_dir(args.dst, room), source_tree.file_sha256(dst)) is None):
            code, detail = "UNRECORDED", ("no attempt record promoted this file - "
                                          f"run: make batch room={room.number} force=1")
        else:
            continue
        bad += 1
        print(f"{code:10} {room.key}" + (f"  {detail}" if detail else ""))
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
    return 1 if bad else 0


# ---- caption ----------------------------------------------------------------

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


def cmd_caption(args):
    rooms = selection(args)
    entries = load_entries(args)
    code = vlm_preflight()
    if code is not None:
        return code
    done = skipped = failed = 0
    for i, room in enumerate(rooms, 1):
        entry = entries[room.key]
        if entry.kind == "skip" or (entry.caption.strip() and not args.force):
            skipped += 1
            continue
        print(f"[{i}/{len(rooms)}] caption {room.key} ({entry.kind})", flush=True)
        try:
            caption = caption_room(caption_images(args.src, room), comfy_client.http_json,
                                   VLM_BASE_URL, VLM_MODEL, VLM_API_KEY)
        except Exception as error:
            failed += 1
            print(f"  ERROR captioning {room.key}: {error}", file=sys.stderr, flush=True)
            continue
        entries[room.key] = replace(entry, caption=caption, style=entry.style or medium_style(caption))
        save_rooms(args.rooms_file, entries)
        done += 1
    print(f"done: captioned={done} skipped={skipped} failed={failed} -> {args.rooms_file}")
    return 1 if failed else 0


# ---- render one room --------------------------------------------------------

def finish_room(canvas, guide, plan, image, strength, has_alpha=False):
    """The stitched 4x `canvas`, cropped to the room's exact 4x size,
    colour-matched toward the guide by `strength`, fixed up, and checked against
    the de-dithered source: (final image, GeometryResult, Boundaries)."""
    if canvas.size != guide.full.size:
        raise RuntimeError(f"the stitched room is {canvas.width}x{canvas.height}, "
                           f"expected {guide.full.width}x{guide.full.height}")
    size = (image.width * SCALE, image.height * SCALE)
    reference = guide.full.crop((0, 0) + size)
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


def render_room(args, workflow, room, entry, corrections):
    """Render one room window by window, stitch it, colour-match it, fix it up
    and check its geometry; promote it into the output tree when that holds.

    Returns (attempt, GeometryResult). Raises when a window fails to render or
    comes back the wrong size: the windows rendered so far stay in the
    attempt's tiles folder, the attempt number stays used, and
    attempt-N.error.txt says what failed. A failed attempt writes no
    attempt-N.json, so it still reads as failed.
    """
    audit = audit_dir(args.dst, room)
    audit.mkdir(parents=True, exist_ok=True)
    attempt = latest_attempt(audit) + 1
    tiles = audit / f"attempt-{attempt}.tiles"
    tiles.mkdir()
    seed = SEED + attempt - 1
    started = time.monotonic()
    stage = None               # the window being rendered
    style = entry.style or "painted"
    negative = negative_prompt(style)
    try:
        image = source_tree.open_rgba(args.src, room)
        guide = room_geometry.build_guide(image, args.dedither)
        plan = room_geometry.plan_room(image)
        canvas = guide.full.copy()
        prompt_log = []

        def render(label, guide_image, composite, mask, note):
            nonlocal stage
            stage = label
            positive = render_prompt(entry.caption, entry.kind, corrections, note,
                                     workflow.reference, style=style)
            prompt_log.append(f"--- {label} ---\n{positive}")
            paths = {}
            for part, image in (("guide", guide_image), ("composite", composite), ("mask", mask)):
                paths[part] = tiles / f"{label}.{part}.png"
                image.save(paths[part])
            saved = comfy_client.render_window(
                workflow, guide=paths["guide"], composite=paths["composite"], mask=paths["mask"],
                reference=REFERENCE, positive=positive, negative=negative, seed=seed,
                # The attempt in the name keeps ComfyUI's cache from answering a rerun of
                # the same inputs and seed with an old render.
                name=f"{room.key}_a{attempt}-{label}", url=COMFY_URL, comfy_dir=COMFY_DIR)
            out = tiles / f"{label}.png"
            shutil.move(saved, out)
            with Image.open(out) as im:
                rendered = im.convert("RGB")
            if rendered.size != guide_image.size:
                raise RuntimeError(f"{label} came back {rendered.width}x{rendered.height}, "
                                   f"expected {guide_image.width}x{guide_image.height}")
            return rendered

        area = (plan.span[0], plan.rows[0], plan.span[1], plan.rows[1])
        for k, window in enumerate(plan.windows):
            left, up = room_geometry.neighbours(plan, k)
            crop, composite, mask = room_geometry.window_inputs(guide.full, canvas, window,
                                                                left, up)
            note = window_note(window.box, area) if len(plan.windows) > 1 else ""
            rendered = render(f"window-{k + 1}", crop, composite, mask, note)
            room_geometry.paste_window(canvas, window, left, up, rendered)
        if plan.wrap:
            strip, composite, mask = room_geometry.seam_inputs(guide.full, canvas, plan)
            room_geometry.apply_seam(canvas, plan,
                                     render("seam", strip, composite, mask, SEAM_NOTE))

        stage = None
        write_atomic(audit / f"attempt-{attempt}.prompt.txt",
                     f"workflow: {workflow.name}\n\n" + "\n\n".join(prompt_log)
                     + f"\n\n--- negative ---\n{negative}\n")
        canvas.save(audit / f"attempt-{attempt}.png")
        final, result, boundaries = finish_room(canvas, guide, plan, image, args.match_strength,
                                                room.has_alpha)
        seams = ([("column", x) for x in boundaries.columns]
                 + [("row", y) for y in boundaries.rows if y < image.height * SCALE])
        for (axis, at), ratio in zip(seams, result.seam_ratios):
            if ratio > geometry_check.SEAM_WARN:
                print(f"  warning: {room.key} seam at 4x {axis} {at}: step {ratio:.1f}x the "
                      "local texture", flush=True)
        sha = None
        if result.passed:
            dst = args.dst / room.out_name
            save_image_atomic(final, dst)
            sha = source_tree.file_sha256(dst)
        m = plan.margins
        record = {
            "attempt": attempt, "workflow": workflow.name, "seed": seed, "reference": REFERENCE,
            "dedither": args.dedither,
            "window_width": room_geometry.WINDOW_WIDTH,
            "window_height": room_geometry.WINDOW_HEIGHT,
            "window_overlap": room_geometry.WINDOW_OVERLAP,
            "windows": [list(w.box) for w in plan.windows],
            "padded_height": plan.height,
            "wrap": [plan.wrap.period, plan.wrap.span] if plan.wrap else None,
            "margins": {"left": m.left, "right": m.right, "top": m.top, "bottom": m.bottom},
            "match": {"rule": colour_match.RULE, "strength": args.match_strength},
            "geometry": result.as_dict(), "promoted": result.passed, "output_sha256": sha,
            "seconds": round(time.monotonic() - started, 1),
        }
        write_atomic(audit / f"attempt-{attempt}.json", json.dumps(record, indent=2))
        return attempt, result
    except BaseException as error:
        write_atomic(audit / f"attempt-{attempt}.error.txt",
                     f"workflow: {workflow.name}\nseed: {seed}\nwindow: {stage or 'none'}\n"
                     f"seconds: {time.monotonic() - started:.1f}\n"
                     f"error: {type(error).__name__}: {error}\n")
        raise


# ---- batch ------------------------------------------------------------------

def memory_available_gb(meminfo=Path("/proc/meminfo")):
    """MemAvailable in GiB. On this unified-memory host it is the GPU budget too."""
    for line in meminfo.read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 2 ** 20
    raise RuntimeError(f"MemAvailable not found in {meminfo}")


def vlm_preflight():
    """None when vLLM serves VLM_MODEL; else fail(...)'s exit code."""
    if not vlm_is_serving(VLM_BASE_URL, VLM_MODEL, comfy_client.http_json, VLM_API_KEY):
        return fail(f"vLLM is not serving {VLM_MODEL} at {VLM_BASE_URL} - start it first")
    return None


def free_comfy_models():
    """Ask ComfyUI to unload its models; a warning, never an error, when it cannot."""
    try:
        comfy_client.free_models(COMFY_URL)
    except Exception as error:
        print(f"warning: failed to free ComfyUI's models: {error}", file=sys.stderr)


def comfy_preflight(workflow, no_memory_check):
    """None when ComfyUI answers, has the model files, knows the node classes
    and there is memory to render; else fail(...)'s exit code."""
    if not comfy_client.is_up(COMFY_URL):
        return fail(f"ComfyUI is not answering at {COMFY_URL} - start it first (make server)")
    missing = comfy_client.missing_model_files(workflow, COMFY_DIR)
    if missing:
        return fail(f"ComfyUI is missing model files under {COMFY_DIR}:\n  " + "\n  ".join(missing))
    unknown = comfy_client.missing_nodes(workflow, COMFY_URL)
    if unknown:
        return fail(f"ComfyUI at {COMFY_URL} does not know {', '.join(unknown)} - update the "
                    f"checkout (git -C {COMFY_DIR} pull) and restart it")
    if not no_memory_check:
        available = memory_available_gb()
        if available < MEMORY_FLOOR_GB:
            return fail(f"only {available:.0f} GB of memory available, a render needs about "
                        f"{MEMORY_FLOOR_GB} GB: stop vLLM first (or pass --no-memory-check)")
    return None


def room_status(dst, item, reviews):
    """(status, latest attempt) of a scene or insert room, or a room object:
    new       never attempted
    stuck     its latest judged attempt was rejected, and it has MAX_ATTEMPTS or
              more judged attempts
    failed    the latest attempt never finished (it has no record)
    rejected  the latest attempt failed the geometry gate, or its review rejected it
    missing   promoted and not rejected, but the output file is gone
    done      promoted and not rejected (reviewed, or waiting for review)

    A judged attempt is one with a record (attempt-N.json). A failed attempt
    has none and never counts toward STUCK: a room failing on infrastructure is
    retried on every batch. A stale review (see current_review) is ignored.
    """
    audit = audit_dir(dst, item)
    attempt = latest_attempt(audit)
    if attempt == 0:
        return "new", 0
    review = current_review(reviews, item, attempt)
    records = {n: r for n in range(1, attempt + 1) if (r := read_record(audit, n)) is not None}

    def rejected(n):
        return not records[n].get("promoted") or (review is not None and not review.accepted
                                                  and review.attempt >= n)

    if records and rejected(max(records)) and len(records) >= MAX_ATTEMPTS:
        return "stuck", attempt
    if attempt not in records:
        return "failed", attempt
    if rejected(attempt):
        return "rejected", attempt
    if not (dst / item.out_name).is_file():
        return "missing", attempt
    return "done", attempt


def corrections_for(dst, item, reviews):
    """What the room or object's next attempt must correct: the issues of its
    current review when that review rejected an attempt and no later attempt
    was promoted, whatever became of the attempts since (rejected or failed).
    After a geometry rejection it is the one GEOMETRY_CORRECTION sentence:
    the gate's own strings mean nothing to the diffusion model."""
    audit = audit_dir(dst, item)
    latest = latest_attempt(audit)
    review = current_review(reviews, item, latest)
    if review is None or review.accepted:
        return []
    if any((read_record(audit, n) or {}).get("promoted")
           for n in range(review.attempt + 1, latest + 1)):
        return []
    return [GEOMETRY_CORRECTION] if review.source == "geometry" else list(review.issues)


def write_nearest(args, room):
    """A skip room's output: its source enlarged 4x, nearest neighbour."""
    save_image_atomic(source_tree.open_rgba(args.src, room).convert(room.mode)
                      .resize(room.out_size, Image.Resampling.NEAREST),
                      args.dst / room.out_name)


def plan_line(args, room, entry, corrections):
    """One dry-run line: the room's size, windows, wraparound, margins and
    corrections; marked NOCAPTION instead of render for an uncaptioned room."""
    image = source_tree.open_rgba(args.src, room)
    plan = room_geometry.plan_room(image)
    one_row = len({(win.y0, win.y1) for win in plan.windows}) == 1

    def label(win):
        return (f"{win.x0}-{win.x1}" if one_row
                else f"{win.x0}-{win.x1}/{win.y0}-{win.y1}")

    w, h = room.out_size
    captioned = bool(entry.caption.strip())
    mark = "render" if captioned else "NOCAPTION"
    line = (f"  {mark:7} {room.key} {entry.kind:6} -> {w}x{h}  windows "
            + " ".join(label(win) for win in plan.windows))
    extras = []
    if plan.wrap:
        extras.append(f"wrap {plan.wrap.period}+{plan.wrap.span} (seam window)")
    m = plan.margins
    if m.left or m.right or m.top or m.bottom:
        extras.append(f"margins L{m.left} R{m.right} T{m.top} B{m.bottom}")
    if plan.height != image.height:
        extras.append(f"padded to {plan.height} rows")
    if corrections:
        extras.append(f"{len(corrections)} correction(s)")
    if not captioned:
        extras.append("no caption - run: make caption")
    return line + ("  " + "; ".join(extras) if extras else "")


def fallback_for(dst, item, workflow):
    """The workflow to render a stuck room or object through once more:
    `workflow`'s fallback while no judged attempt of it has used it; else None."""
    if workflow.fallback is None:
        return None
    audit = audit_dir(dst, item)
    used = {record.get("workflow") for n in range(1, latest_attempt(audit) + 1)
            if (record := read_record(audit, n)) is not None}
    return None if workflow.fallback in used else comfy_client.WORKFLOWS[workflow.fallback]


def room_workflow_for(args, room, workflow):
    """(the workflow the room renders through, why it differs from `workflow` or "").

    A room with several renders (windows, or a wraparound's seam) goes through
    `workflow`'s multi_window workflow when it names one: every window gets the
    whole caption, and at full denoise a mostly empty window paints the caption's
    objects into itself. A room that cannot be planned keeps `workflow`; its
    render reports why.
    """
    if workflow.multi_window is None:
        return workflow, ""
    try:
        plan = room_geometry.plan_room(source_tree.open_rgba(args.src, room))
    except ValueError:
        return workflow, ""
    if len(plan.windows) > 1 or plan.wrap:
        return comfy_client.WORKFLOWS[workflow.multi_window], "multi-window"
    return workflow, ""


def stuck_line(room):
    return (f"  STUCK   {room.key}: rejected {MAX_ATTEMPTS} times - fix its caption in "
            f"rooms.yaml, then: make batch room={room.number} force=1")


def cmd_batch(args):
    workflow = comfy_client.WORKFLOWS[args.workflow]
    rooms = selection(args)
    entries = load_entries(args)
    reviews = load_reviews(args.reviews, optional=True)
    copies, work, stuck, uncaptioned = [], [], [], []
    reasons = {}            # room key -> "fallback" or "multi-window", when not `workflow`
    done = 0
    for room in rooms:
        entry = entries[room.key]
        if entry.kind == "skip":
            if args.force or not (args.dst / room.out_name).is_file():
                copies.append(room)
            else:
                done += 1
            continue
        status, _ = room_status(args.dst, room, reviews)
        if not args.force and status == "done":
            done += 1
            continue
        room_workflow, why = room_workflow_for(args, room, workflow)
        if not args.force and status == "stuck":
            room_workflow, why = fallback_for(args.dst, room, room_workflow), "fallback"
            if room_workflow is None:
                stuck.append(room)
                continue
        if why:
            reasons[room.key] = why
        todo = (room, entry, corrections_for(args.dst, room, reviews), room_workflow)
        if entry.caption.strip():
            work.append(todo)
        else:
            uncaptioned.append(todo)

    print(f"workflow: {workflow.name}  match strength: {args.match_strength}")
    print(f"{len(rooms)} room(s): render {len(work)}, copy {len(copies)} (kind skip), "
          f"done {done}, stuck {len(stuck)}")
    if args.dry_run:
        for room in copies:
            w, h = room.out_size
            print(f"  copy    {room.key} skip   -> {w}x{h} nearest")
        for room, entry, corrections, room_workflow in work + uncaptioned:
            why = reasons.get(room.key)
            note = f"  ({why}: {room_workflow.name})" if why else ""
            try:
                print(plan_line(args, room, entry, corrections) + note)
            except ValueError as error:
                print(f"  ERROR   {room.key}: {error}")
        for room in stuck:
            print(stuck_line(room))
        return 0
    if uncaptioned:
        keys = [room.key for room, *_ in uncaptioned]
        return fail(f"{len(keys)} selected room(s) have no caption in {args.rooms_file} "
                    "- run: make caption\n  " + "\n  ".join(keys))
    for room in copies:
        write_nearest(args, room)
        print(f"  copy    {room.key} (nearest 4x)")
    if not work:
        for room in stuck:
            print(stuck_line(room), file=sys.stderr)
        return 1 if stuck else 0

    for needed in dict.fromkeys(room_workflow for *_, room_workflow in work):
        code = comfy_preflight(needed, args.no_memory_check)
        if code is not None:
            return code
    # ComfyUI keeps its models loaded after rendering (~40 GB); free them on the
    # way out, even after a failure, so vLLM has room to start for `make review`.
    try:
        promoted = rejected = failed = 0
        for i, (room, entry, corrections, room_workflow) in enumerate(work, 1):
            note = f" with {len(corrections)} correction(s)" if corrections else ""
            if reasons.get(room.key) == "fallback":
                note += f" through the fallback {room_workflow.name}"
            elif reasons.get(room.key) == "multi-window":
                note += f" through {room_workflow.name} (several windows)"
            print(f"[{i}/{len(work)}] render {room.key} ({entry.kind}){note}", flush=True)
            try:
                attempt, result = render_room(args, room_workflow, room, entry, corrections)
            except KeyboardInterrupt:
                comfy_client.sweep_outputs(room.key, COMFY_DIR)
                raise
            except Exception as error:
                failed += 1
                swept = comfy_client.sweep_outputs(room.key, COMFY_DIR)
                extra = f" (removed {swept} stray output file(s))" if swept else ""
                print(f"  ERROR rendering {room.key}: {error}{extra}", file=sys.stderr, flush=True)
                continue
            if result.passed:
                promoted += 1
                print(f"  promoted attempt {attempt}", flush=True)
                continue
            rejected += 1
            reviews[room.key] = Review(attempt, False, result.issues, "geometry")
            save_reviews(args.reviews, reviews)
            print(f"  rejected attempt {attempt}: " + "; ".join(result.issues), flush=True)
            if room_status(args.dst, room, reviews)[0] == "stuck":
                fallback = fallback_for(args.dst, room, room_workflow)
                if fallback is None:
                    stuck.append(room)
                else:
                    print(f"  next batch renders it through the fallback {fallback.name}",
                          flush=True)
        for room in stuck:
            print(stuck_line(room), file=sys.stderr)
        print(f"done: promoted={promoted} rejected={rejected} failed={failed} "
              f"copied={len(copies)} done={done} stuck={len(stuck)}")
        return 1 if failed or stuck else 0
    finally:
        free_comfy_models()


# ---- objects ----------------------------------------------------------------

def object_selection(args):
    """--object keys when given, else the objects of the selected rooms."""
    if args.object:
        return source_tree.select_objects(args.source, args.object)
    return source_tree.objects_of(args.source, [room.number for room in selection(args)])


def object_status(args, obj, reviews, room_sha):
    """room_status of the object, plus stale: done, but its promoted record
    named a room output other than the current one (room_sha). A done object
    whose current output file no attempt record promoted (a hand-replaced
    file) keeps its status unchanged; verify reports that file UNRECORDED."""
    status, attempt = room_status(args.obj_dst, obj, reviews)
    if status == "done":
        record = promoted_record(audit_dir(args.obj_dst, obj),
                                 source_tree.file_sha256(args.obj_dst / obj.out_name))
        if record is not None and record.get("room_sha256") != room_sha:
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
            method = args.dedither
            if method is None:
                promoted = promoted_record(audit_dir(args.dst, room), record["room_sha256"])
                method = (promoted or {}).get("dedither") or room_geometry.DEDITHER_METHOD
            inputs = object_geometry.object_inputs(room_hd, room_image, obj_image, obj.x, obj.y,
                                                   method)
            style = entry.style or "painted"
            # Only the room-wide sections: the room's layout names things outside the
            # object's context, and the render paints them into the object's mask.
            positive = render_prompt(room_wide_caption(entry.caption), entry.kind, corrections,
                                     OBJECT_NOTE, workflow.reference, style)
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
                           "dedither": method, "context": list(inputs.box),
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
    unreviewed = sum(1 for _, room, *_ in work if current_review(
        reviews, room, latest_attempt(audit_dir(args.dst, room))) is None)
    if unreviewed:
        print(f"note: {unreviewed} object(s) are in rooms whose latest attempt is not reviewed "
              "yet; if review rejects a room, its objects go stale and render again")
    for obj in bad:
        print(f"  BADPLACE {obj.key}: {obj.placement_error}", file=sys.stderr)
    if args.dry_run:
        for obj in copies:
            w, h = obj.out_size
            print(f"  copy      {obj.key} -> {w}x{h} nearest")
        for obj, room, _, cls, corrections, obj_workflow in work:
            w, h = obj.out_size
            extras = [f"{len(corrections)} correction(s)"] if corrections else []
            if cls == "render":
                x0, y0, x1, y1 = object_geometry.context_box(
                    obj.x, obj.y, obj.width, obj.height, room.width, room.height)
                extras.append(f"context {x1 - x0}x{y1 - y0}")
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
                fallback = fallback_for(args.obj_dst, obj, workflow)
                if fallback is None:
                    stuck.append(obj)
                else:
                    print(f"  next run renders it through the fallback {fallback.name}",
                          flush=True)
        for obj in stuck:
            print(object_stuck_line(obj), file=sys.stderr)
        print(f"done: promoted={promoted} rejected={rejected} failed={failed} "
              f"copied={len(copies)} done={done} stuck={len(stuck)} badplace={len(bad)}")
        return 1 if failed or stuck else 0
    finally:
        if renders:
            free_comfy_models()


# ---- review -----------------------------------------------------------------

def review_images(src, room, output, method=room_geometry.DEDITHER_METHOD):
    """([(guide window, render window), ...], whole render) for the VLM: the
    guide is rebuilt with `method`, the de-dither the promoted attempt used."""
    image = source_tree.open_rgba(src, room)
    guide = room_geometry.build_guide(image, method)
    plan = room_geometry.plan_room(image)
    with Image.open(output) as im:
        render = im.convert("RGB")
    pairs = []
    for win in plan.windows:
        box = (win.x0 * SCALE, win.y0 * SCALE, win.x1 * SCALE, min(win.y1 * SCALE, render.height))
        pairs.append((guide.full.crop(box), render.crop(box)))
    return pairs, render


def cmd_review(args):
    rooms = [] if args.object and not args.room else selection(args)
    entries = load_entries(args)
    code = vlm_preflight()
    if code is not None:
        return code
    free_comfy_models()     # give the VLM room; ComfyUI may be down
    reviews = load_reviews(args.reviews, optional=True)
    accepted = rejected = skipped = failed = 0
    for i, room in enumerate(rooms, 1):
        entry = entries[room.key]
        audit = audit_dir(args.dst, room)
        attempt = latest_attempt(audit)
        record = read_record(audit, attempt) if attempt else None
        dst = args.dst / room.out_name
        review = current_review(reviews, room, attempt)
        # Only a promoted latest attempt is judged: a geometry rejection already
        # has its verdict, and a failed attempt has nothing to show.
        if (entry.kind == "skip" or record is None or not record.get("promoted")
                or not dst.is_file()
                or (review is not None and review.attempt >= attempt and not args.force)):
            skipped += 1
            continue
        print(f"[{i}/{len(rooms)}] review {room.key} (attempt {attempt})", flush=True)
        try:
            method = record.get("dedither", room_geometry.DEDITHER_METHOD)
            pairs, overview = review_images(args.src, room, dst, method)
            verdict = review_room(pairs, overview, entry.kind, entry.caption,
                                  comfy_client.http_json, VLM_BASE_URL, VLM_MODEL, VLM_API_KEY,
                                  style=entry.style or "painted")
        except Exception as error:
            failed += 1
            write_atomic(audit / f"attempt-{attempt}.review-error.txt", str(error))
            print(f"  ERROR reviewing {room.key}: {error}", file=sys.stderr, flush=True)
            continue
        write_atomic(audit / f"attempt-{attempt}.review.json", json.dumps(verdict, indent=2))
        reviews[room.key] = Review(attempt, verdict["accepted"], tuple(verdict["issues"]), "review")
        save_reviews(args.reviews, reviews)
        if verdict["accepted"]:
            accepted += 1
            print("  accepted")
        else:
            rejected += 1
            print("  rejected: " + "; ".join(verdict["issues"]))

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
        for start in range(0, len(todo), OBJECT_REVIEW_BATCH):
            chunk = todo[start:start + OBJECT_REVIEW_BATCH]
            print(f"review {len(chunk)} object(s) of {room.key}", flush=True)
            try:
                with Image.open(args.dst / room.out_name) as im:
                    overview = im.convert("RGB")
                items = []
                for obj, attempt in chunk:
                    audit = audit_dir(args.obj_dst, obj)
                    with Image.open(audit / f"attempt-{attempt}.tiles" / "object.guide.png") as g, \
                            Image.open(audit / f"attempt-{attempt}.png") as r:
                        items.append((obj.key, g.convert("RGB"), r.convert("RGB")))
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

    print(f"done: accepted={accepted} rejected={rejected} skipped={skipped} failed={failed} "
          f"-> {args.reviews}")
    return 1 if failed else 0


# ---- command line -----------------------------------------------------------

def default_workflow(environ=os.environ):
    """--workflow when the flag is absent: DIG_WORKFLOW or comfy_client.DEFAULT_WORKFLOW."""
    name = environ.get("DIG_WORKFLOW") or comfy_client.DEFAULT_WORKFLOW
    if name not in comfy_client.WORKFLOWS:
        raise UsageError(f"DIG_WORKFLOW={name!r} is not a workflow; choose one of "
                         + ", ".join(sorted(comfy_client.WORKFLOWS)))
    return name


def match_strength(text):
    """argparse type for --match-strength: a number from 0 to 1."""
    try:
        value = float(text)
    except ValueError:
        value = -1.0
    if not 0 <= value <= 1:
        raise argparse.ArgumentTypeError(f"{text} is not a number from 0 to 1")
    return value


def default_match_strength(environ=os.environ):
    """--match-strength when the flag is absent: DIG_MATCH_STRENGTH or DEFAULT_MATCH_STRENGTH."""
    text = environ.get("DIG_MATCH_STRENGTH")
    if not text:
        return DEFAULT_MATCH_STRENGTH
    try:
        return match_strength(text)
    except argparse.ArgumentTypeError as error:
        raise UsageError(f"DIG_MATCH_STRENGTH: {error}") from error


def render_options(p, dedither_default=room_geometry.DEDITHER_METHOD):
    """The options of the two render stages, batch and objects. `objects` passes
    dedither_default=None: an object left to default picks up its room's own
    promoted attempt's de-dither method instead of always the constant."""
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
    if dedither_default is None:
        p.add_argument("--dedither", choices=room_geometry.DEDITHER_METHODS, default=None,
                       help="how the guide smooths the source's dithering (default: the "
                            "room's own promoted attempt's method, else "
                            f"{room_geometry.DEDITHER_METHOD})")
    else:
        p.add_argument("--dedither", choices=room_geometry.DEDITHER_METHODS,
                       default=dedither_default,
                       help="how the guide smooths the source's dithering (default: %(default)s)")


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--src", type=Path, default=SRC_ROOT,
                       help="thedig-textures-exporter output: manifest.json and la1/ "
                            "(default: %(default)s, or DIG_SRC)")
        p.add_argument("--dst", type=Path, default=DST_ROOT,
                       help="output tree (default: %(default)s, or DIG_DST)")
        p.add_argument("--obj-dst", type=Path, default=OBJ_DST_ROOT,
                       help="object output tree (default: %(default)s, or DIG_OBJ_DST)")
        p.add_argument("--room", type=int, action="append", metavar="N",
                       help="process room N only (repeatable)")
        p.add_argument("--rooms-file", type=Path, default=ROOMS_FILE,
                       help="rooms file (default: %(default)s, or DIG_ROOMS)")
        p.add_argument("--reviews", type=Path, default=REVIEWS_FILE,
                       help="reviews file (default: %(default)s, or DIG_REVIEWS)")

    def object_option(p):
        p.add_argument("--object", action="append", metavar="KEY",
                       help="process object KEY (objNNN_SS) only (repeatable)")

    caption = sub.add_parser("caption", help="write captions into rooms.yaml with the local vLLM")
    common(caption)
    caption.add_argument("--force", action="store_true",
                         help="re-caption rooms that already have a caption")
    caption.set_defaults(func=cmd_caption)

    batch = sub.add_parser("batch", help="render captioned rooms through ComfyUI")
    common(batch)
    render_options(batch)
    batch.set_defaults(func=cmd_batch)

    objects = sub.add_parser("objects", help="render room objects over their promoted rooms")
    common(objects)
    object_option(objects)
    render_options(objects, dedither_default=None)
    objects.set_defaults(func=cmd_objects)

    review = sub.add_parser("review", help="compare promoted rooms with their sources through "
                                           "the local vLLM")
    common(review)
    object_option(review)
    review.add_argument("--force", action="store_true",
                        help="review rooms whose latest attempt was already reviewed")
    review.set_defaults(func=cmd_review)

    verify = sub.add_parser("verify", help="audit the output tree against the manifest, the 4x "
                                           "rule and the attempt records")
    common(verify)
    object_option(verify)
    verify.set_defaults(func=cmd_verify)
    return ap


def main(argv=None):
    try:
        args = build_parser().parse_args(argv)
        if not args.src.is_dir():
            return fail(f"source is not a directory: {args.src} - set DIG_SRC or pass --src")
        args.source = source_tree.load(args.src)
        return args.func(args)
    except (UsageError, RoomsFileError, SourceError) as error:
        return fail(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
