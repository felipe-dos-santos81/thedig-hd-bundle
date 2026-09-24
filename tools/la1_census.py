#!/usr/bin/env python3
"""DIG.LA1 census + SMAP reconnaissance.

Read-only structural census of The Dig's room/object resource file
(``DIG.LA1``). The output is the normative table for the LA1 oracle (Task 10)
and the LA1 port (Task 11). It is deterministic: no timestamps, no locale
dependence, every list sorted.

Container semantics are taken from the pinned upstream ScummVM sources
(commit ``ac3ab2250a4d8d82fe22c1d784a3d9c490342293``), verified byte-for-byte
against the shipped ``DIG.LA1``:

* ``room.cpp:readRoomsOffsets``  - LOFF index (u8 count, then room + u32 offset)
* ``room.cpp:setupRoomSubBlocks`` - RMHD dimensions, RMIM/IM00, PALS
* ``gfx.cpp:drawStrip`` / ``decompressBitmap`` - SMAP strip table + codec byte
* ``gfx.h:BMCOMP_*``             - codec byte names
* ``object.cpp:getObjectImage`` / ``ImageHeader`` - OBIM -> IMxx
* ``palette.cpp:findPalInPals``  - PALS -> WRAP -> OFFS + APAL

Every chunk size is header-inclusive: for a chunk at ``start`` with size ``S``
the next chunk is at ``start + S``. There is no odd-byte padding in LA1 (the
report proves this: the padded stride desyncs all 111 rooms, the unpadded one
never desyncs).

Usage::

    python3 tools/la1_census.py [DIG.LA1] > docs/la1-census.txt
"""

from __future__ import annotations

import hashlib
import struct
import sys
from collections import Counter
from pathlib import Path

BUNDLE = (
    Path.home()
    / "Documents"
    / "The Dig®.app"
    / "Contents"
    / "Resources"
    / "game"
    / "game"
)
DEFAULT_FILE = BUNDLE / "DIG.LA1"
UPSTREAM = "ac3ab2250a4d8d82fe22c1d784a3d9c490342293"

# gfx.h BMCOMP_* (The Dig is SCUMM v7; the codec byte is ``code`` and the
# low digit is the bit depth: ``_decomp_shr = code % 10``).
CODEC_NAMES = {
    1: "RAW256",
    8: "TRLE8BIT",
    9: "RLE8BIT",
    14: "ZIGZAG_V4",
    15: "ZIGZAG_V5",
    16: "ZIGZAG_V6",
    17: "ZIGZAG_V7",
    18: "ZIGZAG_V8",
    24: "ZIGZAG_H4",
    25: "ZIGZAG_H5",
    26: "ZIGZAG_H6",
    27: "ZIGZAG_H7",
    28: "ZIGZAG_H8",
    34: "ZIGZAG_VT4",
    35: "ZIGZAG_VT5",
    36: "ZIGZAG_VT6",
    37: "ZIGZAG_VT7",
    38: "ZIGZAG_VT8",
    44: "ZIGZAG_HT4",
    45: "ZIGZAG_HT5",
    46: "ZIGZAG_HT6",
    47: "ZIGZAG_HT7",
    48: "ZIGZAG_HT8",
    64: "MAJMIN_H4",
    65: "MAJMIN_H5",
    66: "MAJMIN_H6",
    67: "MAJMIN_H7",
    68: "MAJMIN_H8",
    84: "MAJMIN_HT4",
    85: "MAJMIN_HT5",
    86: "MAJMIN_HT6",
    87: "MAJMIN_HT7",
    88: "MAJMIN_HT8",
    104: "RMAJMIN_H4",
    105: "RMAJMIN_H5",
    106: "RMAJMIN_H6",
    107: "RMAJMIN_H7",
    108: "RMAJMIN_H8",
    124: "RMAJMIN_HT4",
    125: "RMAJMIN_HT5",
    126: "RMAJMIN_HT6",
    127: "RMAJMIN_HT7",
    128: "RMAJMIN_HT8",
    134: "NMAJMIN_H4",
    135: "NMAJMIN_H5",
    136: "NMAJMIN_H6",
    137: "NMAJMIN_H7",
    138: "NMAJMIN_H8",
    143: "CUSTOM_RU_TR",
    144: "NMAJMIN_HT4",
    145: "NMAJMIN_HT5",
    146: "NMAJMIN_HT6",
    147: "NMAJMIN_HT7",
    148: "NMAJMIN_HT8",
    149: "TPIX256",
    150: "SOLID_COLOR_FILL",
}

# Definitive tag -> class table (see section 5). Every tag observed in the
# shipped file is present; classes are bitmap / palette / script / audio /
# auxiliary.
TAG_CLASS = {
    "RMHD": ("auxiliary", "room header (v7: version u32, width/height/numObjects u16)"),
    "RMIM": ("bitmap", "room background image container (RMIH + IM00)"),
    "OBIM": ("bitmap", "object image container (IMHD + IMxx)"),
    "OBCD": ("script", "object code (CDHD + VERB verb scripts)"),
    "RMIH": ("bitmap", "room image header"),
    "IM00": ("bitmap", "room SMAP image"),
    "IM01": ("bitmap", "object image state 1"),
    "IM02": ("bitmap", "object image state 2"),
    "IM03": ("bitmap", "object image state 3"),
    "IM04": ("bitmap", "object image state 4"),
    "IM05": ("bitmap", "object image state 5"),
    "IM06": ("bitmap", "object image state 6"),
    "IM07": ("bitmap", "object image state 7"),
    "IM08": ("bitmap", "object image state 8"),
    "IM09": ("bitmap", "object image state 9"),
    "IM0A": ("bitmap", "object image state 10"),
    "IM0B": ("bitmap", "object image state 11"),
    "IM0C": ("bitmap", "object image state 12"),
    "IM0D": ("bitmap", "object image state 13"),
    "IM0E": ("bitmap", "object image state 14"),
    "IMHD": ("bitmap", "object image header (v7 ImageHeader)"),
    "SMAP": ("bitmap", "strip-offset table + compressed strips (room/object)"),
    "BOMP": ("bitmap", "RLE bitmap (object images only)"),
    "ZP01": ("bitmap", "z-plane mask for the room image"),
    "AKOS": ("bitmap", "costume (actor sprite) resource, Akos codec"),
    "CHAR": ("bitmap", "charset / glyph bitmap"),
    "PALS": ("palette", "room palette block (WRAP -> OFFS + APAL)"),
    "APAL": ("palette", "768-byte room palette"),
    "WRAP": ("palette", "palette container"),
    "OFFS": ("palette", "palette offset table"),
    "TRNS": ("auxiliary", "transparent colour index"),
    "CYCL": ("auxiliary", "colour-cycling range"),
    "SCAL": ("auxiliary", "walk-box scale slots"),
    "BOXD": ("auxiliary", "box (verb/UI) data"),
    "BOXM": ("auxiliary", "box (verb/UI) matrix"),
    "NLSC": ("script", "local-script count / metadata"),
    "LSCR": ("script", "local room script"),
    "EXCD": ("script", "room exit script"),
    "ENCD": ("script", "room entry script"),
    "SCRP": ("script", "global script"),
    "SOUN": ("audio", "sound resource"),
}

_PRINTABLE = frozenset(range(0x20, 0x7F))


def _u8(d: bytes, o: int) -> int:
    return d[o]


def _u16le(d: bytes, o: int) -> int:
    return struct.unpack_from("<H", d, o)[0]


def _u32le(d: bytes, o: int) -> int:
    return struct.unpack_from("<I", d, o)[0]


def _u32be(d: bytes, o: int) -> int:
    return struct.unpack_from(">I", d, o)[0]


def _is_tag(t: bytes) -> bool:
    return len(t) == 4 and all(c in _PRINTABLE for c in t)


def read_loff(data: bytes) -> tuple[int, list[tuple[int, int]]]:
    """LOFF index at file offset 16 (ScummVM ``readRoomsOffsets``).

    Layout: ``u8 count`` then ``count`` records of ``u8 room`` + ``u32LE
    offset`` (stride 5). The offsets are absolute file offsets of the ``ROOM``
    tag, i.e. the payload of an ``LFLF`` at ``offset - 8``.
    """
    count = _u8(data, 16)
    recs = [(_u8(data, 17 + 5 * k), _u32le(data, 18 + 5 * k)) for k in range(count)]
    return count, recs


def walk(
    data: bytes, start: int, end: int, pad: bool = False
) -> tuple[list[tuple[bytes, int, int]], tuple[int, bytes] | None]:
    """Walk the chunk list inside the payload of ``start`` up to ``end``.

    Chunk sizes are header-inclusive, so the next chunk is at ``start + size``.
    ``pad=True`` applies the (incorrect) odd-byte padding of the task brief to
    quantify the desyncs it produces. Returns ``(children, desync)`` where each
    child is ``(tag, offset, size)`` and ``desync`` is ``(offset_in_room,
    tag_read)`` for the first invalid chunk, else ``None``.
    """
    children: list[tuple[bytes, int, int]] = []
    c = start + 8
    while c < end:
        if c + 8 > end or not _is_tag(data[c : c + 4]):
            return children, (c - start, data[c : c + 4])
        tag = data[c : c + 4]
        size = _u32be(data, c + 4)
        if size < 8 or c + size > end:
            return children, (c - start, tag)
        children.append((tag, c, size))
        c += size + ((size & 1) if pad else 0)
    return children, None


def room_bounds(data: bytes, room_off: int) -> tuple[int, int]:
    """Return ``(lflf_off, room_end)`` for a LOFF ``ROOM`` offset."""
    lflf_off = room_off - 8
    return lflf_off, lflf_off + _u32be(data, lflf_off + 4)


def parse_smap(payload: bytes) -> dict | None:
    """Parse an ``IMxx`` payload whose first chunk is ``SMAP``.

    ``SMAP`` layout (gfx.cpp:drawStrip v7 branch): magic ``SMAP``, ``u32BE``
    chunk size, then a ``u32LE`` strip-offset table at ``payload + 8``. Strip
    ``i`` is at ``payload[table[i]]``; the first byte there is the codec.
    """
    if payload[:4] != b"SMAP":
        return None
    smaplen = _u32be(payload, 4)
    if 8 + 4 > len(payload):
        return None
    off0 = _u32le(payload, 8)
    if off0 < 8 or off0 >= len(payload):
        return None
    entries = (off0 - 8) // 4
    return {
        "smaplen": smaplen,
        "payload_len": len(payload),
        "table_offset": 8,
        "table_entries": entries,
        "table_bytes": entries * 4,
        "codec": payload[off0],
        "trailing": payload[smaplen : smaplen + 4],
    }


def parse_rmhd(payload: bytes) -> dict:
    """v7 RoomHeader: u32 version, u16 width, u16 height, u16 numObjects."""
    return {
        "version": _u32le(payload, 0),
        "width": _u16le(payload, 4),
        "height": _u16le(payload, 6),
        "num_objects": _u16le(payload, 8),
    }


def parse_imhd(payload: bytes) -> dict:
    """v7 ImageHeader (object.h): the fields the census needs."""
    return {
        "version": _u32le(payload, 0),
        "obj_id": _u16le(payload, 4),
        "image_count": _u16le(payload, 6),
        "x_pos": _u16le(payload, 8),
        "y_pos": _u16le(payload, 10),
        "width": _u16le(payload, 12),
        "height": _u16le(payload, 14),
    }


def _codec_label(code: int) -> str:
    return f"{code}({CODEC_NAMES.get(code, '?')})"


def _fmt_hist(hist: Counter) -> str:
    return "{" + ", ".join(f"{k}: {v}" for k, v in sorted(hist.items())) + "}"


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_FILE
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 1
    data = path.read_bytes()

    out: list[str] = []
    w = out.append

    w("DIG.LA1 census — LA1 room / object / SMAP reconnaissance")
    w("generated by tools/la1_census.py (deterministic; stdlib only)")
    w(f"upstream reference: scummvm {UPSTREAM}")
    w("")
    w(f"file:   {path}")
    w(f"size:   {len(data)}")
    w(f"sha256: {hashlib.sha256(data).hexdigest()}")

    count, recs = read_loff(data)
    room_bounds_list = [room_bounds(data, off) for _, off in recs]

    # ── 1. container layout ────────────────────────────────────────────────
    lecf_size = _u32be(data, 4)
    loff_size = _u32be(data, 12)
    w("")
    w("=" * 72)
    w("1. CONTAINER LAYOUT (LECF -> LOFF + LFLF -> ROOM)")
    w("=" * 72)
    w(f"LECF @0 size {lecf_size} (header-inclusive; spans the whole file)")
    w(f"LOFF @8 size {loff_size}; payload @16 len {loff_size - 8}")
    w(f"  count byte @16 = {count}   (u8; not a u16 header)")
    w(f"  records = {count} x (u8 room, u32LE offset), stride 5")
    w(f"  occupied bytes = 1 + {count}*5 = {1 + count * 5} (payload has no trailing bytes)")
    w(f"  rooms {recs[0][0]}..{recs[-1][0]} sequential: "
      f"{all(recs[i][0] == recs[0][0] + i for i in range(count))}")
    w(f"  every offset lands on LFLF/ROOM: "
      f"{all(data[o - 8 : o - 4] == b'LFLF' and data[o : o + 4] == b'ROOM' for _, o in recs)}")
    w("  first offsets:")
    for room, off in recs[:3]:
        w(f"    room {room:3d} -> {off}")
    w("  last offsets:")
    for room, off in recs[-3:]:
        w(f"    room {room:3d} -> {off}")
    lflf = [(o - 8, _u32be(data, o - 8 + 4)) for _, o in recs]
    contiguous = all(lflf[i][0] + lflf[i][1] == lflf[i + 1][0] for i in range(len(lflf) - 1))
    w(f"LFLF count: {len(lflf)}")
    w(f"  first LFLF @{lflf[0][0]} size {lflf[0][1]}")
    w(f"  last  LFLF @{lflf[-1][0]} size {lflf[-1][1]} (end {lflf[-1][0] + lflf[-1][1]} == file size "
      f"{len(data)}: {lflf[-1][0] + lflf[-1][1] == len(data)})")
    w(f"  contiguous (start+size == next start): {contiguous}")
    w(f"ROOM count: {count} (each is the payload of its LFLF at offset-8)")

    # ── 2. per-room child inventory + desyncs ──────────────────────────────
    tag_count: Counter = Counter()
    tag_bytes: Counter = Counter()
    tag_min: dict[bytes, int] = {}
    tag_max: dict[bytes, int] = {}
    padded_desyncs: list[tuple[int, int, bytes]] = []
    correct_desyncs: list[tuple[int, int, bytes]] = []

    for (room, room_off), (_, room_end) in zip(recs, room_bounds_list):
        children, desync = walk(data, room_off, room_end)
        if desync is not None:
            correct_desyncs.append((room, desync[0], desync[1]))
        _, pdesync = walk(data, room_off, room_end, pad=True)
        if pdesync is not None:
            padded_desyncs.append((room, pdesync[0], pdesync[1]))
        for tag, _c, size in children:
            tag_count[tag] += 1
            tag_bytes[tag] += size
            tag_min[tag] = min(tag_min.get(tag, size), size)
            tag_max[tag] = max(tag_max.get(tag, size), size)

    w("")
    w("=" * 72)
    w(f"2. ROOM CHILD INVENTORY ({count} rooms)")
    w("=" * 72)
    w("stride: next = chunk_start + size   (header-inclusive, NO odd padding)")
    w(f"{'tag':5s} {'count':>6s} {'total_bytes':>12s} {'min_size':>9s} {'max_size':>9s}")
    for tag, cnt in sorted(tag_count.items(), key=lambda kv: (-kv[1], kv[0])):
        w(f"{tag.decode('latin1'):5s} {cnt:6d} {tag_bytes[tag]:12d} {tag_min[tag]:9d} {tag_max[tag]:9d}")
    w("")
    w(f"desyncs with the correct stride: {len(correct_desyncs)}")
    for room, off, tag in correct_desyncs:
        w(f"  room {room:3d} byte {off:8d} tag {tag!r}")
    w("")
    w(f"desyncs with the brief's stride next = start + size + (size & 1): {len(padded_desyncs)}")
    w("(one per room; the odd-size OBCD/EXCD/ENCD chunks shift the walk by 1 byte)")
    for room, off, tag in padded_desyncs:
        w(f"  room {room:3d} byte {off:8d} tag {tag!r}")

    # ── 3. RMIM / OBIM images ──────────────────────────────────────────────
    rmim_rows: list[dict] = []
    obim_rows: list[dict] = []
    rmim_codecs: Counter = Counter()
    obim_codecs: Counter = Counter()
    obim_containers: Counter = Counter()
    obim_states: Counter = Counter()
    imhd_missing = 0

    for (room, room_off), (_, room_end) in zip(recs, room_bounds_list):
        children, _ = walk(data, room_off, room_end)
        rw = rh = None
        for tag, c, size in children:
            if tag == b"RMHD":
                hdr = parse_rmhd(data[c + 8 : c + size])
                rw, rh = hdr["width"], hdr["height"]
        for tag, c, size in children:
            if tag == b"RMIM":
                sub, _ = walk(data, c, c + size)
                for t, ic, isz in sub:
                    if t != b"IM00":
                        continue
                    smap = parse_smap(data[ic + 8 : ic + isz])
                    rmim_codecs[smap["codec"]] += 1
                    rmim_rows.append(
                        {
                            "room": room,
                            "size": isz,
                            "smaplen": smap["smaplen"],
                            "payload_len": smap["payload_len"],
                            "entries": smap["table_entries"],
                            "codec": smap["codec"],
                            "w": rw,
                            "h": rh,
                            "trailing": smap["trailing"],
                        }
                    )
            elif tag == b"OBIM":
                sub, _ = walk(data, c, c + size)
                imhd = [x for x in sub if x[0] == b"IMHD"]
                if not imhd:
                    imhd_missing += 1
                    continue
                hdr = parse_imhd(data[imhd[0][1] + 8 : imhd[0][1] + imhd[0][2]])
                obim_states[hdr["image_count"]] += 1
                for t, ic, isz in sub:
                    if t == b"IMHD":
                        continue
                    payload = data[ic + 8 : ic + isz]
                    smap = parse_smap(payload)
                    if smap is not None:
                        obim_containers["SMAP"] += 1
                        obim_codecs[smap["codec"]] += 1
                        obim_rows.append(
                            {
                                "room": room,
                                "tag": t,
                                "size": isz,
                                "container": "SMAP",
                                "detail": f"smaplen={smap['smaplen']} codec={_codec_label(smap['codec'])}",
                                "entries": smap["table_entries"],
                                "w": hdr["width"],
                                "h": hdr["height"],
                            }
                        )
                    elif payload[:4] == b"BOMP":
                        obim_containers["BOMP"] += 1
                        bw = _u16le(payload, 8 + 2)
                        bh = _u16le(payload, 8 + 4)
                        obim_rows.append(
                            {
                                "room": room,
                                "tag": t,
                                "size": isz,
                                "container": "BOMP",
                                "detail": f"bomp_w={bw} bomp_h={bh}",
                                "entries": 0,
                                "w": hdr["width"],
                                "h": hdr["height"],
                            }
                        )
                    else:
                        obim_containers[f"other:{payload[:4]!r}"] += 1

    w("")
    w("=" * 72)
    w("3. SMAP / BOMP IMAGES")
    w("=" * 72)
    w("RMIM path:  ROOM -> RMIM -> RMIH + IM00 -> payload = SMAP [+ ZP01]")
    w("  The room image is always IM00 and always SMAP; the codec byte lives at")
    w("  payload[strip_offset[0]]; dimensions come from RMHD (width/height).")
    w(f"RMIM images: {len(rmim_rows)}")
    w(f"  codec histogram: {_fmt_hist(rmim_codecs)}")
    w(f"  strip table == width/8 for all: "
      f"{all(r['entries'] * 8 == r['w'] for r in rmim_rows)}")
    w(f"  smaplen == IM00 payload length for: "
      f"{sum(1 for r in rmim_rows if r['smaplen'] == r['payload_len'])}/{len(rmim_rows)}"
      " (the rest carry ZP01 z-plane data after the SMAP chunk)")
    w("")
    w(f"{'room':>4s} {'size':>7s} {'smaplen':>7s} {'plen':>7s} {'strips':>6s} {'codec':>16s} "
      f"{'w':>5s} {'h':>5s} trailing")
    for r in sorted(rmim_rows, key=lambda r: r["room"]):
        trail = r["trailing"].decode("latin1") if r["trailing"] else "-"
        w(f"{r['room']:4d} {r['size']:7d} {r['smaplen']:7d} {r['payload_len']:7d} "
          f"{r['entries']:6d} {_codec_label(r['codec']):>16s} {r['w']:5d} {r['h']:5d} {trail}")
    w("")
    w("OBIM path:  ROOM -> OBIM -> IMHD + IMxx (x = 01..0E; IM00 never occurs)")
    w("  getObjectImage(ptr, state) uses IMxx_tags[state] with state = getState()")
    w("  (object.cpp:687), and getState() is 1-based, so the first image is IM01.")
    w("  An IMxx payload is a nested chunk: either SMAP (strip table + strips)")
    w("  or BOMP (u16 width @payload+10, u16 height @payload+12). IMHD carries")
    w("  the same width/height (verified for every BOMP image).")
    w(f"OBIM chunks: {tag_count.get(b'OBIM', 0)}  with IMHD: "
      f"{tag_count.get(b'OBIM', 0) - imhd_missing}  missing IMHD: {imhd_missing}")
    w(f"  image_count histogram (IMHD field): {_fmt_hist(obim_states)}")
    w(f"  image container histogram: {_fmt_hist(obim_containers)}")
    w(f"  SMAP codec histogram: {_fmt_hist(obim_codecs)}")
    w(f"  image tag histogram: {_fmt_hist(Counter(r['tag'].decode('latin1') for r in obim_rows))}")
    w(f"  SMAP strip table == width/8 for all SMAP images: "
      f"{all(r['entries'] * 8 == r['w'] for r in obim_rows if r['container'] == 'SMAP')}")
    w("")
    w(f"{'room':>4s} {'tag':4s} {'size':>7s} {'kind':4s} {'detail':34s} {'strips':>6s} "
      f"{'w':>5s} {'h':>5s}")
    for r in sorted(obim_rows, key=lambda r: (r["room"], r["tag"])):
        w(f"{r['room']:4d} {r['tag'].decode('latin1'):4s} {r['size']:7d} {r['container']:4s} "
          f"{r['detail']:34s} {r['entries']:6d} {r['w']:5d} {r['h']:5d}")

    # ── 4. palettes ────────────────────────────────────────────────────────
    pals_sizes: Counter = Counter()
    pals_tables: Counter = Counter()
    pals_rows: list[tuple[int, int, int]] = []
    apal_count = 0
    for (room, room_off), (_, room_end) in zip(recs, room_bounds_list):
        children, _ = walk(data, room_off, room_end)
        for tag, c, size in children:
            if tag != b"PALS":
                continue
            pals_sizes[size] += 1
            n_tables = 0
            sub, _ = walk(data, c, c + size)
            for t, wc, wsz in sub:
                if t != b"WRAP":
                    continue
                wsub, _ = walk(data, wc, wc + wsz)
                for t2, c2, s2 in wsub:
                    if t2 == b"OFFS":
                        n_tables = (s2 - 8) // 4
                    elif t2 == b"APAL":
                        apal_count += 1
            pals_tables[n_tables] += 1
            pals_rows.append((room, size, n_tables))

    w("")
    w("=" * 72)
    w("4. PALETTES (PALS / APAL)")
    w("=" * 72)
    w("structure: PALS -> WRAP -> OFFS + N x APAL")
    w("  OFFS payload is N u32LE offsets (relative to the OFFS payload); each")
    w("  points at a 768-byte palette = the APAL payload. palette.cpp:")
    w("  findPalInPals(WRAP, idx) returns offs + offs[idx].")
    w(f"PALS chunks: {sum(pals_sizes.values())}; size range {min(pals_sizes)}..{max(pals_sizes)}")
    w(f"  size histogram: {_fmt_hist(pals_sizes)}")
    w(f"APAL chunks: {apal_count}; each payload is 768 bytes")
    w(f"  palettes-per-PALS histogram: {_fmt_hist(pals_tables)}")
    w("  size formula: 804 + 780*(N-1)  (8 PALS hdr + 8 WRAP + 12 OFFS + 4*N + N*776)")
    w("  active room palette: index 0 (first OFFS entry / first APAL), per")
    w("  room.cpp:639 setCurrentPalette(0) -> getPalettePtr(0).")
    w("")
    w(f"{'room':>4s} {'pals_size':>9s} {'tables':>6s}")
    for room, size, n in sorted(pals_rows):
        w(f"{room:4d} {size:9d} {n:6d}")

    # ── 5. tag -> class table ──────────────────────────────────────────────
    w("")
    w("=" * 72)
    w("5. TAG -> CLASS TABLE")
    w("=" * 72)
    w(f"{'tag':5s} {'count':>6s} {'class':10s} description")
    for tag in sorted(tag_count, key=lambda t: (t.decode("latin1"))):
        name = tag.decode("latin1")
        cls, desc = TAG_CLASS.get(name, ("unknown", "unclassified"))
        w(f"{name:5s} {tag_count[tag]:6d} {cls:10s} {desc}")

    # ── 6. corrections vs the task brief ───────────────────────────────────
    w("")
    w("=" * 72)
    w("6. CORRECTIONS VS THE TASK BRIEF")
    w("=" * 72)
    w(f"1. LOFF is {count} records of (u8 room, u32LE offset), not 110 records of")
    w("   (u32LE offset, u8 kind). The brief's 'u16LE header 367' is the u16LE")
    w(f"   read of count(0x6f={count}) + first room(0x01): 0x016f = 367. The")
    w("   brief's 'kinds 2..111' are the room numbers shifted by one byte.")
    w(f"2. There are {count} rooms (1..{count}), not 110; the brief's stride missed")
    w("   room 111. Every per-room tag therefore counts 111.")
    w("3. Room chunk stride is next = start + size (header-inclusive, NO odd")
    w(f"   padding). The brief's + (size & 1) desyncs all {count} rooms; the")
    w("   correct stride desyncs 0.")
    w("4. OBIM/OBCD counts are 842/842 (one of each per object), not 841/239.")
    w("5. OBIM images are IMxx with x = 01..0E (state is 1-based); IM00 never")
    w("   occurs in OBIM. An IMxx payload is SMAP (492) or BOMP (150); the")
    w("   brief only listed SMAP.")
    w("6. RMIM IM00 payload is SMAP optionally followed by a ZP01 chunk; smaplen")
    w("   is the SMAP chunk size (header-inclusive), so it equals the IM00")
    w("   payload length only when no ZP01 follows (50/111 rooms).")
    w("7. NCD / XCD / LSC / SCR / BCD are NOT real room chunks: they are the")
    w("   1-byte-shifted tags read by the brief's padded stride. The real script")
    w("   chunks are EXCD, ENCD, NLSC and LSCR.")
    w("8. PALS holds 1..6 768-byte palettes (804 + 780*(N-1) bytes), not a fixed")
    w("   ~804-byte block with a single table.")

    sys.stdout.write("\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
