import struct


def bomp_decode_line(dst: bytearray, dst_off: int, src: bytes, src_off: int,
                     size: int, set_zero: bool = True) -> None:
    assert size > 0
    while size > 0:
        code = src[src_off]; src_off += 1
        num = (code >> 1) + 1
        if num > size:
            num = size
        size -= num
        if code & 1:
            color = src[src_off]; src_off += 1
            if set_zero or color:
                dst[dst_off:dst_off + num] = bytes([color]) * num
            dst_off += num
        elif set_zero:
            dst[dst_off:dst_off + num] = src[src_off:src_off + num]
            src_off += num
            dst_off += num
        else:
            for _ in range(num):
                color = src[src_off]; src_off += 1
                if color:
                    dst[dst_off] = color
                dst_off += 1


def bomp_decode_rows(dst: bytearray, dst_pitch: int, src: bytes, src_off: int,
                     width: int, height: int, set_zero: bool = True) -> None:
    """Decode ``height`` rows of ``src``, each prefixed by a u16LE row length.

    Shared by the LA1/OBIM, AKOS/CDAT and NUT/codec-1 decoders, which all store a
    BOMP stream as one length-prefixed row per output row.
    """
    for row in range(height):
        bomp_decode_line(dst, row * dst_pitch, src, src_off + 2, width,
                         set_zero=set_zero)
        src_off += struct.unpack_from("<H", src, src_off)[0] + 2
