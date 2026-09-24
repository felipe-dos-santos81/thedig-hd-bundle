import struct
from collections.abc import Iterator
from dataclasses import dataclass, field

from .errors import DecodeError

FRAME_W, FRAME_H = 320, 200


@dataclass(frozen=True)
class SanFrame:
    index: bytes
    palette: bytes


@dataclass
class SanReader:
    data: bytes
    source: str = "?"
    pal: bytearray = field(default_factory=lambda: bytearray(768))
    delta: list = field(default_factory=lambda: [0] * 768)
    shifted: list = field(default_factory=lambda: [0] * 768)
    buf: bytearray = field(default_factory=lambda: bytearray(FRAME_W * FRAME_H))
    skipped: dict = field(default_factory=dict)
    num_frames_announced: int = 0
    _pending: int = 0

    def frames(self) -> Iterator[SanFrame]:
        d, n = self.data, len(self.data)
        if d[:4] != b"ANIM":
            raise DecodeError(self.source, 0, f"missing ANIM: {d[:4]!r}")
        off = 8
        emitted = 0
        while off + 8 <= n:
            tag, size = d[off:off + 4], int.from_bytes(d[off + 4:off + 8], "big")
            if off + 8 + size > n:
                raise DecodeError(self.source, off, f"bad {tag!r} chunk size {size}")
            body = off + 8
            if tag == b"AHDR":
                if size < 0x306:
                    raise DecodeError(self.source, body, f"AHDR too small {size}")
                p = d[body:body + size]
                ver, self.num_frames_announced = struct.unpack_from("<HH", p, 0)
                assert ver == 2
                self.pal = bytearray(p[6:774])
            elif tag == b"FRME":
                self._feed(d[body:body + size])
                emitted += 1
                yield SanFrame(bytes(self.buf), bytes(self.pal))
            else:
                raise DecodeError(self.source, off, f"unknown top-level chunk {tag!r}")
            off = body + size + (size & 1)
        if self.num_frames_announced != emitted:
            self.skipped["FRAME_COUNT_MISMATCH"] = self.num_frames_announced - emitted

    def _feed(self, f: bytes) -> None:
        p = 0
        while p + 8 <= len(f):
            tag = f[p:p + 4]
            size = int.from_bytes(f[p + 4:p + 8], "big")
            payload = f[p + 8:p + 8 + size]
            if tag == b"NPAL":
                assert len(payload) >= 0x300
                self.pal = bytearray(payload[:768])
            elif tag == b"XPAL":
                self._xpal(payload)
            elif tag == b"FOBJ":
                self._fobj(payload)
            elif tag == b"ZFOB":
                self._zfb(payload)
            else:
                self.skipped[tag.decode("latin1")] = self.skipped.get(tag.decode("latin1"), 0) + 1
            p += 8 + size + (size & 1)

    def _xpal(self, payload: bytes) -> None:
        cmd = int.from_bytes(payload[2:4], "little")
        if cmd == 256:
            for i in range(768):
                self.shifted[i] += self.delta[i]
                self.pal[i] = min(255, max(0, self.shifted[i] >> 7))
        else:
            for j in range(768):
                self.shifted[j] = self.pal[j] << 7
                v = int.from_bytes(payload[4 + 2 * j:6 + 2 * j], "little")
                self.delta[j] = v - 0x10000 if v > 0x7FFF else v
            if cmd == 512:
                self.pal = bytearray(payload[4 + 1536:4 + 1536 + 768])

    def _fobj(self, payload: bytes) -> None:      # implemented in Task 4
        self._pending += 1

    def _zfb(self, payload: bytes) -> None:       # implemented in Task 4
        self._pending += 1


def iter_frames(data: bytes, source: str = "?") -> Iterator[SanFrame]:
    return SanReader(data, source).frames()
