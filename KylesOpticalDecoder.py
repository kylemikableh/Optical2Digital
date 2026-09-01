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

"""
Optical2Digital - Optical Film Soundtrack to WAV Extractor

Extracts audio from scanned motion picture film optical soundtracks (variable-area):
  1. Load scanned frame images
  2. Crop to soundtrack region
  3. Apply image corrections (negative inversion, Dmin normalization, binary mask cleanup)
  4. Extract audio via scanline luminance averaging
  5. Resample to target sample rate
  6. Apply Butterworth HPF (DC bias removal) + LPF (anti-aliasing)
  7. Write signed 16-bit PCM WAV
"""

import argparse
import concurrent.futures
import contextlib
import io
import os
import queue
import struct
import sys
import threading

import cv2
import numpy as np
import natsort
from scipy.io import wavfile
from scipy.signal import butter, sosfilt, resample

import dpx_reader


class ExtractionCancelled(Exception):
    """Raised out of extract_audio() when a caller-supplied cancel_event is
    set mid-run — see extract_audio()'s cancel_event parameter."""


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract audio from scanned optical film soundtracks.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i", "--input", required=True,
        help="Directory containing scanned frame images",
    )
    parser.add_argument(
        "-o", "--output", default="output.wav",
        help="Output WAV file path",
    )
    parser.add_argument(
        "--crop", type=int, nargs=4, required=True,
        metavar=("TOP", "BOTTOM", "LEFT", "RIGHT"),
        help="Pixel coordinates to crop the soundtrack region: top bottom left right",
    )
    parser.add_argument(
        "--fps", type=float, default=24.0,
        help="Frame rate of the film",
    )
    parser.add_argument(
        "--sample-rate", type=int, default=48000,
        help="Output WAV sample rate in Hz",
    )
    parser.add_argument(
        "--negative", action="store_true",
        help="Invert the image (for negative film scans)",
    )
    parser.add_argument(
        "--dmin-value", type=float, default=None,
        help="Fixed Dmin value in [0,1] used for normalization (overrides percentile estimation)",
    )
    parser.add_argument(
        "--dmin-percentile", type=float, default=99.5,
        help="Percentile used to estimate Dmin from the cropped track",
    )
    parser.add_argument(
        "--dmin-headroom", type=float, default=0.2,
        help="Value subtracted after Dmin normalization to leave headroom",
    )
    parser.add_argument(
        "--binary-mask", action="store_true",
        help="Apply OpenCV binary threshold mask after Dmin normalization",
    )
    parser.add_argument(
        "--binary-lb", type=int, default=96,
        help="Lower threshold (0-255) for binary mask",
    )
    parser.add_argument(
        "--binary-ub", type=int, default=255,
        help="Upper output value (0-255) for binary mask",
    )
    parser.add_argument(
        "--reverse", action="store_true",
        help="Reverse the frame order before extraction",
    )
    parser.add_argument(
        "--hpf", type=float, default=40.0,
        help="High-pass filter cutoff in Hz (removes DC bias)",
    )
    parser.add_argument(
        "--lpf", type=float, default=13500.0,
        help="Low-pass filter cutoff in Hz (anti-aliasing)",
    )
    parser.add_argument(
        "--overlap", type=float, default=0.25,
        help="Fraction of frame height to search for overlap between consecutive frames (0 = disabled, 0.25 = 25%%)",
    )
    parser.add_argument(
        "--audio-offset", type=int, default=21,
        help=(
            "Sound advance in frames: the soundtrack for picture frame N is printed "
            "this many frames earlier in the scan (frame N - offset). 21 is the typical "
            "default for optical film prints."
        ),
    )
    parser.add_argument(
        "--rotate", type=int, default=0, choices=[0, 90, 180, 270],
        help="Rotate cropped image by this many degrees clockwise before extraction",
    )
    parser.add_argument(
        "--dump-crops", type=str, default=None,
        metavar="DIR",
        help="Save cropped soundtrack images to this directory for debugging",
    )
    parser.add_argument(
        "--soundtrack-color", type=parse_soundtrack_color_arg, default="B&W",
        metavar="{B&W,High-Magenta,Cyan}",
        help=(
            "Soundtrack stock color type. For non-monochrome frames: "
            "B&W/High-Magenta use GREEN channel; Cyan uses RED channel"
        ),
    )
    parser.add_argument(
        "--binary-pixel-value", dest="integrate", action="store_false", default=True,
        help=(
            "Use Binary Pixel Value mode (Dmin normalization, optionally followed by "
            "binary threshold masking) instead of the default Average Pixel Value mode "
            "(SVA integration: sum raw channel transmittance). Useful when the default "
            "mode struggles with anti-aliased images."
        ),
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Image correction
# ---------------------------------------------------------------------------

def correct_image(img_float, negative):
    """Apply the remaining image corrections to a floating-point image [0,1]."""
    img = img_float.copy()

    if negative:
        img = 1.0 - img

    np.clip(img, 0.0, 1.0, out=img)
    return img


def normalize_track_by_dmin(img_float, dmin_percentile=99.5, dmin_headroom=0.2, dmin_value=None):
    """Normalize track image by Dmin estimate and apply headroom offset.

    Dmin is estimated from a bright-point percentile in the cropped track image,
    then the full image is divided by Dmin so clear aperture maps near 1.0.
    A small headroom value is subtracted to reduce sensitivity to drift/noise.
    """
    if img_float.size == 0:
        return img_float

    if dmin_value is not None:
        dmin = float(dmin_value)
    else:
        dmin = np.percentile(img_float, np.clip(dmin_percentile, 0.0, 100.0))
    dmin = max(float(dmin), 1e-6)
    normalized = img_float / dmin
    normalized -= dmin_headroom
    return np.clip(normalized, 0.0, 1.0)


def estimate_dmin_from_track_point(img, top, bottom, left, right, rotate=0,
                                   soundtrack_color="B&W", sample_x=None, sample_y=None,
                                   negative=False):
    """Estimate Dmin from a selected pixel in the cropped soundtrack area.

    If *sample_x* and *sample_y* are omitted, the center of the cropped region
    is used. The sampled value honors the negative-inversion setting so the
    picker matches what the user sees in the preview.
    """
    cropped = img[top:bottom, left:right]
    if cropped.size == 0:
        raise ValueError("Invalid crop region for Dmin estimation")
    cropped = select_soundtrack_channel(cropped, soundtrack_color)
    cropped = rotate_image(cropped, rotate)
    h, w = cropped.shape[:2]
    if sample_x is None or sample_y is None:
        cx = w // 2
        cy = h // 2
    else:
        cx = int(np.clip(sample_x, 0, max(w - 1, 0)))
        cy = int(np.clip(sample_y, 0, max(h - 1, 0)))

    corrected = correct_image(cropped.astype(np.float64) / 255.0, negative)
    dmin = max(float(corrected[cy, cx]), 1e-6)
    dmin_u8 = int(np.clip(round(dmin * 255.0), 0, 255))
    return dmin, cx, cy, dmin_u8


def estimate_dmin_from_track_center(img, top, bottom, left, right, rotate=0,
                                    soundtrack_color="B&W", negative=False):
    """Backward-compatible wrapper for center-point Dmin estimation."""
    return estimate_dmin_from_track_point(
        img, top, bottom, left, right, rotate, soundtrack_color, None, None, negative
    )


def apply_binary_mask_threshold(img_float, negative, binary_lb=96, binary_ub=255):
    """Apply OpenCV binary threshold on a [0,1] float image and return [0,1]."""
    lb = int(np.clip(binary_lb, 0, 255))
    ub = int(np.clip(binary_ub, 0, 255))
    img_u8 = np.clip(img_float * 255.0, 0, 255).astype(np.uint8)
    thresh_type = cv2.THRESH_BINARY_INV if negative else cv2.THRESH_BINARY
    _, mask_u8 = cv2.threshold(img_u8, lb, ub, thresh_type)
    return mask_u8.astype(np.float64) / 255.0


# ---------------------------------------------------------------------------
# Audio extraction
# ---------------------------------------------------------------------------

def extract_scanline_audio(corrected_img):
    """Extract one audio sample per row by averaging brightness across the track width.

    Each row (scanline) of the cropped soundtrack image represents one audio sample.
    The mean brightness across the row gives the instantaneous amplitude [0,1].
    """
    return np.mean(corrected_img, axis=1)


def extract_stereo_scanline_audio(corrected_img):
    """Extract stereo audio from a corrected image.

    Splits the image down the center column. The inner half (left side of image)
    becomes the LEFT channel, the outer half (right side) becomes the RIGHT channel.
    Returns (left_samples, right_samples).
    """
    mid = corrected_img.shape[1] // 2
    left_ch = np.mean(corrected_img[:, :mid], axis=1)
    right_ch = np.mean(corrected_img[:, mid:], axis=1)
    return left_ch, right_ch


# ---------------------------------------------------------------------------
# Overlap stitching
# ---------------------------------------------------------------------------

# Guards the O(L^2) vectorized overlap-error computation below from growing
# unbounded on a pathological crop/overlap-fraction combination (very tall
# crop + large --overlap). Above this size, _overlap_errors() falls back to
# the original per-offset Python loop instead of risking a multi-hundred-MB
# temporary-array spike on memory-constrained hardware (e.g. Raspberry Pi).
_OVERLAP_VECTORIZE_MAX_L = 3000


def _overlap_errors_loop(prev_samples, curr_samples, search_range):
    """Original per-offset loop: mean(|prev[-o:] - curr[:o]|) for o in
    1..search_range-1. Kept as the fallback for very large search ranges
    (see _OVERLAP_VECTORIZE_MAX_L) and as the reference implementation
    _overlap_errors_vectorized() is checked against in tests."""
    errors = np.empty(search_range - 1, dtype=np.float64)
    for offset in range(1, search_range):
        errors[offset - 1] = np.mean(np.abs(prev_samples[-offset:] - curr_samples[:offset]))
    return errors


def _overlap_errors_vectorized(prev_samples, curr_samples, search_range):
    """Vectorized replacement for _overlap_errors_loop(): computes the same
    per-offset mean-absolute-difference values, without a Python-level loop
    over offsets.

    For offset o, the compared windows are prev_samples[-o:] and
    curr_samples[:o] — both length o, paired element-by-element in order.
    Writing L = search_range - 1, prev_tail = prev_samples[-L:] and
    curr_head = curr_samples[:L], the k-th element (k = 0..o-1) of that
    comparison is prev_tail[L-o+k] vs curr_head[k] — a fixed indexing
    pattern that only depends on (o, k), not on any running state. That
    lets every offset's window be gathered in one vectorized pass over an
    (L, L) grid instead of one Python-level numpy call per offset:
      - row r = o - 1 (r = 0..L-1)
      - column k = 0..L-1, valid where k <= r (i.e. k < o)
      - prev index for (r, k) is L-1-r+k, always in [0, L-1] where valid.
    """
    L = search_range - 1
    if L > _OVERLAP_VECTORIZE_MAX_L:
        return _overlap_errors_loop(prev_samples, curr_samples, search_range)

    prev_tail = prev_samples[-L:]
    curr_head = curr_samples[:L]

    r = np.arange(L)[:, None]
    k = np.arange(L)[None, :]
    valid = k <= r
    # Clip so out-of-range (invalid) positions still index safely into
    # prev_tail -- their values are discarded by `valid` below regardless.
    prev_idx = np.clip((L - 1 - r) + k, 0, L - 1)
    diff = np.abs(prev_tail[prev_idx] - curr_head)  # curr_head broadcasts over rows

    counts = valid.sum(axis=1)
    sums = np.sum(diff, axis=1, where=valid)
    return sums / counts


def find_best_overlap(prev_samples, curr_samples, max_overlap):
    """Find the overlap offset that best aligns the end of prev with the start of curr.

    Slides the two waveforms against each other and returns the offset (in samples)
    that minimizes the mean absolute difference — the same approach AEO-Light uses.
    """
    search_range = min(max_overlap, len(prev_samples) // 2, len(curr_samples) // 2)
    if search_range < 2:
        return 0

    errors = _overlap_errors_vectorized(prev_samples, curr_samples, search_range)
    # argmin returns the first occurrence of the minimum, matching the
    # original loop's strict `<` comparison (first strictly-lower error
    # wins ties, earlier offsets are never displaced by an equal error).
    best_offset = int(np.argmin(errors)) + 1

    return best_offset


def stitch_with_overlap(frame_audio_list, max_overlap_frac):
    """Stitch frame audio arrays with overlap detection and cross-fade blending.

    For each consecutive pair of frames:
      1. Find the best overlap alignment (minimum absolute difference)
      2. Cross-fade in the overlap region to avoid clicks
      3. Concatenate the non-overlapping portions
    """
    if not frame_audio_list:
        return np.array([], dtype=np.float64)
    if len(frame_audio_list) == 1 or max_overlap_frac <= 0:
        return np.concatenate(frame_audio_list)

    frame_len = len(frame_audio_list[0])
    max_overlap = int(frame_len * max_overlap_frac)

    result = frame_audio_list[0].copy()

    for i in range(1, len(frame_audio_list)):
        curr = frame_audio_list[i]
        overlap = find_best_overlap(result, curr, max_overlap)

        if overlap > 0:
            # Cross-fade: linear blend in the overlap region
            fade_out = np.linspace(1.0, 0.0, overlap)
            fade_in = np.linspace(0.0, 1.0, overlap)
            blended = result[-overlap:] * fade_out + curr[:overlap] * fade_in

            # Replace the tail of result with the blended region, then append the rest
            result = np.concatenate([result[:-overlap], blended, curr[overlap:]])
        else:
            result = np.concatenate([result, curr])

    return result


def compute_overlap_offsets(frame_audio_list, max_overlap_frac):
    """Compute the overlap offset for each consecutive frame pair.

    Returns a list of offsets (length = len(frame_audio_list) - 1).
    Uses the mono signal to determine alignment.
    """
    if len(frame_audio_list) < 2 or max_overlap_frac <= 0:
        return [0] * max(0, len(frame_audio_list) - 1)

    frame_len = len(frame_audio_list[0])
    max_overlap = int(frame_len * max_overlap_frac)
    offsets = []

    # Build running tail for overlap detection
    prev_tail = frame_audio_list[0].copy()
    for i in range(1, len(frame_audio_list)):
        curr = frame_audio_list[i]
        offset = find_best_overlap(prev_tail, curr, max_overlap)
        offsets.append(offset)
        # Advance: the "result" tail after stitching this frame
        if offset > 0:
            prev_tail = curr  # after cross-fade, tail is curr
        else:
            prev_tail = curr
    return offsets


def apply_overlap_offsets(frame_audio_list, offsets):
    """Stitch frames using pre-computed overlap offsets with cross-fade blending."""
    if not frame_audio_list:
        return np.array([], dtype=np.float64)
    if len(frame_audio_list) == 1:
        return frame_audio_list[0].copy()

    result = frame_audio_list[0].copy()
    for i in range(1, len(frame_audio_list)):
        curr = frame_audio_list[i]
        overlap = offsets[i - 1]
        if overlap > 0:
            fade_out = np.linspace(1.0, 0.0, overlap)
            fade_in = np.linspace(0.0, 1.0, overlap)
            blended = result[-overlap:] * fade_out + curr[:overlap] * fade_in
            result = np.concatenate([result[:-overlap], blended, curr[overlap:]])
        else:
            result = np.concatenate([result, curr])
    return result


# ---------------------------------------------------------------------------
# Overlap/splice preview (for UI)
# ---------------------------------------------------------------------------

def _load_overlap_frame_pair(source, index, top, bottom, left, right,
                              rotate=0, negative=False, soundtrack_color="B&W",
                              dmin_percentile=99.5, dmin_headroom=0.2,
                              binary_mask=False, binary_lb=96, binary_ub=255,
                              dmin_value=None, integrate=False):
    """Load and correct the two source frames actually shown for picture-frame
    *index* and *index* + 1, i.e. the frames on screen in the UI.

    This intentionally ignores audio_offset: the splice preview is meant to
    show what the user is currently looking at spliced against the next
    frame, not the audio_offset-shifted source frames that extract_audio()
    reads for that picture-frame join.

    Returns (corrected_a, corrected_b, prev_idx, next_idx).
    Raises ValueError if either source frame is out of range or unreadable.
    """
    prev_idx = index
    next_idx = index + 1

    if prev_idx < 0 or prev_idx >= source.num_frames:
        raise ValueError(
            f"Frame {prev_idx} is out of range (0-{source.num_frames - 1})"
        )
    if next_idx < 0 or next_idx >= source.num_frames:
        raise ValueError(
            f"Frame {next_idx} is out of range (0-{source.num_frames - 1})"
        )

    img_a = source.load_frame(prev_idx)
    img_b = source.load_frame(next_idx)
    if img_a is None or img_b is None:
        raise ValueError("Could not read one or both frames for the splice preview")

    kwargs = dict(
        rotate=rotate, negative=negative, soundtrack_color=soundtrack_color,
        dmin_percentile=dmin_percentile, dmin_headroom=dmin_headroom,
        binary_mask=binary_mask, binary_lb=binary_lb, binary_ub=binary_ub,
        dmin_value=dmin_value, integrate=integrate,
    )
    corrected_a = crop_and_correct(img_a, top, bottom, left, right, **kwargs)
    corrected_b = crop_and_correct(img_b, top, bottom, left, right, **kwargs)
    return corrected_a, corrected_b, prev_idx, next_idx


def build_overlap_splice_image(corrected_a, corrected_b, overlap_frac):
    """Stack the bottom of frame A's crop against the top of frame B's crop.

    Returns a [0,1] float image (same width as the crops) spanning the
    overlap search window, for visual inspection of how the two frames'
    soundtrack pixels line up at the join.
    """
    if overlap_frac <= 0:
        raise ValueError("Overlap must be greater than 0 to preview the splice")

    frame_len = corrected_a.shape[0]
    max_overlap = int(frame_len * overlap_frac)
    max_overlap = min(max_overlap, corrected_a.shape[0], corrected_b.shape[0])
    if max_overlap <= 0:
        raise ValueError("Overlap window is too small to preview the splice")

    return np.concatenate([corrected_a[-max_overlap:], corrected_b[:max_overlap]], axis=0)


def _find_best_overlap_with_error(prev_samples, curr_samples, max_overlap):
    """Same search as find_best_overlap(), but also returns the winning
    mean-absolute-difference score so callers can report alignment quality."""
    search_range = min(max_overlap, len(prev_samples) // 2, len(curr_samples) // 2)
    if search_range < 2:
        return 0, 0.0

    errors = _overlap_errors_vectorized(prev_samples, curr_samples, search_range)
    best_idx = int(np.argmin(errors))

    return best_idx + 1, float(errors[best_idx])


def compute_overlap_waveform(corrected_a, corrected_b, overlap_frac, stereo=False,
                              channel_order="LR"):
    """Compute the overlap alignment + preview waveform data between two
    corrected frame crops, for UI display.

    Mirrors the real stitching math in stitch_with_overlap(): finds the
    offset that best aligns the tail of A with the head of B (using the
    mono mix when *stereo*, exactly like extract_audio() does so channels
    stay sample-synced), then builds the same cross-faded join preview.

    Returns a dict:
        {offset, max_overlap, stereo,
         channels: {<name>: {context_prev, context_next, stitched, error}}}
    channels is {"mono": ...} when not stereo, else {"left": ..., "right": ...}.
    Raises ValueError if overlap_frac <= 0 or the overlap window is empty.
    """
    if overlap_frac <= 0:
        raise ValueError("Overlap must be greater than 0 to preview the splice")

    if stereo:
        left_a, right_a = extract_stereo_scanline_audio(corrected_a)
        left_b, right_b = extract_stereo_scanline_audio(corrected_b)
        if channel_order == "RL":
            left_a, right_a = right_a, left_a
            left_b, right_b = right_b, left_b
        mono_a = (left_a + right_a) / 2.0
        mono_b = (left_b + right_b) / 2.0
        channel_samples = {"left": (left_a, left_b), "right": (right_a, right_b)}
        align_a, align_b = mono_a, mono_b
    else:
        mono_a = extract_scanline_audio(corrected_a)
        mono_b = extract_scanline_audio(corrected_b)
        channel_samples = {"mono": (mono_a, mono_b)}
        align_a, align_b = mono_a, mono_b

    frame_len = len(align_a)
    max_overlap = int(frame_len * overlap_frac)
    max_overlap = max(0, min(max_overlap, len(align_a) // 2, len(align_b) // 2))
    if max_overlap <= 0:
        raise ValueError("Overlap window is too small to preview the splice")

    offset, _ = _find_best_overlap_with_error(align_a, align_b, max_overlap)

    channels = {}
    for name, (samples_a, samples_b) in channel_samples.items():
        context_prev = samples_a[-max_overlap:]
        context_next = samples_b[:max_overlap]

        if offset > 0:
            fade_out = np.linspace(1.0, 0.0, offset)
            fade_in = np.linspace(0.0, 1.0, offset)
            blended = context_prev[-offset:] * fade_out + context_next[:offset] * fade_in
            stitched = np.concatenate([context_prev[:-offset], blended, context_next[offset:]])
            chan_error = float(np.mean(np.abs(context_prev[-offset:] - context_next[:offset])))
        else:
            stitched = np.concatenate([context_prev, context_next])
            chan_error = 0.0

        channels[name] = {
            "context_prev": context_prev.tolist(),
            "context_next": context_next.tolist(),
            "stitched": stitched.tolist(),
            "error": chan_error,
        }

    return {
        "offset": int(offset),
        "max_overlap": int(max_overlap),
        "stereo": bool(stereo),
        "channels": channels,
    }


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def apply_lowpass(signal, cutoff, sample_rate, order=5):
    """Butterworth low-pass filter using second-order sections."""
    nyquist = sample_rate / 2.0
    if cutoff >= nyquist:
        return signal  # nothing to filter
    sos = butter(order, cutoff / nyquist, btype="low", output="sos")
    return sosfilt(sos, signal)


def apply_highpass(signal, cutoff, sample_rate, order=2):
    """Butterworth high-pass filter using second-order sections."""
    nyquist = sample_rate / 2.0
    if cutoff <= 0:
        return signal
    sos = butter(order, cutoff / nyquist, btype="high", output="sos")
    return sosfilt(sos, signal)


def _chunked_resample(signal, target_n, chunk_seconds=30, sample_rate_hint=48000):
    """Resample a signal in chunks to avoid a single enormous FFT.

    Processes the signal in overlapping chunks, then concatenates.  This keeps
    peak memory usage bounded regardless of total signal length.
    """
    n = len(signal)
    if n <= chunk_seconds * sample_rate_hint:
        return resample(signal, target_n)

    chunk_src = chunk_seconds * sample_rate_hint
    overlap_src = min(chunk_src // 10, 4800)  # 10% overlap for smooth joins
    ratio = target_n / n

    parts = []
    pos = 0
    while pos < n:
        end = min(pos + chunk_src, n)
        # Extend chunk by overlap on both sides for smoother edges
        src_start = max(0, pos - overlap_src)
        src_end = min(n, end + overlap_src)
        chunk = signal[src_start:src_end]
        tgt_len = int(len(chunk) * ratio)
        resampled = resample(chunk, tgt_len)
        # Trim the overlap regions from the resampled output
        trim_left = int((pos - src_start) * ratio)
        trim_right = int((src_end - end) * ratio)
        if trim_right > 0:
            resampled = resampled[trim_left:-trim_right]
        else:
            resampled = resampled[trim_left:]
        parts.append(resampled)
        pos = end

    return np.concatenate(parts)


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".dpx", ".exr"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv"}
SOUNDTRACK_COLOR_CHOICES = ("B&W", "High-Magenta", "Cyan")


def parse_soundtrack_color_arg(value):
    """Normalize CLI soundtrack-color values to canonical labels."""
    raw = str(value).strip()
    key = raw.lower().replace("_", "-")
    if key in {"b&w", "bw", "blackwhite", "black-and-white"}:
        return "B&W"
    if key in {"high-magenta", "highmagenta", "magenta"}:
        return "High-Magenta"
    if key == "cyan":
        return "Cyan"
    raise argparse.ArgumentTypeError(
        "Invalid --soundtrack-color value. Use one of: B&W, High-Magenta, Cyan"
    )


def select_soundtrack_channel(img, soundtrack_color="B&W"):
    """Return a grayscale uint8 image for extraction based on soundtrack color rules.

    Rules:
      - If image is already monochrome, keep it as-is.
      - Otherwise use GREEN for B&W and High-Magenta.
      - Otherwise use RED for Cyan.
    """
    if img is None:
        return None

    if img.ndim == 2:
        return img

    if img.ndim == 3 and img.shape[2] == 1:
        return img[:, :, 0]

    if img.ndim != 3 or img.shape[2] < 3:
        raise ValueError("Unsupported image format for soundtrack extraction")

    b = img[:, :, 0]
    g = img[:, :, 1]
    r = img[:, :, 2]

    # Treat tiny channel differences as monochrome (common with compressed video).
    mono_like = (
        np.max(cv2.absdiff(b, g)) <= 1
        and np.max(cv2.absdiff(g, r)) <= 1
        and np.max(cv2.absdiff(b, r)) <= 1
    )
    if mono_like:
        return g

    if soundtrack_color == "Cyan":
        return r
    return g


# ---------------------------------------------------------------------------
# Frame source abstraction
# ---------------------------------------------------------------------------

def _read_image_file(path):
    """Read a single image file as uint8 (grayscale or BGR), or None on failure.

    Dispatches .dpx files to dpx_reader (OpenCV has no DPX codec); everything
    else goes through cv2.imread as before.
    """
    if os.path.splitext(path)[1].lower() == ".dpx":
        try:
            return dpx_reader.read_dpx(path)
        except dpx_reader.DPXError as e:
            print(f"Warning: {e}", file=sys.stderr)
            return None
    return cv2.imread(path, cv2.IMREAD_UNCHANGED)


class ImageSequenceSource:
    """Frame source backed by a directory of image files."""

    def __init__(self, input_dir):
        self._input_dir = input_dir
        self._filenames = list_frames(input_dir)
        if not self._filenames:
            raise ValueError(f"No image files found in '{input_dir}'")
        first = _read_image_file(os.path.join(input_dir, self._filenames[0]))
        if first is None:
            raise RuntimeError(f"Could not read first frame: {self._filenames[0]}")
        self._frame_height, self._frame_width = first.shape[:2]

    @property
    def num_frames(self):
        return len(self._filenames)

    @property
    def frame_width(self):
        return self._frame_width

    @property
    def frame_height(self):
        return self._frame_height

    @property
    def fps(self):
        return None

    @property
    def input_dir(self):
        return self._input_dir

    @property
    def filenames(self):
        """Naturally-sorted list of frame filenames (read-only copy)."""
        return list(self._filenames)

    def frame_path(self, index):
        """Absolute path to the frame file at *index*, or None if out of range."""
        if index < 0 or index >= len(self._filenames):
            return None
        return os.path.abspath(os.path.join(self._input_dir, self._filenames[index]))

    def load_frame(self, index):
        """Load frame by index as uint8 image (grayscale or color) or None."""
        if index < 0 or index >= len(self._filenames):
            return None
        return _read_image_file(os.path.join(self._input_dir, self._filenames[index]))


class VideoSource:
    """Frame source backed by a video file (mp4, mov, avi, mkv)."""

    def __init__(self, video_path):
        self._path = video_path
        self._cap = cv2.VideoCapture(video_path)
        if not self._cap.isOpened():
            raise ValueError(f"Could not open video: {video_path}")
        self._num_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._fps = self._cap.get(cv2.CAP_PROP_FPS)
        self._frame_width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._frame_height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._lock = threading.Lock()

    @property
    def num_frames(self):
        return self._num_frames

    @property
    def frame_width(self):
        return self._frame_width

    @property
    def frame_height(self):
        return self._frame_height

    @property
    def fps(self):
        return self._fps

    @property
    def path(self):
        return self._path

    def load_frame(self, index):
        """Seek to *index* and return the frame as uint8 image (or None)."""
        if index < 0 or index >= self._num_frames:
            return None
        with self._lock:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = self._cap.read()
        if not ok or frame is None:
            return None
        return frame

    def iter_frames(self, start, stop):
        """Yield (index, frame) for index in [start, stop] (inclusive),
        decoding sequentially after a single seek to *start* instead of
        load_frame()'s seek-per-call.

        For most codecs (anything with GOPs, e.g. H.264/HEVC),
        load_frame()'s CAP_PROP_POS_FRAMES seek forces a decode from the
        nearest preceding keyframe forward to the target on every call --
        calling it in an ascending loop redoes that keyframe-to-target
        decode work every single frame. This method decodes forward once
        instead.

        Uses a second, independent cv2.VideoCapture opened on the same
        file rather than self._cap/self._lock -- video files support
        multiple independent read handles, so this never contends with
        load_frame()'s random-access callers (e.g. server.py's frame
        preview endpoints), which keep using load_frame() unchanged.

        Stops early (without raising) if a read fails before reaching
        *stop* -- e.g. the container's reported frame count was slightly
        optimistic. Callers must treat any index in [start, stop] that was
        never yielded as missing, exactly like a load_frame() None return.
        """
        start = max(0, start)
        stop = min(stop, self._num_frames - 1)
        if start > stop:
            return
        cap = cv2.VideoCapture(self._path)
        try:
            if not cap.isOpened():
                return
            if start > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, start)
            for index in range(start, stop + 1):
                ok, frame = cap.read()
                if not ok or frame is None:
                    return
                yield index, frame
        finally:
            cap.release()

    def close(self):
        self._cap.release()


def open_source(path):
    """Open a frame source from a directory of images or a video file."""
    p = os.path.abspath(path)
    if os.path.isfile(p):
        ext = os.path.splitext(p)[1].lower()
        if ext in VIDEO_EXTS:
            return VideoSource(p)
        raise ValueError(f"Unsupported file type: {ext}")
    if os.path.isdir(p):
        return ImageSequenceSource(p)
    raise ValueError(f"Path not found: {p}")


# ---------------------------------------------------------------------------
# Reusable helpers for the web UI and CLI
# ---------------------------------------------------------------------------

def list_frames(input_dir):
    """Return naturally-sorted list of image filenames in *input_dir*."""
    names = [f for f in os.listdir(input_dir)
             if os.path.splitext(f)[1].lower() in SUPPORTED_EXTS]
    return natsort.natsorted(names)


def load_frame(input_dir, filename):
    """Load a single frame as a uint8 numpy array (grayscale or color)."""
    return _read_image_file(os.path.join(input_dir, filename))


def rotate_image(img, degrees):
    """Rotate an image by 0/90/180/270 degrees clockwise."""
    if degrees == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if degrees == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if degrees == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


# NOTE on GPU/OpenCL: this function's actual per-pixel math (dtype cast,
# invert, clip, Dmin's np.percentile, the scanline row-mean) is plain NumPy
# on float64 arrays, not cv2 -- routing it through cv2.UMat/OpenCL would
# only touch the few incidental cv2 calls here (absdiff in
# select_soundtrack_channel, threshold in apply_binary_mask_threshold,
# rotate in rotate_image), not the real per-pixel work, short of a much
# larger rewrite around cv2/UMat or a tensor library (Torch/CuPy). It was
# evaluated and deliberately deprioritized in favor of the CPU-side fixes
# in this module (sequential VideoSource decoding, thread-pool frame
# parallelism, vectorized overlap search): those target the actual
# measured bottlenecks and are portable to every platform, including the
# weak-hardware target this app names in README.md (Raspberry Pi/Ampere
# arm64), where OpenCL support is unreliable-to-absent in practice -- a
# UMat path would likely just no-op back to CPU there while adding real
# packaging risk (no existing PyInstaller GPU-library hooks; opencv-python
# itself already lacks a Windows ARM64 wheel, a bad sign for bundling a
# GPU tensor library too). Worth revisiting only if profiling after those
# CPU-side fixes still shows the cv2-side calls specifically (not the
# NumPy math) as a bottleneck.
def crop_and_correct(img, top, bottom, left, right, rotate=0,
                     negative=False, soundtrack_color="B&W",
                     dmin_percentile=99.5, dmin_headroom=0.2,
                     binary_mask=False, binary_lb=96, binary_ub=255,
                     dmin_value=None, integrate=False):
    """Crop, rotate, channel-select, and prepare a frame for extraction.

    Returns the corrected image as a float64 array in [0, 1].

    When *integrate* is True (Average Pixel Value mode), Dmin normalization and
    binary-mask thresholding are skipped so that raw channel transmittance is
    preserved linearly — the correct approach for synthetic SVA renders with
    anti-aliased edges. When False (Binary Pixel Value mode), Dmin normalization
    is applied and binary-mask thresholding is available on top of it.
    """
    cropped = img[top:bottom, left:right]
    cropped = select_soundtrack_channel(cropped, soundtrack_color)
    cropped = rotate_image(cropped, rotate)
    img_float = cropped.astype(np.float64) / 255.0
    corrected = correct_image(img_float, negative)
    if integrate:
        return corrected
    normalized = normalize_track_by_dmin(
        corrected, dmin_percentile, dmin_headroom, dmin_value
    )
    if binary_mask:
        return apply_binary_mask_threshold(normalized, negative, binary_lb, binary_ub)
    return normalized


def correct_full_frame(img, negative=False, soundtrack_color="B&W",
                       dmin_percentile=99.5, dmin_headroom=0.2,
                       binary_mask=False, binary_lb=96, binary_ub=255,
                       dmin_value=None, integrate=False):
    """Apply corrections to the full frame (no crop/rotation). Returns float64 [0,1]."""
    img = select_soundtrack_channel(img, soundtrack_color)
    img_float = img.astype(np.float64) / 255.0
    corrected = correct_image(img_float, negative)
    if integrate:
        return corrected
    normalized = normalize_track_by_dmin(
        corrected, dmin_percentile, dmin_headroom, dmin_value
    )
    if binary_mask:
        return apply_binary_mask_threshold(normalized, negative, binary_lb, binary_ub)
    return normalized


def corrected_to_jpeg(img_corrected):
    """Encode a [0,1] float image as JPEG bytes for the web preview."""
    uint8 = (img_corrected * 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", uint8, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()


def frame_to_jpeg(img):
    """Encode a raw uint8 image (grayscale or color) as JPEG bytes."""
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()


# ---------------------------------------------------------------------------
# Thread-pool frame processing (shared by extract_audio() and CLI main())
# ---------------------------------------------------------------------------

def _default_pool_size():
    """Default thread-pool size for parallel frame processing: enough to
    get real concurrency without hardcoding a large pool that starves the
    UI/server thread (or other work happening alongside the CLI) on a
    low-core machine like a Raspberry Pi."""
    return min(os.cpu_count() or 4, 8)


def _run_video_frame_pool(source, position_by_source_idx, process_one, cancel_event, num_workers):
    """Decode source's frames sequentially via iter_frames() (video decode
    is inherently stateful -- this part can't itself be parallelized),
    while a pool of worker threads runs process_one(position, img)
    concurrently on already-decoded frames (pure CPU, no shared state,
    parallelizes cleanly).

    process_one(position, img) is called concurrently from worker threads
    for distinct positions -- safe here since crop_and_correct()/
    extract_scanline_audio() are pure functions with no shared mutable
    state, and each call only ever writes its own position's output slot.

    Raises whatever process_one raised (re-raised on the calling thread),
    or ExtractionCancelled if cancel_event was set. Returns the set of
    positions actually processed -- callers compare this against
    position_by_source_idx's positions to find frames that were requested
    but never decoded (e.g. a read failed before reaching the end of the
    range) and must be treated as missing, same as a load_frame() None.
    """
    if not position_by_source_idx:
        return set()

    lo = min(position_by_source_idx)
    hi = max(position_by_source_idx)

    # Bounded so the sequential decode (one fast, CPU-bound C call per
    # frame) can't race arbitrarily far ahead of the worker pool and pile
    # up decoded frames in memory -- a real concern at scan resolution on
    # memory-constrained hardware.
    work_q = queue.Queue(maxsize=max(2 * num_workers, 8))
    stop = threading.Event()
    errors = []
    errors_lock = threading.Lock()
    processed = set()
    processed_lock = threading.Lock()

    def _cancelled():
        return stop.is_set() or (cancel_event is not None and cancel_event.is_set())

    def worker():
        while True:
            item = work_q.get()
            try:
                if item is None:
                    return
                if _cancelled():
                    continue
                position, img = item
                try:
                    process_one(position, img)
                except Exception as exc:
                    with errors_lock:
                        errors.append(exc)
                    stop.set()
                else:
                    with processed_lock:
                        processed.add(position)
            finally:
                work_q.task_done()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(num_workers)]
    for t in threads:
        t.start()

    try:
        with contextlib.closing(source.iter_frames(lo, hi)) as frames:
            for s_idx, img in frames:
                if _cancelled():
                    break
                position = position_by_source_idx.get(s_idx)
                if position is None:
                    continue
                work_q.put((position, img))
    finally:
        for _ in threads:
            work_q.put(None)
        for t in threads:
            t.join()

    if errors:
        raise errors[0]
    # Only raise for cancellation that actually left work undone -- if
    # cancel_event happened to flip just as the very last frame finished,
    # let the (complete, correct) result through rather than discarding it
    # on a narrow race.
    if cancel_event is not None and cancel_event.is_set() and len(processed) < len(position_by_source_idx):
        raise ExtractionCancelled()

    return processed


def _run_sequence_frame_pool(positions, load_one, process_one, cancel_event, num_workers):
    """Parallelize independent per-position work (load_one(position) then
    process_one(position, img)) across a thread pool.

    Used for ImageSequenceSource, where each frame is its own file read
    (cv2.imread/dpx) with no shared decode state -- unlike VideoSource,
    there's no single stateful decoder to bottleneck on, so both the file
    I/O and the crop/correct/reduce work parallelize across threads
    directly.

    Returns the set of positions that were both present (load_one()
    returned a non-None image) and successfully processed; callers treat
    any position not in that set as missing.
    """
    if not positions:
        return set()

    processed = set()
    processed_lock = threading.Lock()

    def task(position):
        if cancel_event is not None and cancel_event.is_set():
            return
        img = load_one(position)
        if img is None:
            return
        process_one(position, img)
        with processed_lock:
            processed.add(position)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=num_workers)
    try:
        futures = [executor.submit(task, position) for position in positions]
        for future in concurrent.futures.as_completed(futures):
            if cancel_event is not None and cancel_event.is_set():
                break
            future.result()  # re-raises any exception from task()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    # Only raise for cancellation that actually left work undone -- see the
    # matching comment in _run_video_frame_pool().
    if cancel_event is not None and cancel_event.is_set() and len(processed) < len(positions):
        raise ExtractionCancelled()

    return processed


def extract_audio(source, top, bottom, left, right,
                  rotate=0, negative=False, fps=24.0, sample_rate=48000,
                  hpf=40.0, lpf=13500.0, overlap=0.25, audio_offset=21,
                  stereo=False, progress_callback=None, reverse=False,
                  phase_callback=None, start_frame=0, end_frame=None,
                  soundtrack_color="B&W", dmin_percentile=99.5,
                  dmin_headroom=0.2, binary_mask=False,
                  binary_lb=96, binary_ub=255, dmin_value=None,
                  integrate=False, bit_depth="int16", cancel_event=None,
                  progress_every=20, channel_order="LR"):
    """Run the full extraction pipeline. Returns (sample_rate, sample_array).

    *source* is a FrameSource object (ImageSequenceSource or VideoSource).
    When *stereo* is True, returns a 2-channel array (N, 2).
    *channel_order* controls which physical half of the split soundtrack
    maps to which output channel: "LR" (default) keeps the image's inner
    half as the left channel and the outer half as the right; "RL" swaps
    them, for scans whose track runs right-to-left. Ignored when *stereo*
    is False.
    *bit_depth* selects the output sample format — one of "int16" (default),
    "int24", "int32", or "float32"; see _quantize_audio().
    *cancel_event*, if provided, is a threading.Event checked periodically
    during the run — ExtractionCancelled is raised as soon as it's set.
    *progress_callback*, if provided, is called with (current, total) every
    *progress_every* frames (and always on the last frame). Calling it on
    every single frame sounds free — it's just a couple of attribute
    writes — but it isn't free end-to-end: server.py's frame viewer treats
    each distinct reported frame as a real position change and re-fetches
    a freshly decoded/corrected preview image for it, so reporting too
    finely turns every progress tick into extra concurrent image work
    competing with this loop's own CPU-heavy decode/correct work. 20 is a
    reasonable default; raise it for less UI churn, lower it (e.g. 1) for
    maximum frame-viewer granularity if the caller can afford it.
    *phase_callback*, if provided, is called with a string describing the
    current processing phase.
    *start_frame* and *end_frame* allow processing a sub-range of frames
    (end_frame is inclusive; defaults to the last frame) — this is the
    picture frame range; it stays fixed regardless of *audio_offset*.
    *audio_offset* corrects for the physical sound advance printed on
    optical film: the soundtrack for picture frame N is printed earlier
    in the scan, at frame N - audio_offset, so each picture index in
    [start_frame, end_frame] is read for audio at (idx - audio_offset)
    rather than idx itself.

    The returned audio is NOT the same length as the picture range: it
    starts with audio_offset frames of silence (there is no scanned
    soundtrack before frame 0, so the first audio_offset picture frames
    have nothing to play), and it *extends* audio_offset frames past
    end_frame (the source frames at the very end of the scan hold real
    soundtrack data for picture positions beyond end_frame that were
    simply never scanned as picture — that real audio is kept rather than
    discarded). Net result: len(audio) == len(picture) + audio_offset
    frames' worth of samples, with a silent lead-in and a "real audio, no
    picture" tail. Callers muxing this against a picture track should NOT
    trim to the shorter stream (e.g. ffmpeg's -shortest) — the picture
    track ending before the audio track does is expected.
    """
    def _phase(msg):
        if phase_callback:
            phase_callback(msg)

    if end_frame is None:
        end_frame = source.num_frames - 1
    end_frame = min(end_frame, source.num_frames - 1)
    start_frame = max(0, start_frame)

    _phase("Processing frames")
    # Extend past end_frame by audio_offset frames to capture the real
    # trailing soundtrack data described above (only when audio_offset is
    # positive -- the physically-typical case of sound printed earlier).
    indices = list(range(start_frame, end_frame + 1 + max(audio_offset, 0)))
    if reverse:
        indices = indices[::-1]
    total = len(indices)
    # source_indices[position] is the source frame the picture at
    # indices[position] actually reads audio from (idx - audio_offset).
    # Since indices is a contiguous run (just reversed when *reverse*),
    # source_indices is too -- ascending when not reversed, descending when
    # reversed. VideoSource frames are always decoded in ascending source
    # order below (regardless of *reverse*) since seeking backwards isn't
    # efficient; results are placed into their correct output position via
    # position_by_source_idx, so the picture-order/decode-order mismatch
    # when reversed never affects correctness.
    source_indices = [idx - audio_offset for idx in indices]

    all_left = [None] * total
    all_right = [None] * total if stereo else None
    missing_indices = []

    completed = 0
    progress_lock = threading.Lock()

    def _mark_done():
        # See progress_every in the docstring: batched (not called every
        # frame) by default — reporting every frame makes server.py's
        # frame viewer re-fetch a preview image on nearly every progress
        # tick, which competes for CPU with this loop's own decode/correct
        # work rather than being the free couple-of-attribute-writes it
        # looks like in isolation. `completed` counts positions resolved
        # so far (real or backfilled-as-missing) -- it still advances
        # monotonically from 0 to `total` exactly once each regardless of
        # source-vs-picture or decode/completion order (worker threads call
        # this concurrently, hence the lock), which is all
        # progress_callback relies on.
        nonlocal completed
        with progress_lock:
            completed += 1
            current = completed
        if progress_callback and (current % progress_every == 0 or current == total):
            progress_callback(current, total)

    def _process_frame(position, img):
        # Called from worker threads (possibly concurrently, for distinct
        # positions) by the thread pools below -- safe since
        # crop_and_correct()/extract_*_scanline_audio() are pure functions
        # with no shared mutable state, and each call only ever writes its
        # own position's slot in all_left/all_right.
        corrected = crop_and_correct(
            img,
            top,
            bottom,
            left,
            right,
            rotate=rotate,
            negative=negative,
            soundtrack_color=soundtrack_color,
            dmin_percentile=dmin_percentile,
            dmin_headroom=dmin_headroom,
            binary_mask=binary_mask,
            binary_lb=binary_lb,
            binary_ub=binary_ub,
            dmin_value=dmin_value,
            integrate=integrate,
        )
        if stereo:
            l_ch, r_ch = extract_stereo_scanline_audio(corrected)
            all_left[position] = l_ch
            all_right[position] = r_ch
        else:
            all_left[position] = extract_scanline_audio(corrected)
        _mark_done()

    num_workers = _default_pool_size()

    if isinstance(source, VideoSource):
        # No corresponding source frame for this picture frame's
        # audio_offset-shifted soundtrack position -- most commonly because
        # idx - audio_offset is before the start of the scan. Recorded now
        # and backfilled with silence below (once a real chunk's length is
        # known) rather than dropped: dropping would shrink the output
        # track by audio_offset frames' worth of time and slide all audio
        # earlier, silently undoing the offset instead of applying it.
        position_by_source_idx = {}
        for position, s_idx in enumerate(source_indices):
            if s_idx < 0 or s_idx >= source.num_frames:
                missing_indices.append(position)
                _mark_done()
            else:
                position_by_source_idx[s_idx] = position

        processed = _run_video_frame_pool(
            source, position_by_source_idx, _process_frame, cancel_event, num_workers
        )
        # Anything the pool didn't reach (e.g. a read failed before hitting
        # the end of the range, despite being in the container's reported
        # frame count) becomes missing too, same as a load_frame() None.
        for s_idx, position in position_by_source_idx.items():
            if position not in processed:
                missing_indices.append(position)
                _mark_done()
    else:
        def _load_one(position):
            return source.load_frame(source_indices[position])

        positions = list(range(total))
        processed = _run_sequence_frame_pool(
            positions, _load_one, _process_frame, cancel_event, num_workers
        )
        for position in positions:
            if position not in processed:
                missing_indices.append(position)
                _mark_done()

    if len(missing_indices) == len(all_left):
        raise ValueError("No frames were successfully processed")

    if missing_indices:
        template = next(chunk for chunk in all_left if chunk is not None)
        silence = np.zeros_like(template)
        for i in missing_indices:
            all_left[i] = silence.copy()
            if stereo:
                all_right[i] = silence.copy()

    # Compute overlap offsets once from mono (or left channel) for sample-accurate sync
    if stereo and overlap > 0 and len(all_left) > 1:
        _phase("Computing overlap offsets")
        all_mono = [(l + r) / 2.0 for l, r in zip(all_left, all_right)]
        offsets = compute_overlap_offsets(all_mono, overlap)
    elif overlap > 0 and len(all_left) > 1:
        offsets = None  # use standard stitch_with_overlap for mono
    else:
        offsets = None

    def _process_channel(all_samples, label, shared_offsets=None):
        if cancel_event is not None and cancel_event.is_set():
            raise ExtractionCancelled()
        _phase(f"Stitching {label}")
        if shared_offsets is not None:
            raw_signal = apply_overlap_offsets(all_samples, shared_offsets)
        elif overlap > 0 and len(all_samples) > 1:
            raw_signal = stitch_with_overlap(all_samples, overlap)
        else:
            raw_signal = np.concatenate(all_samples)
        # Target length is anchored to the true elapsed time (n_frames / fps),
        # not to len(raw_signal) — overlap-based stitching removes genuinely
        # duplicated (overscanned) content, which shortens raw_signal without
        # changing how much real time these frames actually span. Deriving
        # target_n from raw_signal's length would shrink the output audio by
        # however much overlap was removed, drifting it out of sync with a
        # video track (which stays at full, uncompressed length).
        target_n = int(round(len(all_samples) / fps * sample_rate))
        _phase(f"Resampling {label}")
        signal = _chunked_resample(raw_signal, target_n)
        _phase(f"Filtering {label}")
        signal = apply_lowpass(signal, lpf, sample_rate)
        signal = apply_highpass(signal, hpf, sample_rate)
        peak = np.max(np.abs(signal))
        if peak > 0:
            signal = signal / peak
        return _quantize_audio(signal, bit_depth)

    left_samples = _process_channel(all_left, "audio" if not stereo else "left channel", offsets)
    if stereo:
        right_samples = _process_channel(all_right, "right channel", offsets)
        # channel_order == "RL" flips the track's left-to-right orientation:
        # the inner-half samples ("left_samples") are written as the output's
        # right channel and vice versa.
        if channel_order == "RL":
            signal_out = np.column_stack([right_samples, left_samples])
        else:
            signal_out = np.column_stack([left_samples, right_samples])
    else:
        signal_out = left_samples

    return sample_rate, signal_out


_BIT_DEPTHS = ("int16", "int24", "int32", "float32")


def _quantize_audio(signal, bit_depth):
    """Quantize a float64 signal already normalized to [-1, 1] into the
    given output sample format.

    int24 has no native numpy/C integer type, so its values are held in an
    int32 container (still only spanning the 24-bit signed range,
    [-2**23, 2**23 - 1]) — packing those into an actual 24-bit-per-sample
    WAV file happens in _write_wav_int24(), the only place that needs to
    know int24 is special.
    """
    if bit_depth == "int16":
        return np.clip(signal * 32767, -32768, 32767).astype(np.int16)
    if bit_depth == "int24":
        return np.clip(signal * 8388607, -8388608, 8388607).astype(np.int32)
    if bit_depth == "int32":
        return np.clip(signal * 2147483647, -2147483648, 2147483647).astype(np.int32)
    if bit_depth == "float32":
        return np.clip(signal, -1.0, 1.0).astype(np.float32)
    raise ValueError(f"Unsupported bit_depth: {bit_depth!r} (expected one of {_BIT_DEPTHS})")


def _write_wav_int24(buf, sample_rate, samples):
    """Write a standard 24-bit PCM WAV file.

    scipy.io.wavfile can't emit 24-bit output directly (there's no native
    int24 numpy/C type for it to infer a format from), so this packs each
    sample's low 3 bytes (little-endian) by hand into a minimal RIFF/WAVE
    container. *samples* holds int32 values already clipped to the 24-bit
    signed range by _quantize_audio() — for values in that range, dropping
    the top byte of their little-endian int32 form is exactly the correct
    3-byte two's-complement encoding (the dropped byte is pure sign
    extension, 0x00 or 0xFF).
    """
    mono = samples.ndim == 1
    n_channels = 1 if mono else samples.shape[1]
    interleaved = samples if mono else samples.reshape(-1)

    raw = interleaved.astype("<i4").tobytes()
    data = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 4)[:, :3].tobytes()
    if len(data) % 2:
        data += b"\x00"  # RIFF chunks must be even-sized

    bytes_per_sample = 3
    block_align = n_channels * bytes_per_sample
    byte_rate = sample_rate * block_align
    fmt_chunk = struct.pack("<HHIIHH", 1, n_channels, sample_rate, byte_rate, block_align, 24)

    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 4 + (8 + len(fmt_chunk)) + (8 + len(data))))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<I", len(fmt_chunk)))
    buf.write(fmt_chunk)
    buf.write(b"data")
    buf.write(struct.pack("<I", len(data)))
    buf.write(data)


def extract_audio_to_wav_bytes(source, bit_depth="int16", **kwargs):
    """Run extraction and return the WAV file as an in-memory bytes object."""
    sr, samples = extract_audio(source, bit_depth=bit_depth, **kwargs)
    buf = io.BytesIO()
    if bit_depth == "int24":
        _write_wav_int24(buf, sr, samples)
    else:
        wavfile.write(buf, sr, samples)
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# Main pipeline (CLI)
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    # --- Open frame source (directory or video file) ---
    try:
        source = open_source(args.input)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    num_frames = source.num_frames
    if source.fps is not None:
        print(f"Video source: {num_frames} frames at {source.fps:.3f} fps")
        if args.fps == 24.0:  # default — override with video fps
            args.fps = source.fps
    else:
        print(f"Image sequence: {num_frames} frames")

    top, bottom, left, right = args.crop
    print(f"Crop region: top={top} bottom={bottom} left={left} right={right}")
    print(f"Soundtrack color mode: {args.soundtrack_color}")
    print(f"Audio offset: {args.audio_offset} frames")
    if args.integrate:
        print("Pixel value mode: Average Pixel Value (SVA integration)")
    else:
        print(
            f"Pixel value mode: Binary Pixel Value — "
            f"Dmin normalize: value={args.dmin_value if args.dmin_value is not None else 'auto'}, "
            f"p{args.dmin_percentile:.1f}, "
            f"headroom={args.dmin_headroom:.3f}, "
            f"binary_mask={args.binary_mask} (lb={args.binary_lb}, ub={args.binary_ub})"
        )

    # --- Prepare crop dump directory if requested ---
    if args.dump_crops:
        os.makedirs(args.dump_crops, exist_ok=True)
        print(f"Dumping cropped images to '{args.dump_crops}/'")

    # --- Process frames ---
    # Extend past the last picture frame by audio_offset frames: the source
    # frames at the very end of the scan hold real soundtrack data for
    # picture positions beyond num_frames - 1 that were never scanned as
    # picture -- see extract_audio()'s docstring for the full explanation.
    indices = list(range(num_frames + max(args.audio_offset, 0)))
    if args.reverse:
        indices = indices[::-1]
    total_indices = len(indices)
    # See extract_audio()'s matching comment: source_indices is a constant
    # shift of `indices`, so it's contiguous ascending/descending too.
    # VideoSource frames are decoded in ascending source order below
    # (regardless of args.reverse) and placed into their correct output
    # position via position_by_source_idx.
    source_indices = [frame_idx - args.audio_offset for frame_idx in indices]

    all_samples = [None] * total_indices
    missing_indices = []
    completed = 0
    progress_lock = threading.Lock()

    def _mark_done():
        nonlocal completed
        with progress_lock:
            completed += 1
            current = completed
        if current % 50 == 0 or current == total_indices:
            print(f"  Processed {current}/{total_indices} frames", file=sys.stderr)

    def _process_frame(position, img):
        # May be called from worker threads (possibly concurrently, for
        # distinct positions) by the thread pools below -- see the matching
        # comment in extract_audio()'s _process_frame for why that's safe.
        frame_idx = indices[position]
        img_corrected = crop_and_correct(
            img,
            top,
            bottom,
            left,
            right,
            rotate=args.rotate,
            negative=args.negative,
            soundtrack_color=args.soundtrack_color,
            dmin_percentile=args.dmin_percentile,
            dmin_headroom=args.dmin_headroom,
            binary_mask=args.binary_mask,
            binary_lb=args.binary_lb,
            binary_ub=args.binary_ub,
            dmin_value=args.dmin_value,
            integrate=args.integrate,
        )

        # Dump cropped image if requested
        if args.dump_crops:
            dump_path = os.path.join(args.dump_crops, f"frame_{frame_idx:06d}.png")
            cv2.imwrite(dump_path, (img_corrected * 255).astype(np.uint8))

        # Extract audio: mean brightness per row → one sample per scanline
        all_samples[position] = extract_scanline_audio(img_corrected)
        _mark_done()

    def _note_missing(position):
        # No corresponding source frame for this picture frame's
        # audio_offset-shifted soundtrack position -- most commonly
        # because frame_idx - args.audio_offset is before the start of
        # the scan. Backfilled with silence below (once a real chunk's
        # length is known) rather than dropped: dropping would shrink
        # the output track by audio_offset frames' worth of time and
        # slide all audio earlier, silently undoing the offset instead
        # of applying it.
        print(f"  Note: no source frame at {source_indices[position]} "
              f"(audio_offset={args.audio_offset}); using silence.", file=sys.stderr)
        missing_indices.append(position)

    num_workers = _default_pool_size()

    if isinstance(source, VideoSource):
        position_by_source_idx = {}
        for position, s_idx in enumerate(source_indices):
            if s_idx < 0 or s_idx >= source.num_frames:
                _note_missing(position)
                _mark_done()
            else:
                position_by_source_idx[s_idx] = position

        processed = _run_video_frame_pool(
            source, position_by_source_idx, _process_frame, None, num_workers
        )
        for s_idx, position in position_by_source_idx.items():
            if position not in processed:
                _note_missing(position)
                _mark_done()
    else:
        def _load_one(position):
            return source.load_frame(source_indices[position])

        positions = list(range(total_indices))
        processed = _run_sequence_frame_pool(
            positions, _load_one, _process_frame, None, num_workers
        )
        for position in positions:
            if position not in processed:
                _note_missing(position)
                _mark_done()

    if len(missing_indices) == len(all_samples):
        print("Error: no frames were successfully processed", file=sys.stderr)
        sys.exit(1)

    if missing_indices:
        template = next(chunk for chunk in all_samples if chunk is not None)
        silence = np.zeros_like(template)
        for i in missing_indices:
            all_samples[i] = silence.copy()

    # Stitch frames with overlap detection and cross-fade
    if args.overlap > 0:
        print(f"Stitching frames with up to {args.overlap*100:.0f}% overlap search...")
        raw_signal = stitch_with_overlap(all_samples, args.overlap)
    else:
        raw_signal = np.concatenate(all_samples)
    native_rate = len(all_samples[0]) * args.fps  # use single-frame length for native rate
    print(f"Raw signal: {len(raw_signal)} samples at native rate ~{native_rate:.0f} Hz")

    # --- Resample to target sample rate ---
    # Target length is anchored to the true elapsed time (frame count / fps),
    # not to len(raw_signal): overlap-based stitching above removes
    # genuinely duplicated (overscanned) content, which shortens raw_signal
    # without changing how much real time these frames actually span.
    # Deriving the target from raw_signal's length would shrink the output
    # audio by however much overlap was removed.
    target_num_samples = int(round(len(all_samples) * args.sample_rate / args.fps))
    print(f"Resampling to {args.sample_rate} Hz ({target_num_samples} samples)...")
    signal = resample(raw_signal, target_num_samples)

    # --- Post-processing filters ---
    # Low-pass filter (anti-aliasing / noise removal)
    print(f"Applying low-pass filter at {args.lpf} Hz...")
    signal = apply_lowpass(signal, args.lpf, args.sample_rate)

    # High-pass filter (DC bias removal — the critical step)
    print(f"Applying high-pass filter at {args.hpf} Hz...")
    signal = apply_highpass(signal, args.hpf, args.sample_rate)

    # --- Normalize to signed 16-bit range ---
    peak = np.max(np.abs(signal))
    if peak > 0:
        signal = signal / peak  # normalize to [-1.0, +1.0]
    signal_int16 = np.clip(signal * 32767, -32768, 32767).astype(np.int16)

    # --- Write WAV ---
    wavfile.write(args.output, args.sample_rate, signal_int16)
    duration = len(signal_int16) / args.sample_rate
    print(f"Wrote {args.output}: {duration:.2f}s, {args.sample_rate} Hz, 16-bit mono")


if __name__ == "__main__":
    main()
