"""Faithful Python port of ScummVM's ``SmushDeltaBlocksDecoder`` (codec 37).

Transcribed line-for-line from the vendored, hash-pinned upstream source
``vendor/san-oracle/upstream/engines/scumm/smush/codec37.cpp`` (GPLv3), which is
authoritative for The Dig's ``SMUSH_CODEC_DELTA_BLOCKS`` frame objects.

Representation note: the C++ decoder keeps one flat ``_deltaBuf`` allocation and
two base pointers into it (``_deltaBufs[0] = +0x4D80``, ``_deltaBufs[1] =
+0xE880 + frameSize``).  The delta routines index relative to those bases with a
signed displacement (``dst + offsetTable[code] + nextOffs``, where ``nextOffs``
is negative when the current table is the second buffer).  A Python memoryview
sliced at a base cannot express that signed displacement -- a negative index
would count from the end of the view -- so the buffers are modelled as integer
offsets into the single ``bytearray``.  Integer offsets are exact pointer
arithmetic and keep every ``memset``/``memcpy`` span byte-faithful and in bounds.

One instance is stateful across frames; ``SanReader`` holds a single instance per
stream.
"""

from .bomp import bomp_decode_line

_MAKE_TABLE_BYTES = (
    0, 0, 1, 0, 2, 0, 3, 0, 5, 0,
    8, 0, 13, 0, 21, 0, -1, 0, -2, 0,
    -3, 0, -5, 0, -8, 0, -13, 0, -17, 0,
    -21, 0, 0, 1, 1, 1, 2, 1, 3, 1,
    5, 1, 8, 1, 13, 1, 21, 1, -1, 1,
    -2, 1, -3, 1, -5, 1, -8, 1, -13, 1,
    -17, 1, -21, 1, 0, 2, 1, 2, 2, 2,
    3, 2, 5, 2, 8, 2, 13, 2, 21, 2,
    -1, 2, -2, 2, -3, 2, -5, 2, -8, 2,
    -13, 2, -17, 2, -21, 2, 0, 3, 1, 3,
    2, 3, 3, 3, 5, 3, 8, 3, 13, 3,
    21, 3, -1, 3, -2, 3, -3, 3, -5, 3,
    -8, 3, -13, 3, -17, 3, -21, 3, 0, 5,
    1, 5, 2, 5, 3, 5, 5, 5, 8, 5,
    13, 5, 21, 5, -1, 5, -2, 5, -3, 5,
    -5, 5, -8, 5, -13, 5, -17, 5, -21, 5,
    0, 8, 1, 8, 2, 8, 3, 8, 5, 8,
    8, 8, 13, 8, 21, 8, -1, 8, -2, 8,
    -3, 8, -5, 8, -8, 8, -13, 8, -17, 8,
    -21, 8, 0, 13, 1, 13, 2, 13, 3, 13,
    5, 13, 8, 13, 13, 13, 21, 13, -1, 13,
    -2, 13, -3, 13, -5, 13, -8, 13, -13, 13,
    -17, 13, -21, 13, 0, 21, 1, 21, 2, 21,
    3, 21, 5, 21, 8, 21, 13, 21, 21, 21,
    -1, 21, -2, 21, -3, 21, -5, 21, -8, 21,
    -13, 21, -17, 21, -21, 21, 0, -1, 1, -1,
    2, -1, 3, -1, 5, -1, 8, -1, 13, -1,
    21, -1, -1, -1, -2, -1, -3, -1, -5, -1,
    -8, -1, -13, -1, -17, -1, -21, -1, 0, -2,
    1, -2, 2, -2, 3, -2, 5, -2, 8, -2,
    13, -2, 21, -2, -1, -2, -2, -2, -3, -2,
    -5, -2, -8, -2, -13, -2, -17, -2, -21, -2,
    0, -3, 1, -3, 2, -3, 3, -3, 5, -3,
    8, -3, 13, -3, 21, -3, -1, -3, -2, -3,
    -3, -3, -5, -3, -8, -3, -13, -3, -17, -3,
    -21, -3, 0, -5, 1, -5, 2, -5, 3, -5,
    5, -5, 8, -5, 13, -5, 21, -5, -1, -5,
    -2, -5, -3, -5, -5, -5, -8, -5, -13, -5,
    -17, -5, -21, -5, 0, -8, 1, -8, 2, -8,
    3, -8, 5, -8, 8, -8, 13, -8, 21, -8,
    -1, -8, -2, -8, -3, -8, -5, -8, -8, -8,
    -13, -8, -17, -8, -21, -8, 0, -13, 1, -13,
    2, -13, 3, -13, 5, -13, 8, -13, 13, -13,
    21, -13, -1, -13, -2, -13, -3, -13, -5, -13,
    -8, -13, -13, -13, -17, -13, -21, -13, 0, -17,
    1, -17, 2, -17, 3, -17, 5, -17, 8, -17,
    13, -17, 21, -17, -1, -17, -2, -17, -3, -17,
    -5, -17, -8, -17, -13, -17, -17, -17, -21, -17,
    0, -21, 1, -21, 2, -21, 3, -21, 5, -21,
    8, -21, 13, -21, 21, -21, -1, -21, -2, -21,
    -3, -21, -5, -21, -8, -21, -13, -21, -17, -21,
    0, 0, -8, -29, 8, -29, -18, -25, 17, -25,
    0, -23, -6, -22, 6, -22, -13, -19, 12, -19,
    0, -18, 25, -18, -25, -17, -5, -17, 5, -17,
    -10, -15, 10, -15, 0, -14, -4, -13, 4, -13,
    19, -13, -19, -12, -8, -11, -2, -11, 0, -11,
    2, -11, 8, -11, -15, -10, -4, -10, 4, -10,
    15, -10, -6, -9, -1, -9, 1, -9, 6, -9,
    -29, -8, -11, -8, -8, -8, -3, -8, 3, -8,
    8, -8, 11, -8, 29, -8, -5, -7, -2, -7,
    0, -7, 2, -7, 5, -7, -22, -6, -9, -6,
    -6, -6, -3, -6, -1, -6, 1, -6, 3, -6,
    6, -6, 9, -6, 22, -6, -17, -5, -7, -5,
    -4, -5, -2, -5, 0, -5, 2, -5, 4, -5,
    7, -5, 17, -5, -13, -4, -10, -4, -5, -4,
    -3, -4, -1, -4, 0, -4, 1, -4, 3, -4,
    5, -4, 10, -4, 13, -4, -8, -3, -6, -3,
    -4, -3, -3, -3, -2, -3, -1, -3, 0, -3,
    1, -3, 2, -3, 4, -3, 6, -3, 8, -3,
    -11, -2, -7, -2, -5, -2, -3, -2, -2, -2,
    -1, -2, 0, -2, 1, -2, 2, -2, 3, -2,
    5, -2, 7, -2, 11, -2, -9, -1, -6, -1,
    -4, -1, -3, -1, -2, -1, -1, -1, 0, -1,
    1, -1, 2, -1, 3, -1, 4, -1, 6, -1,
    9, -1, -31, 0, -23, 0, -18, 0, -14, 0,
    -11, 0, -7, 0, -5, 0, -4, 0, -3, 0,
    -2, 0, -1, 0, 0, -31, 1, 0, 2, 0,
    3, 0, 4, 0, 5, 0, 7, 0, 11, 0,
    14, 0, 18, 0, 23, 0, 31, 0, -9, 1,
    -6, 1, -4, 1, -3, 1, -2, 1, -1, 1,
    0, 1, 1, 1, 2, 1, 3, 1, 4, 1,
    6, 1, 9, 1, -11, 2, -7, 2, -5, 2,
    -3, 2, -2, 2, -1, 2, 0, 2, 1, 2,
    2, 2, 3, 2, 5, 2, 7, 2, 11, 2,
    -8, 3, -6, 3, -4, 3, -2, 3, -1, 3,
    0, 3, 1, 3, 2, 3, 3, 3, 4, 3,
    6, 3, 8, 3, -13, 4, -10, 4, -5, 4,
    -3, 4, -1, 4, 0, 4, 1, 4, 3, 4,
    5, 4, 10, 4, 13, 4, -17, 5, -7, 5,
    -4, 5, -2, 5, 0, 5, 2, 5, 4, 5,
    7, 5, 17, 5, -22, 6, -9, 6, -6, 6,
    -3, 6, -1, 6, 1, 6, 3, 6, 6, 6,
    9, 6, 22, 6, -5, 7, -2, 7, 0, 7,
    2, 7, 5, 7, -29, 8, -11, 8, -8, 8,
    -3, 8, 3, 8, 8, 8, 11, 8, 29, 8,
    -6, 9, -1, 9, 1, 9, 6, 9, -15, 10,
    -4, 10, 4, 10, 15, 10, -8, 11, -2, 11,
    0, 11, 2, 11, 8, 11, 19, 12, -19, 13,
    -4, 13, 4, 13, 0, 14, -10, 15, 10, 15,
    -5, 17, 5, 17, 25, 17, -25, 18, 0, 18,
    -12, 19, 13, 19, -6, 22, 6, 22, 0, 23,
    -17, 25, 18, 25, -8, 29, 8, 29, 0, 31,
    0, 0, -6, -22, 6, -22, -13, -19, 12, -19,
    0, -18, -5, -17, 5, -17, -10, -15, 10, -15,
    0, -14, -4, -13, 4, -13, 19, -13, -19, -12,
    -8, -11, -2, -11, 0, -11, 2, -11, 8, -11,
    -15, -10, -4, -10, 4, -10, 15, -10, -6, -9,
    -1, -9, 1, -9, 6, -9, -11, -8, -8, -8,
    -3, -8, 0, -8, 3, -8, 8, -8, 11, -8,
    -5, -7, -2, -7, 0, -7, 2, -7, 5, -7,
    -22, -6, -9, -6, -6, -6, -3, -6, -1, -6,
    1, -6, 3, -6, 6, -6, 9, -6, 22, -6,
    -17, -5, -7, -5, -4, -5, -2, -5, -1, -5,
    0, -5, 1, -5, 2, -5, 4, -5, 7, -5,
    17, -5, -13, -4, -10, -4, -5, -4, -3, -4,
    -2, -4, -1, -4, 0, -4, 1, -4, 2, -4,
    3, -4, 5, -4, 10, -4, 13, -4, -8, -3,
    -6, -3, -4, -3, -3, -3, -2, -3, -1, -3,
    0, -3, 1, -3, 2, -3, 3, -3, 4, -3,
    6, -3, 8, -3, -11, -2, -7, -2, -5, -2,
    -4, -2, -3, -2, -2, -2, -1, -2, 0, -2,
    1, -2, 2, -2, 3, -2, 4, -2, 5, -2,
    7, -2, 11, -2, -9, -1, -6, -1, -5, -1,
    -4, -1, -3, -1, -2, -1, -1, -1, 0, -1,
    1, -1, 2, -1, 3, -1, 4, -1, 5, -1,
    6, -1, 9, -1, -23, 0, -18, 0, -14, 0,
    -11, 0, -7, 0, -5, 0, -4, 0, -3, 0,
    -2, 0, -1, 0, 0, -23, 1, 0, 2, 0,
    3, 0, 4, 0, 5, 0, 7, 0, 11, 0,
    14, 0, 18, 0, 23, 0, -9, 1, -6, 1,
    -5, 1, -4, 1, -3, 1, -2, 1, -1, 1,
    0, 1, 1, 1, 2, 1, 3, 1, 4, 1,
    5, 1, 6, 1, 9, 1, -11, 2, -7, 2,
    -5, 2, -4, 2, -3, 2, -2, 2, -1, 2,
    0, 2, 1, 2, 2, 2, 3, 2, 4, 2,
    5, 2, 7, 2, 11, 2, -8, 3, -6, 3,
    -4, 3, -3, 3, -2, 3, -1, 3, 0, 3,
    1, 3, 2, 3, 3, 3, 4, 3, 6, 3,
    8, 3, -13, 4, -10, 4, -5, 4, -3, 4,
    -2, 4, -1, 4, 0, 4, 1, 4, 2, 4,
    3, 4, 5, 4, 10, 4, 13, 4, -17, 5,
    -7, 5, -4, 5, -2, 5, -1, 5, 0, 5,
    1, 5, 2, 5, 4, 5, 7, 5, 17, 5,
    -22, 6, -9, 6, -6, 6, -3, 6, -1, 6,
    1, 6, 3, 6, 6, 6, 9, 6, 22, 6,
    -5, 7, -2, 7, 0, 7, 2, 7, 5, 7,
    -11, 8, -8, 8, -3, 8, 0, 8, 3, 8,
    8, 8, 11, 8, -6, 9, -1, 9, 1, 9,
    6, 9, -15, 10, -4, 10, 4, 10, 15, 10,
    -8, 11, -2, 11, 0, 11, 2, 11, 8, 11,
    19, 12, -19, 13, -4, 13, 4, 13, 0, 14,
    -10, 15, 10, 15, -5, 17, 5, 17, 0, 18,
    -12, 19, 13, 19, -6, 22, 6, 22, 0, 23,
)


class DeltaBlocksDecoder:
    def __init__(self, width: int, height: int, rebel2_variant: bool = False):
        self._rebel2_variant = rebel2_variant
        self._width = width
        self._height = height
        self._frame_size = width * height
        self._delta_size = self._frame_size * 3 + 0x13600
        self._delta_buf = bytearray(self._delta_size)
        self._delta_bufs = [0x4D80, 0xE880 + self._frame_size]
        self._offset_table = [0] * 255
        self._cur_table = 0
        self._table_last_pitch = -1
        self._table_last_index = -1

    # -- table ---------------------------------------------------------------

    def _make_table(self, pitch: int, index: int) -> None:
        if self._table_last_pitch == pitch and self._table_last_index == index:
            return
        self._table_last_pitch = pitch
        self._table_last_index = index
        base = index * 255
        table, bytes_ = self._offset_table, _MAKE_TABLE_BYTES
        for i in range(255):
            j = (i + base) * 2
            table[i] = bytes_[j + 1] * pitch + bytes_[j]

    # -- 4x4 block primitives (macros LITERAL_*/COPY_4X4) ---------------------

    def _copy_4x4(self, dst: int, dst2: int, pitch: int) -> int:
        buf = self._delta_buf
        for x in range(4):
            a, b = dst + pitch * x, dst2 + pitch * x
            buf[a:a + 4] = buf[b:b + 4]
        return dst + 4

    def _literal_4x4(self, dst: int, src: bytes, s: int, pitch: int) -> tuple[int, int]:
        buf = self._delta_buf
        t = src[s]
        s += 1
        row = bytes((t, t, t, t))
        for x in range(4):
            a = dst + pitch * x
            buf[a:a + 4] = row
        return dst + 4, s

    def _literal_4x1(self, dst: int, src: bytes, s: int, pitch: int) -> tuple[int, int]:
        buf = self._delta_buf
        for x in range(4):
            t = src[s]
            s += 1
            a = dst + pitch * x
            buf[a:a + 4] = bytes((t, t, t, t))
        return dst + 4, s

    def _literal_2x2(self, dst: int, src: bytes, s: int, pitch: int) -> tuple[int, int]:
        buf = self._delta_buf
        p1, p2, p3, p4 = src[s], src[s + 1], src[s + 2], src[s + 3]
        s += 4
        for off, v in ((0, p1), (pitch, p1), (2, p2), (pitch + 2, p2),
                       (pitch * 2, p3), (pitch * 2 + 2, p4),
                       (pitch * 3, p3), (pitch * 3 + 2, p4)):
            buf[dst + off:dst + off + 2] = bytes((v, v))
        return dst + 4, s

    def _literal_1x1(self, dst: int, src: bytes, s: int, pitch: int) -> tuple[int, int]:
        buf = self._delta_buf
        for x in range(4):
            a = dst + pitch * x
            buf[a:a + 4] = src[s:s + 4]
            s += 4
        return dst + 4, s

    # -- block run decoders --------------------------------------------------

    def _proc1(self, dst: int, src: bytes, s: int, next_offs: int,
               bw: int, bh: int, pitch: int) -> None:
        buf = self._delta_buf
        pitches = [(p >> 2) * pitch + (p & 3) for p in range(16)]
        code = 0
        filling = False
        length = -1
        i = bw
        while True:
            if length < 0:
                filling = (src[s] & 1) == 1
                length = src[s] >> 1
                s += 1
                skip_code = False
            else:
                skip_code = True
            if (not filling) or (not skip_code):
                code = src[s]
                s += 1
                if code == 0xFF:
                    length -= 1
                    for p in range(0x10):
                        if length < 0:
                            filling = (src[s] & 1) == 1
                            length = src[s] >> 1
                            s += 1
                            if filling:
                                code = src[s]
                                s += 1
                        if filling:
                            buf[dst + pitches[p]] = code
                        else:
                            buf[dst + pitches[p]] = src[s]
                            s += 1
                        length -= 1
                    dst += 4
                    i -= 1
                    if i == 0:
                        dst += pitch * 3
                        bh -= 1
                        if bh == 0:
                            return
                        i = bw
                    continue
            dst2 = dst + self._offset_table[code] + next_offs
            dst = self._copy_4x4(dst, dst2, pitch)
            i -= 1
            if i == 0:
                dst += pitch * 3
                bh -= 1
                if bh == 0:
                    return
                i = bw
            length -= 1

    def _proc3_with_fdfe(self, dst: int, src: bytes, s: int, next_offs: int,
                         bw: int, bh: int, pitch: int) -> None:
        while True:
            i = bw
            while True:
                code = src[s]
                s += 1
                if code == 0xFD:
                    dst, s = self._literal_4x4(dst, src, s, pitch)
                elif code == 0xFE:
                    dst, s = self._literal_2x2(dst, src, s, pitch)
                elif code == 0xFF:
                    dst, s = self._literal_1x1(dst, src, s, pitch)
                else:
                    dst = self._copy_4x4(dst, dst + self._offset_table[code] + next_offs, pitch)
                i -= 1
                if i == 0:
                    break
            dst += pitch * 3
            bh -= 1
            if bh == 0:
                return

    def _proc3_without_fdfe(self, dst: int, src: bytes, s: int, next_offs: int,
                            bw: int, bh: int, pitch: int) -> None:
        while True:
            i = bw
            while True:
                code = src[s]
                s += 1
                if code == 0xFF:
                    dst, s = self._literal_1x1(dst, src, s, pitch)
                else:
                    dst = self._copy_4x4(dst, dst + self._offset_table[code] + next_offs, pitch)
                i -= 1
                if i == 0:
                    break
            dst += pitch * 3
            bh -= 1
            if bh == 0:
                return

    def _proc4_with_fdfe(self, dst: int, src: bytes, s: int, next_offs: int,
                         bw: int, bh: int, pitch: int) -> None:
        while True:
            i = bw
            while True:
                code = src[s]
                s += 1
                if code == 0xFD:
                    dst, s = self._literal_4x4(dst, src, s, pitch)
                elif code == 0xFE:
                    if self._rebel2_variant:
                        dst, s = self._literal_2x2(dst, src, s, pitch)
                    else:
                        dst, s = self._literal_4x1(dst, src, s, pitch)
                elif code == 0xFF:
                    dst, s = self._literal_1x1(dst, src, s, pitch)
                elif code == 0x00:
                    length = src[s] + 1
                    s += 1
                    for _ in range(length):
                        dst = self._copy_4x4(dst, dst + next_offs, pitch)
                        i -= 1
                        if i == 0:
                            dst += pitch * 3
                            bh -= 1
                            i = bw
                    if bh == 0:
                        return
                    i += 1
                else:
                    dst = self._copy_4x4(dst, dst + self._offset_table[code] + next_offs, pitch)
                i -= 1
                if i == 0:
                    break
            dst += pitch * 3
            bh -= 1
            if bh == 0:
                return

    def _proc4_without_fdfe(self, dst: int, src: bytes, s: int, next_offs: int,
                            bw: int, bh: int, pitch: int) -> None:
        while True:
            i = bw
            while True:
                code = src[s]
                s += 1
                if code == 0xFF:
                    dst, s = self._literal_1x1(dst, src, s, pitch)
                elif code == 0x00:
                    length = src[s] + 1
                    s += 1
                    for _ in range(length):
                        dst = self._copy_4x4(dst, dst + next_offs, pitch)
                        i -= 1
                        if i == 0:
                            dst += pitch * 3
                            bh -= 1
                            i = bw
                    if bh == 0:
                        return
                    i += 1
                else:
                    dst = self._copy_4x4(dst, dst + self._offset_table[code] + next_offs, pitch)
                i -= 1
                if i == 0:
                    break
            dst += pitch * 3
            bh -= 1
            if bh == 0:
                return

    # -- entry point ---------------------------------------------------------

    def decode(self, dst: bytearray, src: bytes) -> None:
        bw = (self._width + 3) // 4
        bh = (self._height + 3) // 4
        pitch = bw * 4

        seq_nb = int.from_bytes(src[2:4], "little")
        decoded_size = int.from_bytes(src[4:8], "little")
        mask_flags = src[12]
        self._make_table(pitch, src[1])
        variant = src[0]
        buf = self._delta_buf
        cur = self._cur_table
        off = self._delta_bufs[cur]

        if variant == 0:
            if off > 0:
                buf[0:off] = bytes(off)
            tmp = self._delta_size - off - decoded_size
            if tmp > 0:
                buf[off + decoded_size:off + decoded_size + tmp] = bytes(tmp)
            buf[off:off + decoded_size] = src[16:16 + decoded_size]
        elif variant == 1:
            if (seq_nb & 1) or not (mask_flags & 1):
                cur ^= 1
            self._cur_table = cur
            self._proc1(self._delta_bufs[cur], src, 16,
                        self._delta_bufs[cur ^ 1] - self._delta_bufs[cur], bw, bh, pitch)
        elif variant == 2:
            bomp_decode_line(buf, self._delta_bufs[cur], src, 16, decoded_size, set_zero=True)
            if off > 0:
                buf[0:off] = bytes(off)
            tmp = self._delta_size - off - decoded_size
            if tmp > 0:
                buf[off + decoded_size:off + decoded_size + tmp] = bytes(tmp)
        elif variant == 3:
            if (seq_nb & 1) or not (mask_flags & 1):
                cur ^= 1
            self._cur_table = cur
            next_offs = self._delta_bufs[cur ^ 1] - self._delta_bufs[cur]
            proc = self._proc3_with_fdfe if (mask_flags & 4) else self._proc3_without_fdfe
            proc(self._delta_bufs[cur], src, 16, next_offs, bw, bh, pitch)
        elif variant == 4:
            if (seq_nb & 1) or not (mask_flags & 1):
                cur ^= 1
            self._cur_table = cur
            next_offs = self._delta_bufs[cur ^ 1] - self._delta_bufs[cur]
            proc = self._proc4_with_fdfe if (mask_flags & 4) else self._proc4_without_fdfe
            proc(self._delta_bufs[cur], src, 16, next_offs, bw, bh, pitch)

        out_off = self._delta_bufs[self._cur_table]
        dst[0:self._frame_size] = buf[out_off:out_off + self._frame_size]
