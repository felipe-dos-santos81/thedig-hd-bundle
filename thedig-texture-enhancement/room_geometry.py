"""Room geometry: the guide image, margins, wraparound, the window plan, each
window's composite and mask, the stitch, the wrap seam and the fix-ups.

Pure image maths on Pillow images and numpy arrays; talks to no service and
knows no file layout. Positions are native room columns unless a comment says
4x; SCALE converts.
"""
import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter

from source_tree import SCALE, colour_keys

WINDOW_WIDTH = 320          # the widest window, native columns
WINDOW_HEIGHT = 240         # the tallest window, native rows (the spike checks it)
WINDOW_OVERLAP = 64         # the least overlap between neighbouring windows, on each axis
ALIGN = 8                   # window edges and the padded canvas height, native px
DEDITHER_METHODS = ("palette-smooth", "gaussian")
DEDITHER_METHOD = "palette-smooth"
DEDITHER_THRESHOLD = 64.0   # palette-smooth: the RGB distance of a neighbour still averaged in
MIN_WRAP_PERIOD = 320       # a wraparound repeats at least one screen later ...
MIN_WRAP_SPAN = 64          # ... over at least this many columns ...
WRAP_MATCH = 0.999          # ... in at least this fraction of their pixels


# ---- guide ------------------------------------------------------------------

def dedither(rgb, method=DEDITHER_METHOD):
    """`rgb` with its dithering smoothed away, at its own size.

    palette-smooth: each pixel becomes the mean of itself and those of its 3x3
    neighbours within DEDITHER_THRESHOLD RGB distance of it, so a checkerboard of near
    colours melts while an edge between distant colours stays sharp.
    gaussian: a Gaussian blur of radius 1. (A 3x3 median is no candidate: on a
    50% checkerboard each pixel is its neighbourhood's majority.)
    """
    if method == "gaussian":
        return rgb.convert("RGB").filter(ImageFilter.GaussianBlur(1))
    if method != "palette-smooth":
        raise ValueError(f"unknown de-dither method {method!r}; choose one of "
                         + ", ".join(DEDITHER_METHODS))
    a = np.asarray(rgb.convert("RGB"), dtype=np.float32)
    h, w, _ = a.shape
    padded = np.pad(a, ((1, 1), (1, 1), (0, 0)), mode="edge")
    total = np.zeros_like(a)
    count = np.zeros((h, w, 1), np.float32)
    for dy in range(3):
        for dx in range(3):
            n = padded[dy:dy + h, dx:dx + w]
            near = np.sqrt(((n - a) ** 2).sum(axis=2, keepdims=True)) <= DEDITHER_THRESHOLD
            near = near.astype(np.float32)
            total += n * near
            count += near
    return Image.fromarray(np.round(total / count).astype(np.uint8))


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


# ---- margins and wraparound -------------------------------------------------

@dataclass(frozen=True)
class Margins:
    left: int               # columns (left, right) or rows (top, bottom) at each edge
    right: int              # that are all one colour, the same one throughout
    top: int
    bottom: int


def _flat_run(lines):
    """How many leading lines are each one colour, the same colour throughout."""
    count, value = 0, None
    for line in lines:
        if (line != line[0]).any():
            break
        if value is None:
            value = line[0]
        elif line[0] != value:
            break
        count += 1
    return count


def blank_margins(pixels):
    h, w = pixels.shape
    return Margins(left=_flat_run(pixels[:, x] for x in range(w)),
                   right=_flat_run(pixels[:, x] for x in range(w - 1, -1, -1)),
                   top=_flat_run(pixels[y, :] for y in range(h)),
                   bottom=_flat_run(pixels[y, :] for y in range(h - 1, -1, -1)))


@dataclass(frozen=True)
class Wrap:
    period: int             # columns [period, period + span) repeat columns [0, span)
    span: int


def find_wrap(pixels, content_end):
    """The room's wraparound, or None.

    The smallest period from MIN_WRAP_PERIOD at which columns
    [period, content_end) repeat columns [0, content_end - period) in at least
    WRAP_MATCH of their pixels, over at least MIN_WRAP_SPAN columns.
    """
    for period in range(MIN_WRAP_PERIOD, content_end - MIN_WRAP_SPAN + 1):
        span = content_end - period
        if (pixels[:, period:content_end] == pixels[:, :span]).mean() >= WRAP_MATCH:
            return Wrap(period, span)
    return None


# ---- windows ----------------------------------------------------------------

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


# ---- composites, stitch, seam, fix-ups --------------------------------------

def _mask_row(width_4x, zero_until, full_from):
    """A 4x mask row: 0 before `zero_until`, a ramp strictly between 0 and 255
    up to `full_from`, 255 from there."""
    row = np.full(width_4x, 255, np.uint8)
    row[:zero_until] = 0
    n = full_from - zero_until
    if n > 0:
        row[zero_until:full_from] = np.round(np.arange(1, n + 1) * 255 / (n + 1))
    return row


def _mask(row, height):
    return Image.fromarray(np.tile(row, (height, 1)))


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


def _rolled(image, period, half):
    """The 4x columns of native [period - half, period) followed by [0, half)."""
    h = image.height
    strip = Image.new("RGB", (2 * half * SCALE, h))
    strip.paste(image.crop(((period - half) * SCALE, 0, period * SCALE, h)), (0, 0))
    strip.paste(image.crop((0, 0, half * SCALE, h)), (half * SCALE, 0))
    return strip


def seam_inputs(guide, canvas, plan):
    """(guide strip, composite, mask) for the seam window across a wraparound's join.

    The strip is the span's last WINDOW_WIDTH/2 columns followed by its first
    WINDOW_WIDTH/2.
    The mask holds the outer quarters, ramps across the next eighths and paints
    the middle quarter fully.
    """
    width = WINDOW_WIDTH
    period, half, q, e = plan.wrap.period, width // 2, width // 4, width // 8
    up = _mask_row(width * SCALE, q * SCALE, (q + e) * SCALE)
    row = np.minimum(up, up[::-1])
    return _rolled(guide, period, half), _rolled(canvas, period, half), _mask(row, guide.height)


def apply_seam(canvas, plan, rendered):
    """Write the seam render's middle half back to both ends of `canvas`."""
    period, half, q = plan.wrap.period, WINDOW_WIDTH // 2, WINDOW_WIDTH // 4
    h = canvas.height
    canvas.paste(rendered.crop((q * SCALE, 0, half * SCALE, h)), ((period - q) * SCALE, 0))
    canvas.paste(rendered.crop((half * SCALE, 0, (half + q) * SCALE, h)), (0, 0))


def apply_fixups(image, plan, source):
    """A copy of the 4x `image` with the wraparound's repeat copied from the
    room's start, and the margins set to the source's flat colours."""
    out = image.copy()
    h = out.height
    if plan.wrap:
        period, span = plan.wrap.period, plan.wrap.span
        out.paste(out.crop((0, 0, span * SCALE, h)), (period * SCALE, 0))
    m = plan.margins
    if m.left or m.right or m.top or m.bottom:
        flat = source.convert("RGB").resize(out.size, Image.Resampling.NEAREST)
        w, rows = source.width, source.height
        for x0, y0, x1, y1 in ((0, 0, m.left, rows), (w - m.right, 0, w, rows),
                               (0, 0, w, m.top), (0, rows - m.bottom, w, rows)):
            if x1 > x0 and y1 > y0:
                box = (x0 * SCALE, y0 * SCALE, x1 * SCALE, y1 * SCALE)
                out.paste(flat.crop(box), box[:2])
    return out
