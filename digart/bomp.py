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
