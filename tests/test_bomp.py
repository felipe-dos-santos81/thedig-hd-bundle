from digart.bomp import bomp_decode_line

def test_rle_run_fills():
    dst = bytearray(6)
    src = bytes([0b0000_1001, 0x42, 0b0000_0000, 0x00])  # RLE 5x0x42, then literal 1x0x00
    bomp_decode_line(dst, 0, src, 0, 6)
    assert dst == bytearray(b"\x42" * 5 + b"\x00")

def test_rle_run_clamped_to_size():
    dst = bytearray(3)
    src = bytes([0b0000_1111, 0x99])          # num=8 -> clamped to 3
    bomp_decode_line(dst, 0, src, 0, 3)
    assert dst == bytearray(b"\x99" * 3)

def test_literal_run_copy():
    dst = bytearray(4)
    src = bytes([0b0000_0100]) + b"\x11\x22\x33\x44"   # literal num=3
    bomp_decode_line(dst, 0, src, 0, 3)
    assert dst == bytearray(b"\x11\x22\x33\x00")

def test_set_zero_false_literal_zero_keeps_previous():
    dst = bytearray(b"\xAA" * 3)
    src = bytes([0b0000_0100, 0x00, 0x01, 0x02])
    bomp_decode_line(dst, 0, src, 0, 3, set_zero=False)
    assert dst == bytearray(b"\xAA\x01\x02")

def test_set_zero_false_rle_zero_keeps_previous():
    dst = bytearray(b"\xAA" * 3)
    src = bytes([0b0000_0101, 0x00])          # RLE num=3 color 0
    bomp_decode_line(dst, 0, src, 0, 3, set_zero=False)
    assert dst == bytearray(b"\xAA" * 3)

def test_dst_offset_respected():
    dst = bytearray(8)
    src = bytes([0b0000_1001, 0x77])
    bomp_decode_line(dst, 5, src, 0, 3)
    assert dst[:5] == bytearray(5) and dst[5:] == bytearray(b"\x77\x77\x77")

def test_mixed_opcodes_sequence():
    dst = bytearray(6)
    src = bytes([0b0000_0010, 0xAA, 0xBB]) + bytes([0b0000_0111, 0x42])  # lit2, RLE4
    bomp_decode_line(dst, 0, src, 0, 6)
    assert dst == bytearray(b"\xAA\xBB" + b"\x42" * 4)
