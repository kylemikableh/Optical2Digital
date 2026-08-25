# This file is part of Kyle's Optical Decoder.
#
# Copyright (C) 2026 Kyle Mikolajczyk
#
# Kyle's Optical Decoder is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# Kyle's Optical Decoder is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Kyle's Optical Decoder; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

"""
Kyle's Optical Decoder - Optical Film Soundtrack to WAV Extractor

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
import io
import os
import sys
import threading

import cv2
import numpy as np
import natsort
from scipy.io import wavfile
from scipy.signal import butter, sosfilt, resample

import dpx_reader


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

def find_best_overlap(prev_samples, curr_samples, max_overlap):
    """Find the overlap offset that best aligns the end of prev with the start of curr.

    Slides the two waveforms against each other and returns the offset (in samples)
    that minimizes the mean absolute difference — the same approach AEO-Light uses.
    """
    search_range = min(max_overlap, len(prev_samples) // 2, len(curr_samples) // 2)
    if search_range < 2:
        return 0

    best_offset = 0
    best_error = float("inf")

    for offset in range(1, search_range):
        error = np.mean(np.abs(prev_samples[-offset:] - curr_samples[:offset]))
        if error < best_error:
            best_error = error
            best_offset = offset

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


def extract_audio(source, top, bottom, left, right,
                  rotate=0, negative=False, fps=24.0, sample_rate=48000,
                  hpf=40.0, lpf=13500.0, overlap=0.25, audio_offset=21,
                  stereo=False, progress_callback=None, reverse=False,
                  phase_callback=None, start_frame=0, end_frame=None,
                  soundtrack_color="B&W", dmin_percentile=99.5,
                  dmin_headroom=0.2, binary_mask=False,
                  binary_lb=96, binary_ub=255, dmin_value=None,
                  integrate=False):
    """Run the full extraction pipeline. Returns (sample_rate, int16_array).

    *source* is a FrameSource object (ImageSequenceSource or VideoSource).
    When *stereo* is True, returns a 2-channel int16 array (N, 2).
    *progress_callback*, if provided, is called with (current, total) after
    each frame is processed.
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
    """
    def _phase(msg):
        if phase_callback:
            phase_callback(msg)

    if end_frame is None:
        end_frame = source.num_frames - 1
    end_frame = min(end_frame, source.num_frames - 1)
    start_frame = max(0, start_frame)

    _phase("Processing frames")
    all_left = []
    all_right = [] if stereo else None
    indices = list(range(start_frame, end_frame + 1))
    if reverse:
        indices = indices[::-1]
    total = len(indices)

    for count, idx in enumerate(indices):
        img = source.load_frame(idx - audio_offset)
        if img is None:
            continue
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
            all_left.append(l_ch)
            all_right.append(r_ch)
        else:
            all_left.append(extract_scanline_audio(corrected))
        if progress_callback and ((count + 1) % 20 == 0 or count + 1 == total):
            progress_callback(count + 1, total)

    if not all_left:
        raise ValueError("No frames were successfully processed")

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
        return np.clip(signal * 32767, -32768, 32767).astype(np.int16)

    left_int16 = _process_channel(all_left, "audio" if not stereo else "left channel", offsets)
    if stereo:
        right_int16 = _process_channel(all_right, "right channel", offsets)
        signal_int16 = np.column_stack([left_int16, right_int16])
    else:
        signal_int16 = left_int16

    return sample_rate, signal_int16


def extract_audio_to_wav_bytes(source, **kwargs):
    """Run extraction and return the WAV file as an in-memory bytes object."""
    sr, samples = extract_audio(source, **kwargs)
    buf = io.BytesIO()
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
    all_samples = []

    indices = list(range(num_frames))
    if args.reverse:
        indices = indices[::-1]

    for count, frame_idx in enumerate(indices):
        img = source.load_frame(frame_idx - args.audio_offset)
        if img is None:
            print(f"  Warning: Could not read frame {frame_idx - args.audio_offset}, skipping.", file=sys.stderr)
            continue

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
        frame_samples = extract_scanline_audio(img_corrected)
        all_samples.append(frame_samples)

        # Progress
        if (count + 1) % 50 == 0 or (count + 1) == num_frames:
            print(f"  Processed {count + 1}/{num_frames} frames", file=sys.stderr)

    # Stitch frames with overlap detection and cross-fade
    if args.overlap > 0:
        print(f"Stitching frames with up to {args.overlap*100:.0f}% overlap search...")
        raw_signal = stitch_with_overlap(all_samples, args.overlap)
    else:
        raw_signal = np.concatenate(all_samples)
    native_rate = len(all_samples[0]) * args.fps  # use single-frame length for native rate
    print(f"Raw signal: {len(raw_signal)} samples at native rate ~{native_rate:.0f} Hz")

    # --- Resample to target sample rate ---
    target_num_samples = int(len(raw_signal) * args.sample_rate / native_rate)
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
