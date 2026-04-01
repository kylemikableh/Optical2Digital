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
  3. Apply image corrections (negative inversion, lift, gamma, gain, S-curve)
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
        "--lift", type=float, default=0.0,
        help="Black point shift (added to pixel values after optional inversion)",
    )
    parser.add_argument(
        "--gamma", type=float, default=1.0,
        help="Gamma correction exponent (applied after lift)",
    )
    parser.add_argument(
        "--gain", type=float, default=1.0,
        help="Brightness multiplier (applied after gamma)",
    )
    parser.add_argument(
        "--threshold", type=float, default=0.0,
        help="S-curve steepness for variable-area edge sharpening (0 = disabled)",
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
        "--rotate", type=int, default=0, choices=[0, 90, 180, 270],
        help="Rotate cropped image by this many degrees clockwise before extraction",
    )
    parser.add_argument(
        "--dump-crops", type=str, default=None,
        metavar="DIR",
        help="Save cropped soundtrack images to this directory for debugging",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Image correction
# ---------------------------------------------------------------------------

def correct_image(img_float, negative, lift, gamma, gain, threshold):
    """Apply image corrections to a floating-point image [0,1]."""
    img = img_float.copy()

    # 1. Negative inversion
    if negative:
        img = 1.0 - img

    # 2. Lift (black point shift)
    if lift != 0.0:
        img += lift

    # 3. Clamp
    np.clip(img, 0.0, 1.0, out=img)

    # 4. Gamma
    if gamma != 1.0:
        img = np.power(img, gamma)

    # 5. Gain
    if gain != 1.0:
        img *= gain

    # 6. Clamp
    np.clip(img, 0.0, 1.0, out=img)

    # 7. S-curve threshold for VA edge sharpening
    #    Formula borrowed from AEO-Light: x^s / (0.5^s + x^s)
    if threshold > 0.0:
        s = threshold
        half_s = np.power(0.5, s)
        img = np.power(img, s) / (half_s + np.power(img, s))

    return img


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


# ---------------------------------------------------------------------------
# Frame source abstraction
# ---------------------------------------------------------------------------

class ImageSequenceSource:
    """Frame source backed by a directory of image files."""

    def __init__(self, input_dir):
        self._input_dir = input_dir
        self._filenames = list_frames(input_dir)
        if not self._filenames:
            raise ValueError(f"No image files found in '{input_dir}'")
        first = cv2.imread(os.path.join(input_dir, self._filenames[0]), cv2.IMREAD_GRAYSCALE)
        if first is None:
            raise RuntimeError(f"Could not read first frame: {self._filenames[0]}")
        self._frame_height, self._frame_width = first.shape

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

    def load_frame(self, index):
        """Load frame by index as grayscale uint8 (or None)."""
        if index < 0 or index >= len(self._filenames):
            return None
        return cv2.imread(
            os.path.join(self._input_dir, self._filenames[index]),
            cv2.IMREAD_GRAYSCALE,
        )


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

    def load_frame(self, index):
        """Seek to *index* and return the frame as grayscale uint8 (or None)."""
        if index < 0 or index >= self._num_frames:
            return None
        with self._lock:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = self._cap.read()
        if not ok or frame is None:
            return None
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

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
    """Load a single frame as a grayscale uint8 numpy array (or None)."""
    return cv2.imread(os.path.join(input_dir, filename), cv2.IMREAD_GRAYSCALE)


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
                     negative=False, lift=0.0, gamma=1.0, gain=1.0,
                     threshold=0.0):
    """Crop, rotate, normalise and colour-correct a grayscale frame.

    Returns the corrected image as a float64 array in [0, 1].
    """
    cropped = img[top:bottom, left:right]
    cropped = rotate_image(cropped, rotate)
    img_float = cropped.astype(np.float64) / 255.0
    return correct_image(img_float, negative, lift, gamma, gain, threshold)


def correct_full_frame(img, negative=False, lift=0.0, gamma=1.0, gain=1.0, threshold=0.0):
    """Apply corrections to the full frame (no crop/rotation). Returns float64 [0,1]."""
    img_float = img.astype(np.float64) / 255.0
    return correct_image(img_float, negative, lift, gamma, gain, threshold)


def corrected_to_jpeg(img_corrected):
    """Encode a [0,1] float image as JPEG bytes for the web preview."""
    uint8 = (img_corrected * 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", uint8, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()


def frame_to_jpeg(img):
    """Encode a raw grayscale uint8 image as JPEG bytes."""
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()


def extract_audio(source, top, bottom, left, right,
                  rotate=0, negative=False, lift=0.0, gamma=1.0,
                  gain=1.0, threshold=0.0, fps=24.0, sample_rate=48000,
                  hpf=40.0, lpf=13500.0, overlap=0.25,
                  stereo=False, progress_callback=None, reverse=False,
                  phase_callback=None, start_frame=0, end_frame=None):
    """Run the full extraction pipeline. Returns (sample_rate, int16_array).

    *source* is a FrameSource object (ImageSequenceSource or VideoSource).
    When *stereo* is True, returns a 2-channel int16 array (N, 2).
    *progress_callback*, if provided, is called with (current, total) after
    each frame is processed.
    *phase_callback*, if provided, is called with a string describing the
    current processing phase.
    *start_frame* and *end_frame* allow processing a sub-range of frames
    (end_frame is inclusive; defaults to the last frame).
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
        img = source.load_frame(idx)
        if img is None:
            continue
        corrected = crop_and_correct(
            img, top, bottom, left, right, rotate,
            negative, lift, gamma, gain, threshold,
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
        native_rate = len(all_samples[0]) * fps
        target_n = int(len(raw_signal) * sample_rate / native_rate)
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
        img = source.load_frame(frame_idx)
        if img is None:
            print(f"  Warning: Could not read frame {frame_idx}, skipping.", file=sys.stderr)
            continue

        # Crop to soundtrack region
        img_cropped = img[top:bottom, left:right]

        # Rotate if requested (clockwise)
        if args.rotate == 90:
            img_cropped = cv2.rotate(img_cropped, cv2.ROTATE_90_CLOCKWISE)
        elif args.rotate == 180:
            img_cropped = cv2.rotate(img_cropped, cv2.ROTATE_180)
        elif args.rotate == 270:
            img_cropped = cv2.rotate(img_cropped, cv2.ROTATE_90_COUNTERCLOCKWISE)

        # Normalize to [0.0, 1.0]
        img_float = img_cropped.astype(np.float64) / 255.0

        # Apply image corrections
        img_corrected = correct_image(
            img_float,
            negative=args.negative,
            lift=args.lift,
            gamma=args.gamma,
            gain=args.gain,
            threshold=args.threshold,
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
