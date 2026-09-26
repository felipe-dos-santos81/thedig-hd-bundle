from digart.bomp import bomp_decode_line


def test_bomp_decode_line_runs_clamp_and_offsets():
    dst = bytearray(6)
    bomp_decode_line(dst, 0, bytes([0b0000_1001, 0x42, 0b0000_0000, 0x00]), 0, 6)
    assert dst == bytearray(b"\x42" * 5 + b"\x00")            # RLE 5, then literal 1

    dst = bytearray(3)
    bomp_decode_line(dst, 0, bytes([0b0000_1111, 0x99]), 0, 3)
    assert dst == bytearray(b"\x99" * 3)                      # run clamped to size

    dst = bytearray(4)
    bomp_decode_line(dst, 0, bytes([0b0000_0100]) + b"\x11\x22\x33\x44", 0, 3)
    assert dst == bytearray(b"\x11\x22\x33\x00")              # literal, tail untouched

    dst = bytearray(8)
    bomp_decode_line(dst, 5, bytes([0b0000_1001, 0x77]), 0, 3)
    assert dst[:5] == bytearray(5) and dst[5:] == bytearray(b"\x77\x77\x77")

    dst = bytearray(6)
    bomp_decode_line(dst, 0, bytes([0b0000_0010, 0xAA, 0xBB]) + bytes([0b0000_0111, 0x42]), 0, 6)
    assert dst == bytearray(b"\xAA\xBB" + b"\x42" * 4)        # literal then RLE


def test_bomp_decode_line_set_zero_false_keeps_previous():
    dst = bytearray(b"\xAA" * 3)
    bomp_decode_line(dst, 0, bytes([0b0000_0100, 0x00, 0x01, 0x02]), 0, 3, set_zero=False)
    assert dst == bytearray(b"\xAA\x01\x02")                  # literal zero keeps previous

    dst = bytearray(b"\xAA" * 3)
    bomp_decode_line(dst, 0, bytes([0b0000_0101, 0x00]), 0, 3, set_zero=False)
    assert dst == bytearray(b"\xAA" * 3)                      # RLE zero keeps previous
