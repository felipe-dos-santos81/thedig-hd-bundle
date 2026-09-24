import struct

def be(tag: bytes, payload: bytes) -> bytes:
    out = tag + struct.pack(">I", len(payload)) + payload
    if len(payload) & 1:
        out += b"\x00"
    return out

def fsub(tag: bytes, payload: bytes) -> bytes:
    return be(tag, payload)

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
