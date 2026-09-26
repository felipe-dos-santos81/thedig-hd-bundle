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
