"""Minimal pure-Python/numpy reader for DPX (SMPTE 268M) image files.

DPX is the still-image format most film scanners write. This module has no
dependency beyond numpy (already required elsewhere in this project), which
matters because this project's PyInstaller build matrix already fights
painful platform-specific packaging issues -- see the long comments in
.github/workflows/release.yml -- so a heavier imaging dependency (e.g.
OpenImageIO, which has no published wheel for Windows ARM64, one of this
project's three release targets) was deliberately avoided in favor of a
self-contained parser.

Supported:
  - 8-bit and 16-bit samples, any of the channel layouts below, either
    "packed" or "Method A" packing (the two are byte-identical at these
    depths since 8 and 16 divide evenly into byte/word boundaries).
  - 10-bit RGB samples packed "Method A" (filled to 32-bit words) -- the
    conventional format written by virtually all film scanners. The exact
    bit layout (MSB-justified, 2 padding bits at the low end of each
    32-bit word: R in bits [31:22], G in [21:12], B in [11:2]) was
    verified against the PatrickPalmer/dpx reference reader's
    Unfill10bitFilled implementation rather than derived from the spec
    text alone, since real-world DPX decoders have historically disagreed
    on bit-packing details the spec doesn't fully pin down.
  - Descriptor codes: 50 (RGB), 51 (RGBA, alpha decoded then dropped), and
    1/2/3/6 (single-component/luminance -- scanners use these somewhat
    interchangeably for monochrome scans).
  - Both byte orders (magic "SDPX" = big-endian, "XPDS" = little-endian).

Deliberately unsupported (raises DPXError with a specific reason, never
silently mis-decodes): RLE encoding, signed sample data, encrypted files,
"Method B" packing, 12-bit samples, 10-bit non-RGB (grayscale/RGBA) with
Method A packing, and 10/12-bit "packed" (non-word-aligned) data. These are
all rare in real scanner output, and the bit-level conventions for several
of them could not be independently verified without a real sample file
(the project has none) -- rejecting them cleanly was judged safer than
guessing at an unverified packing scheme. Broadening support later is
straightforward: add a case to _unpack_pixels once the exact convention is
confirmed against a real file or another verified reference implementation.

Always converts down to 8-bit-per-channel uint8 before returning (never
16-bit or float), matching what cv2.imread(..., IMREAD_UNCHANGED) returns
for other formats -- the rest of this project's pipeline hard-codes an
8-bit assumption throughout, and this keeps that assumption valid for DPX
frames without touching that pipeline.
"""
import struct

import numpy as np


class DPXError(Exception):
    """Malformed, truncated, or unsupported DPX data.

    read_dpx() raises this instead of returning None so the caller always
    knows *why* a file failed, rather than getting an opaque None like a
    corrupt JPEG/PNG would produce from cv2.imread.
    """


# Descriptor codes (Image Element Structure, byte offset 20 within the
# element -> absolute offset 800) this reader understands, mapped to
# output channel count. Values not listed here (CbYCr variants, depth,
# composite video, user-defined, etc.) are rejected.
_DESCRIPTOR_CHANNELS = {
    1: 1,   # Red -- scanners also use this for generic single-component/mono
    2: 1,   # Green
    3: 1,   # Blue
    6: 1,   # Luminance
    50: 3,  # R, G, B
    51: 4,  # R, G, B, A (alpha decoded then dropped)
}

_SUPPORTED_BITS = (8, 10, 12, 16)
_MAX_VALUE = {8: 255, 10: 1023, 12: 4095, 16: 65535}


def read_dpx(path):
    """Read a DPX file.

    Returns a uint8 numpy array: (H, W) for grayscale/luminance sources or
    (H, W, 3) BGR for RGB/RGBA sources -- matching cv2.imread's convention
    so callers don't need to special-case DPX. Raises DPXError on any
    malformed or unsupported input; never returns None.
    """
    with open(path, "rb") as f:
        buf = f.read()
    try:
        header = _parse_header(buf, path)
        samples = _unpack_pixels(buf, header, path)
        return _to_uint8_bgr_or_gray(samples, header)
    except DPXError:
        raise
    except (struct.error, IndexError, ValueError) as e:
        raise DPXError(f"Malformed DPX file '{path}': {e}") from e


def _u8(buf, offset):
    return buf[offset]


def _u16(buf, offset, endian):
    return struct.unpack_from(endian + "H", buf, offset)[0]


def _u32(buf, offset, endian):
    return struct.unpack_from(endian + "I", buf, offset)[0]


def _parse_header(buf, path):
    """Parse the fields needed from the Generic File Header (offset 0),
    Image Information Header (offset 768), and Image Element Structure for
    element 0 (offset 780, 72 bytes) -- see SMPTE 268M-2003. Only element 0
    is read; multi-element DPX files (rare) use later elements for extra
    data like alpha mattes, which this reader doesn't need.
    """
    if len(buf) < 852:  # 780 + 72: end of image element 0's structure
        raise DPXError(f"Truncated DPX header: '{path}'")

    magic = buf[0:4]
    if magic == b"SDPX":
        endian = ">"
    elif magic == b"XPDS":
        endian = "<"
    else:
        raise DPXError(f"Not a DPX file (bad magic number): '{path}'")

    generic_data_offset = _u32(buf, 4, endian)

    encryption_key = _u32(buf, 660, endian)
    if encryption_key != 0xFFFFFFFF:
        raise DPXError(f"Encrypted DPX files are not supported: '{path}'")

    num_elements = _u16(buf, 770, endian)
    if num_elements < 1:
        raise DPXError(f"DPX file declares zero image elements: '{path}'")

    width = _u32(buf, 772, endian)
    height = _u32(buf, 776, endian)
    if width == 0 or height == 0:
        raise DPXError(f"DPX file declares zero width/height: '{path}'")

    e = 780  # start of Image Element Structure for element 0
    data_sign = _u32(buf, e + 0, endian)
    if data_sign != 0:
        raise DPXError(f"Signed DPX pixel data is not supported: '{path}'")

    descriptor = _u8(buf, e + 20)
    if descriptor not in _DESCRIPTOR_CHANNELS:
        raise DPXError(f"Unsupported DPX descriptor {descriptor}: '{path}'")
    channels = _DESCRIPTOR_CHANNELS[descriptor]

    bits = _u8(buf, e + 23)
    if bits not in _SUPPORTED_BITS:
        raise DPXError(f"Unsupported DPX bit depth {bits}: '{path}'")

    packing = _u16(buf, e + 24, endian)
    if packing not in (0, 1):
        raise DPXError(f"Unsupported DPX packing method {packing}: '{path}'")

    encoding = _u16(buf, e + 26, endian)
    if encoding != 0:
        raise DPXError(f"RLE-encoded DPX files are not supported: '{path}'")

    elem_data_offset = _u32(buf, e + 28, endian)
    data_offset = (
        elem_data_offset
        if elem_data_offset not in (0, 0xFFFFFFFF)
        else generic_data_offset
    )
    if data_offset == 0 or data_offset == 0xFFFFFFFF or data_offset >= len(buf):
        raise DPXError(f"Invalid or missing DPX pixel data offset: '{path}'")

    eol_padding = _u32(buf, e + 32, endian)
    if eol_padding == 0xFFFFFFFF:
        eol_padding = 0

    return {
        "endian": endian,
        "width": width,
        "height": height,
        "channels": channels,
        "bits": bits,
        "packing": packing,
        "data_offset": data_offset,
        "eol_padding": eol_padding,
    }


def _unpack_pixels(buf, header, path):
    """Return native-bit-depth samples as a (H, W, C) uint32 array."""
    bits = header["bits"]
    packing = header["packing"]
    channels = header["channels"]

    if bits in (8, 16):
        return _unpack_tight(buf, header, path)

    if bits == 10 and packing == 1 and channels == 3:
        return _unpack_10bit_method_a_rgb(buf, header, path)

    raise DPXError(
        f"Unsupported DPX bit depth/packing/channel combination "
        f"(bits={bits}, packing={packing}, channels={channels}) in "
        f"'{path}' -- only 8-bit and 16-bit (any channel count), and "
        f"10-bit RGB packed to 32-bit words ('Method A'), are supported"
    )


def _unpack_tight(buf, header, path):
    """8-bit or 16-bit samples, tightly packed with no padding needed --
    both depths divide evenly into byte/word boundaries, so 'packed' and
    'Method A' produce identical byte layouts and don't need to be told
    apart here."""
    endian = header["endian"]
    width = header["width"]
    height = header["height"]
    channels = header["channels"]
    bits = header["bits"]
    data_offset = header["data_offset"]
    eol_padding = header["eol_padding"]

    bytes_per_sample = bits // 8
    dtype = np.dtype(endian + ("u1" if bits == 8 else "u2"))
    samples_per_row = width * channels
    row_bytes = samples_per_row * bytes_per_sample
    stride = row_bytes + eol_padding

    end_needed = data_offset + stride * max(height - 1, 0) + row_bytes
    if end_needed > len(buf):
        raise DPXError(f"Truncated DPX pixel data: '{path}'")

    samples = np.empty((height, samples_per_row), dtype=np.uint32)
    pos = data_offset
    for y in range(height):
        row = np.frombuffer(buf, dtype=dtype, count=samples_per_row, offset=pos)
        samples[y] = row.astype(np.uint32)
        pos += stride
    return samples.reshape(height, width, channels)


def _unpack_10bit_method_a_rgb(buf, header, path):
    """10-bit RGB, 'Method A': one pixel's R, G, B packed MSB-justified
    into a single 32-bit word with 2 padding bits at the low end:
    R = bits [31:22], G = bits [21:12], B = bits [11:2]. This is the
    conventional layout written by virtually all film scanners; verified
    against the PatrickPalmer/dpx reference reader (shifts 22/12/2, mask
    0x3FF) rather than derived from the spec text alone -- see this
    module's docstring."""
    endian = header["endian"]
    width = header["width"]
    height = header["height"]
    data_offset = header["data_offset"]
    eol_padding = header["eol_padding"]

    row_bytes = width * 4
    stride = row_bytes + eol_padding
    end_needed = data_offset + stride * max(height - 1, 0) + row_bytes
    if end_needed > len(buf):
        raise DPXError(f"Truncated DPX pixel data: '{path}'")

    wdtype = np.dtype(endian + "u4")
    words = np.empty((height, width), dtype=np.uint32)
    pos = data_offset
    for y in range(height):
        words[y] = np.frombuffer(buf, dtype=wdtype, count=width, offset=pos)
        pos += stride

    r = (words >> 22) & 0x3FF
    g = (words >> 12) & 0x3FF
    b = (words >> 2) & 0x3FF
    return np.stack([r, g, b], axis=-1)


def _to_uint8_bgr_or_gray(samples, header):
    """Scale native-bit-depth samples down to uint8 and reorder RGB(A)
    into OpenCV's BGR channel convention, matching what
    cv2.imread(..., IMREAD_UNCHANGED) returns for other formats."""
    bits = header["bits"]
    channels = header["channels"]
    max_value = _MAX_VALUE[bits]

    if bits == 8:
        scaled = samples.astype(np.uint8)
    else:
        # Round-to-nearest scale-down rather than a plain right-shift, to
        # avoid a systematic downward bias.
        scaled = (
            (samples.astype(np.uint64) * 255 + max_value // 2) // max_value
        ).astype(np.uint8)

    if channels == 1:
        return scaled[:, :, 0]

    # DPX stores R, G, B(, A); this codebase's convention (matching
    # OpenCV, see KylesOpticalDecoder.select_soundtrack_channel) is BGR.
    r = scaled[:, :, 0]
    g = scaled[:, :, 1]
    b = scaled[:, :, 2]
    return np.stack([b, g, r], axis=-1)
