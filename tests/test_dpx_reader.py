#!/usr/bin/env python3

# This file is part of Optical2Digital.
#
# Copyright (C) 2026 Kyle Mikolajczyk
#
# Optical2Digital is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# Optical2Digital is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Optical2Digital; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

"""Standalone checks for dpx_reader.read_dpx.

Run directly with python3 (this project has no pytest setup):
    python3 tests/test_dpx_reader.py

These tests build synthetic DPX byte buffers by hand rather than reading a
real scanner file (none is available in this repo) -- see dpx_reader.py's
module docstring for which bit-depth/packing combinations are supported and
why the unsupported ones are rejected rather than guessed at.
"""
import os
import struct
import sys
import tempfile

import numpy as np

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
import dpx_reader
import KylesOpticalDecoder


HEADER_SIZE = 8192  # common real-world convention; only ~852 bytes matter


def _build_dpx(width, height, bits, descriptor, packing, pixel_bytes,
                endian=">", encoding=0, data_sign=0,
                encryption_key=0xFFFFFFFF, eol_padding=0, num_elements=1,
                magic=None, truncate_pixels=False):
    """Hand-pack a minimal-but-valid synthetic DPX buffer around
    *pixel_bytes* (already encoded by the caller in the target bit
    depth/packing scheme, row-major, with eol_padding bytes already
    included after each row if applicable)."""
    if magic is None:
        magic = b"SDPX" if endian == ">" else b"XPDS"

    buf = bytearray(HEADER_SIZE)

    def put_u32(offset, value):
        struct.pack_into(endian + "I", buf, offset, value & 0xFFFFFFFF)

    def put_u16(offset, value):
        struct.pack_into(endian + "H", buf, offset, value & 0xFFFF)

    def put_u8(offset, value):
        buf[offset] = value & 0xFF

    buf[0:4] = magic
    put_u32(4, HEADER_SIZE)  # generic image-data offset
    put_u32(660, encryption_key)

    put_u16(770, num_elements)
    put_u32(772, width)
    put_u32(776, height)

    e = 780
    put_u32(e + 0, data_sign)
    put_u8(e + 20, descriptor)
    put_u8(e + 23, bits)
    put_u16(e + 24, packing)
    put_u16(e + 26, encoding)
    put_u32(e + 28, 0)  # 0 -> fall back to the generic offset at byte 4
    put_u32(e + 32, eol_padding)

    data = bytes(pixel_bytes)
    if truncate_pixels:
        data = data[: max(0, len(data) - 4)]

    return bytes(buf) + data


def _pack_tight(pixel_grid, bits, endian, eol_padding=0):
    """pixel_grid: rows of pixels, each pixel a tuple of per-channel ints
    (or a bare int for single-channel). Returns tightly-packed row-major
    bytes with eol_padding zero bytes appended after each row."""
    dtype = np.dtype(endian + ("u1" if bits == 8 else "u2"))
    out = bytearray()
    for row in pixel_grid:
        flat = []
        for px in row:
            flat.extend(px if isinstance(px, tuple) else (px,))
        out += np.array(flat, dtype=dtype).tobytes()
        out += bytes(eol_padding)
    return bytes(out)


def _pack_10bit_method_a_rgb(pixel_grid, endian, eol_padding=0):
    dtype = np.dtype(endian + "u4")
    out = bytearray()
    for row in pixel_grid:
        words = [((r & 0x3FF) << 22) | ((g & 0x3FF) << 12) | ((b & 0x3FF) << 2)
                  for (r, g, b) in row]
        out += np.array(words, dtype=dtype).tobytes()
        out += bytes(eol_padding)
    return bytes(out)


def _expect_dpx_error(buf, needle=None):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "frame.dpx")
        with open(path, "wb") as f:
            f.write(buf)
        try:
            dpx_reader.read_dpx(path)
        except dpx_reader.DPXError as e:
            if needle is not None:
                assert needle.lower() in str(e).lower(), \
                    f"expected '{needle}' in error message, got: {e}"
            return
        assert False, "expected DPXError, got a successful read"


def test_magic_number_big_and_little_endian_agree():
    grid = [[(200, 100, 50), (10, 20, 30)]]
    for endian in (">", "<"):
        pixels = _pack_tight(grid, 8, endian)
        buf = _build_dpx(2, 1, 8, 50, 0, pixels, endian=endian)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "frame.dpx")
            with open(path, "wb") as f:
                f.write(buf)
            out = dpx_reader.read_dpx(path)
        assert out.shape == (1, 2, 3)
        assert out.dtype == np.uint8
        # DPX stores R,G,B; this reader outputs BGR (OpenCV convention).
        assert list(out[0, 0]) == [50, 100, 200], f"endian={endian}: {out[0,0]}"
        assert list(out[0, 1]) == [30, 20, 10], f"endian={endian}: {out[0,1]}"


def test_8bit_rgb_packed():
    grid = [[(200, 100, 50), (1, 2, 3)],
            [(255, 0, 128), (0, 0, 0)]]
    pixels = _pack_tight(grid, 8, ">")
    buf = _build_dpx(2, 2, 8, 50, 0, pixels)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "frame.dpx")
        with open(path, "wb") as f:
            f.write(buf)
        out = dpx_reader.read_dpx(path)
    assert out.shape == (2, 2, 3)
    assert list(out[0, 0]) == [50, 100, 200]
    assert list(out[1, 0]) == [128, 0, 255]


def test_8bit_grayscale():
    grid = [[10, 20], [30, 40]]
    pixels = _pack_tight(grid, 8, ">")
    buf = _build_dpx(2, 2, 8, 6, 0, pixels)  # descriptor 6 = luminance
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "frame.dpx")
        with open(path, "wb") as f:
            f.write(buf)
        out = dpx_reader.read_dpx(path)
    assert out.shape == (2, 2), f"expected 2D grayscale, got shape {out.shape}"
    assert out[0, 0] == 10 and out[1, 1] == 40


def test_10bit_rgb_method_a():
    grid = [[(1023, 512, 0), (0, 1023, 511)]]
    pixels = _pack_10bit_method_a_rgb(grid, ">")
    buf = _build_dpx(2, 1, 10, 50, 1, pixels)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "frame.dpx")
        with open(path, "wb") as f:
            f.write(buf)
        out = dpx_reader.read_dpx(path)

    def expected(v):
        return (v * 255 + 511) // 1023

    r0, g0, b0 = 1023, 512, 0
    assert list(out[0, 0]) == [expected(b0), expected(g0), expected(r0)]
    r1, g1, b1 = 0, 1023, 511
    assert list(out[0, 1]) == [expected(b1), expected(g1), expected(r1)]
    assert expected(1023) == 255  # sanity: max value round-trips to 255
    assert expected(0) == 0


def test_16bit_rgb_packed():
    grid = [[(65535, 0, 32768)]]
    pixels = _pack_tight(grid, 16, ">")
    buf = _build_dpx(1, 1, 16, 50, 0, pixels)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "frame.dpx")
        with open(path, "wb") as f:
            f.write(buf)
        out = dpx_reader.read_dpx(path)

    def expected(v):
        return (v * 255 + 32767) // 65535

    assert list(out[0, 0]) == [expected(32768), expected(0), expected(65535)]


def test_end_of_line_padding():
    grid = [[(200, 100, 50)], [(10, 20, 30)]]
    pixels = _pack_tight(grid, 8, ">", eol_padding=4)
    buf = _build_dpx(1, 2, 8, 50, 0, pixels, eol_padding=4)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "frame.dpx")
        with open(path, "wb") as f:
            f.write(buf)
        out = dpx_reader.read_dpx(path)
    assert list(out[0, 0]) == [50, 100, 200]
    assert list(out[1, 0]) == [30, 20, 10]


def test_rle_encoding_rejected():
    pixels = _pack_tight([[(1, 2, 3)]], 8, ">")
    buf = _build_dpx(1, 1, 8, 50, 0, pixels, encoding=1)
    _expect_dpx_error(buf, needle="RLE")


def test_unsupported_bit_depth_rejected():
    pixels = b"\x00" * 16
    buf = _build_dpx(1, 1, 32, 50, 0, pixels)
    _expect_dpx_error(buf)


def test_12bit_rejected():
    # 12-bit is rejected regardless of packing method -- see dpx_reader.py's
    # module docstring for why (unverified real-world bit-packing convention).
    pixels = b"\x00" * 16
    for packing in (0, 1):
        buf = _build_dpx(1, 1, 12, 50, packing, pixels)
        _expect_dpx_error(buf)


def test_10bit_grayscale_rejected():
    # Only 10-bit RGB Method A is supported; 10-bit single-channel Method A
    # uses an unverified packing convention and is rejected -- see
    # dpx_reader.py's module docstring.
    pixels = b"\x00" * 16
    buf = _build_dpx(1, 1, 10, 6, 1, pixels)
    _expect_dpx_error(buf)


def test_10bit_packing_zero_rejected():
    # "Packed" (non-word-aligned) 10-bit is rejected -- unverified bitstream
    # convention and rare in real scanner output.
    pixels = b"\x00" * 16
    buf = _build_dpx(1, 1, 10, 50, 0, pixels)
    _expect_dpx_error(buf)


def test_packing_method_b_rejected():
    pixels = _pack_tight([[(1, 2, 3)]], 8, ">")
    buf = _build_dpx(1, 1, 8, 50, 2, pixels)
    _expect_dpx_error(buf)


def test_signed_data_rejected():
    pixels = _pack_tight([[(1, 2, 3)]], 8, ">")
    buf = _build_dpx(1, 1, 8, 50, 0, pixels, data_sign=1)
    _expect_dpx_error(buf)


def test_encrypted_file_rejected():
    pixels = _pack_tight([[(1, 2, 3)]], 8, ">")
    buf = _build_dpx(1, 1, 8, 50, 0, pixels, encryption_key=0x12345678)
    _expect_dpx_error(buf)


def test_truncated_pixel_data_rejected():
    pixels = _pack_tight([[(1, 2, 3), (4, 5, 6)], [(7, 8, 9), (10, 11, 12)]], 8, ">")
    buf = _build_dpx(2, 2, 8, 50, 0, pixels, truncate_pixels=True)
    _expect_dpx_error(buf)


def test_bad_magic_rejected():
    pixels = _pack_tight([[(1, 2, 3)]], 8, ">")
    buf = _build_dpx(1, 1, 8, 50, 0, pixels)
    buf = b"XXXX" + buf[4:]
    _expect_dpx_error(buf)


def test_read_dpx_matches_supported_exts_dispatch():
    """End-to-end: a synthetic .dpx frame in a directory loads correctly
    through KylesOpticalDecoder.ImageSequenceSource, exercising the actual
    call-site wiring (not just dpx_reader in isolation)."""
    assert ".dpx" in KylesOpticalDecoder.SUPPORTED_EXTS

    grid = [[(200, 100, 50), (1, 2, 3)],
            [(255, 0, 128), (0, 0, 0)]]
    pixels = _pack_tight(grid, 8, ">")
    buf = _build_dpx(2, 2, 8, 50, 0, pixels)

    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "0001.dpx"), "wb") as f:
            f.write(buf)

        source = KylesOpticalDecoder.ImageSequenceSource(tmp)
        assert source.num_frames == 1
        assert source.frame_width == 2
        assert source.frame_height == 2

        frame = source.load_frame(0)
        assert frame is not None
        assert frame.shape == (2, 2, 3)
        assert list(frame[0, 0]) == [50, 100, 200]


if __name__ == "__main__":
    test_magic_number_big_and_little_endian_agree()
    test_8bit_rgb_packed()
    test_8bit_grayscale()
    test_10bit_rgb_method_a()
    test_16bit_rgb_packed()
    test_end_of_line_padding()
    test_rle_encoding_rejected()
    test_unsupported_bit_depth_rejected()
    test_12bit_rejected()
    test_10bit_grayscale_rejected()
    test_10bit_packing_zero_rejected()
    test_packing_method_b_rejected()
    test_signed_data_rejected()
    test_encrypted_file_rejected()
    test_truncated_pixel_data_rejected()
    test_bad_magic_rejected()
    test_read_dpx_matches_supported_exts_dispatch()
    print("OK: all dpx_reader checks passed")
