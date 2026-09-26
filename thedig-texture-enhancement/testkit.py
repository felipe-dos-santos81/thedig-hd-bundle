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


def write_rooms(path, kinds=None, caption="SCENE: a test room.\nTEXT: none", rooms=DEFAULT_ROOMS,
                skip_objects=None):
    """Write a rooms.yaml covering `rooms`: kind scene with `caption`, unless
    `kinds` maps a room number to another kind. Room 4 is skip by default;
    skip rooms get no caption. `skip_objects` maps a room number to a list of
    object keys written as a nearest-neighbour 4x rather than rendered."""
    kinds = {4: "skip", **(kinds or {})}
    skip_objects = skip_objects or {}
    entries = {}
    for spec in rooms:
        kind = kinds.get(spec["room"], "scene")
        entries[f"room_{spec['room']:03d}"] = RoomEntry(
            kind, "" if kind == "skip" else caption, "",
            tuple(skip_objects.get(spec["room"], ())))
    save_rooms(path, entries)


def run_cli(argv):
    """Run dig_recreate.main(argv), capturing stdout and stderr: (code, out, err)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = a.main(list(argv))
    return code, out.getvalue(), err.getvalue()


_UNSET = object()


@contextlib.contextmanager
def vlm_stub(*, serving=True, caption=None, review=None, free=_UNSET):
    """Patch the vLLM side of `caption` and `review`: dig_recreate.vlm_is_serving
    and, when given, a side_effect callable for dig_recreate.caption_room or
    review_room. Pass `free` (a side_effect, or None for a plain stub) to also
    patch comfy_client.free_models, which only `review` calls.

    Yields the mocks: serving, and caption, review and freed when requested.
    """
    with contextlib.ExitStack() as stack:
        mocks = SimpleNamespace(
            serving=stack.enter_context(patch.object(a, "vlm_is_serving", return_value=serving)))
        if caption is not None:
            mocks.caption = stack.enter_context(patch.object(a, "caption_room", side_effect=caption))
        if review is not None:
            mocks.review = stack.enter_context(patch.object(a, "review_room", side_effect=review))
        if free is not _UNSET:
            mocks.freed = stack.enter_context(
                patch.object(comfy_client, "free_models", side_effect=free))
        yield mocks


def shift_right(image, pixels=8):
    """`image` moved `pixels` to the right over black: a render that slid 2 native px."""
    out = Image.new("RGB", image.size)
    out.paste(image, (pixels, 0))
    return out


def fake_render(transform=None):
    """A comfy_client.render_window stand-in that 'renders' a window by saving
    its composite (through `transform`, when given) where ComfyUI would."""
    def render(workflow, **kw):
        with Image.open(kw["composite"]) as im:
            image = im.convert("RGB")
        if transform is not None:
            image = transform(image)
        folder = Path(kw["comfy_dir"]) / "output" / comfy_client.OUTPUT_PREFIX
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{kw['name']}_00001_.png"
        image.save(path)
        return path
    return render


@contextlib.contextmanager
def comfy_stub(*, up=True, mem=100.0, missing=(), nodes=(), comfy_dir=None, render=None,
               free=None, swept=0):
    """Patch the ComfyUI side of `batch`: comfy_client.is_up, free_models,
    missing_model_files, missing_nodes, sweep_outputs, dig_recreate's
    memory_available_gb and (when given) COMFY_DIR and comfy_client.render_window
    (`render`, a side_effect callable such as fake_render()).

    Yields the mocks: is_up, freed, missing_model_files, missing_nodes, sweep,
    memory_available_gb, and render when requested.
    """
    with contextlib.ExitStack() as stack:
        mocks = SimpleNamespace(
            is_up=stack.enter_context(patch.object(comfy_client, "is_up", return_value=up)),
            freed=stack.enter_context(patch.object(comfy_client, "free_models", side_effect=free)),
            missing_model_files=stack.enter_context(
                patch.object(comfy_client, "missing_model_files", return_value=list(missing))),
            missing_nodes=stack.enter_context(
                patch.object(comfy_client, "missing_nodes", return_value=list(nodes))),
            sweep=stack.enter_context(
                patch.object(comfy_client, "sweep_outputs", return_value=swept)),
            memory_available_gb=stack.enter_context(
                patch.object(a, "memory_available_gb", return_value=mem)))
        if comfy_dir is not None:
            stack.enter_context(patch.object(a, "COMFY_DIR", comfy_dir))
        if render is not None:
            mocks.render = stack.enter_context(
                patch.object(comfy_client, "render_window", side_effect=render))
        yield mocks
