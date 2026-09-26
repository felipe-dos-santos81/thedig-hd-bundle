import struct


# ── SAN / NUT synthetic builders ─────────────────────────────────────────────

def be(tag: bytes, payload: bytes) -> bytes:
    out = tag + struct.pack(">I", len(payload)) + payload
    if len(payload) & 1:
        out += b"\x00"
    return out


def ahdr(payload_len: int = 0x31a, palette: bytes | None = None, num_frames: int = 0, fps: int = 12) -> bytes:
    p = bytearray(payload_len)
    struct.pack_into("<HH", p, 0, 2, num_frames)
    struct.pack_into("<H", p, 6 + 768, fps)
    if palette is not None:
        p[6:6 + 768] = palette
    return p


def xpal(cmd: int, delta: bytes = b"", full_palette: bytes | None = None) -> bytes:
    if cmd == 256:
        p = struct.pack("<HHH", 0, cmd, 0)        # 3 u16 LE then no palette data
    else:
        assert len(delta) == 768 * 2
        p = struct.pack("<HH", 0, cmd) + delta
        if full_palette is not None:
            assert len(full_palette) == 768
            p += full_palette
    return be(b"XPAL", p)


def npal(pal: bytes) -> bytes:
    return be(b"NPAL", pal)


def frame(*subs: bytes) -> bytes:
    return be(b"FRME", b"".join(subs))


def san(frames: list[bytes], palette: bytes = bytes(768)) -> bytes:
    body = be(b"AHDR", ahdr(palette=palette, num_frames=len(frames))) + b"".join(frames)
    return b"ANIM" + struct.pack(">I", 8 + len(body)) + body


def mk_nut(glyphs: list[tuple[int, int, int, bytes]], palette: bytes = bytes(768)) -> bytes:
    """Build a NUT font: ANIM + AHDR + one FRME(FOBJ) per ``(codec, w, h, payload)``.

    No metadata chunk; ``numChars`` at AHDR+10 (payload+2) and the palette at
    payload[6:774], per the verified layout. The ANIM length is the font-body
    length (AHDR onward), unlike ``san`` which adds the 8-byte ANIM header.
    """
    frames = []
    for codec, w, h, payload in glyphs:
        body = struct.pack("<HhhHHHH", codec, 0, 0, w, h, 0, 0) + payload
        frames.append(be(b"FRME", be(b"FOBJ", body)))
    body = be(b"AHDR", ahdr(palette=palette, num_frames=len(glyphs))) + b"".join(frames)
    return b"ANIM" + struct.pack(">I", len(body)) + body


# ── Shared byte-builders for the LA1-family and codec-37 fixtures ────────────

def be32(n: int) -> bytes:
    return struct.pack(">I", n)


def le32(n: int) -> bytes:
    return struct.pack("<I", n)


def le16(n: int) -> bytes:
    return struct.pack("<H", n)


def la1_chunk(tag: bytes, payload: bytes) -> bytes:
    """Header-inclusive LA1 chunk: tag + u32BE size (8 + payload), no padding."""
    return tag + be32(8 + len(payload)) + payload


def la1_container(room_body: bytes, room: int = 1) -> bytes:
    """LECF -> LOFF (one room) -> LFLF wrapping ``room_body``."""
    loff = la1_chunk(b"LOFF", bytes([1, room]) + le32(30))
    return la1_chunk(b"LECF", loff + la1_chunk(b"LFLF", room_body))


def palette_wrap(pal: bytes) -> bytes:
    """The room's active palette: PALS -> WRAP -> OFFS(12) + APAL."""
    wrap = la1_chunk(b"WRAP", la1_chunk(b"OFFS", le32(12)) + la1_chunk(b"APAL", pal))
    return la1_chunk(b"PALS", wrap)


def smap(codec: int, strip: bytes, w: int, h: int) -> bytes:
    """SMAP with a single strip whose codec byte sits at payload[offset[0]]."""
    return la1_chunk(b"SMAP", le32(8 + 4 * (w // 8)) + bytes([codec]) + strip)


def codec_header(variant: int, table: int = 0, seq: int = 0,
                 decoded_size: int = 0, mask: int = 0) -> bytes:
    """16-byte codec-37 sub-header: variant, table, seq, size, 4 pad, mask, 3 pad."""
    return (bytes([variant, table]) + struct.pack("<H", seq)
            + struct.pack("<I", decoded_size) + bytes(4)
            + bytes([mask]) + bytes(3))


def fobj(codec: int, w: int, h: int, data: bytes, left: int = 0, top: int = 0,
         objid: int = 0, parm2: int = 0) -> bytes:
    hdr = struct.pack("<HhhHHHH", codec, left, top, w, h, objid, parm2)
    return be(b"FOBJ", hdr + data)


def codec1_payload() -> bytes:
    """Two rows for a 4x2 NUT glyph: a literal run, then an RLE run."""
    row0 = struct.pack("<H", 5) + bytes([0x06, 5, 6, 7, 8])
    row1 = struct.pack("<H", 2) + bytes([0x07, 3])
    return row0 + row1
