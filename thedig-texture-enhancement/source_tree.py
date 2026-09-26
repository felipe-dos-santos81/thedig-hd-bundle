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
