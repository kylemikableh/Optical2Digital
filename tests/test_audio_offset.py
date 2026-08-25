#!/usr/bin/env python3
"""Standalone checks for extract_audio()'s audio_offset handling.

Run directly with python3 (this project has no pytest setup):
    python3 tests/test_audio_offset.py

extract_audio() reads audio for picture frame `idx` from source frame
`idx - audio_offset` (the soundtrack is physically printed audio_offset
frames earlier on the scan). Two consequences of that shift, both covered
here:

  - Leading silence: for the first `audio_offset` frames of any range
    starting near 0, `idx - audio_offset` is negative and
    source.load_frame() returns None -- there is genuinely no scanned
    audio for those picture frames. (Previously this silently dropped the
    frame and shrank the whole track by audio_offset frames instead of
    padding with silence -- see git history for that bug.)
  - Trailing real audio: the source frames at the very end of the scan
    ([end_frame - audio_offset + 1, end_frame]) hold real, valid
    soundtrack data for *virtual* picture positions beyond end_frame
    ([end_frame + 1, end_frame + audio_offset]) that were simply never
    scanned as picture. That audio is real and should be kept (appended
    past the end of the picture, "audio but no video"), not discarded.

Net effect: the audio track is audio_offset frames *longer* than the
picture range -- silence at the front, real content extending past the
picture's own end at the back.
"""
import os
import sys
import tempfile

import numpy as np

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, "tests"))
import test_dpx_reader as dpx_test_helpers
import KylesOpticalDecoder as kod


def _make_sequence(tmpdir, num_frames, width=8, height=20):
    """Write `num_frames` synthetic 8-bit RGB DPX frames, each a distinct
    solid brightness, so frames are individually distinguishable."""
    for i in range(num_frames):
        val = 40 + (i * 7) % 200  # keep values away from 0 so "real" chunks are never silent
        grid = [[(val, val, val)] * width for _ in range(height)]
        pixels = dpx_test_helpers._pack_tight(grid, 8, ">")
        buf = dpx_test_helpers._build_dpx(width, height, 8, 50, 0, pixels)
        with open(os.path.join(tmpdir, f"frame{i:04d}.dpx"), "wb") as f:
            f.write(buf)


def test_output_length_extends_by_offset_for_tail_audio():
    """The exported audio must span the picture range PLUS audio_offset
    extra frames at the end (real soundtrack data that has no matching
    picture), not merely match the picture's own duration."""
    with tempfile.TemporaryDirectory() as tmp:
        num_frames = 30
        _make_sequence(tmp, num_frames)
        source = kod.open_source(tmp)

        fps = 24.0
        sample_rate = 4800
        audio_offset = 21
        start_frame, end_frame = 0, num_frames - 1

        sr, samples = kod.extract_audio(
            source, top=0, bottom=20, left=0, right=8,
            fps=fps, sample_rate=sample_rate, audio_offset=audio_offset,
            start_frame=start_frame, end_frame=end_frame,
            overlap=0, integrate=True,
        )

        requested_frames = end_frame - start_frame + 1
        expected_len = int(round((requested_frames + audio_offset) / fps * sample_rate))
        assert len(samples) == expected_len, (
            f"expected {expected_len} samples ({requested_frames} picture "
            f"frames + {audio_offset} offset frames @ {fps}fps), got "
            f"{len(samples)}"
        )


def test_offset_produces_leading_silence_not_shifted_content():
    """With a 21-frame offset and no valid frames before frame 0, the first
    ~21 frames' worth of output audio must be silence, not real content
    slid forward to fill the gap."""
    with tempfile.TemporaryDirectory() as tmp:
        num_frames = 30
        _make_sequence(tmp, num_frames)
        source = kod.open_source(tmp)

        fps = 24.0
        sample_rate = 4800
        audio_offset = 21

        sr, samples = kod.extract_audio(
            source, top=0, bottom=20, left=0, right=8,
            fps=fps, sample_rate=sample_rate, audio_offset=audio_offset,
            start_frame=0, end_frame=num_frames - 1,
            overlap=0, integrate=True, hpf=0.0, lpf=sample_rate / 2 - 1,
        )

        samples_per_frame = sample_rate / fps
        # Check well inside the offset region (avoid the exact boundary
        # sample, which may carry a little energy from filter/resample
        # edge effects) and well inside the real-content region.
        silent_probe = int(5 * samples_per_frame)
        real_probe = int(25 * samples_per_frame)

        assert samples[silent_probe] == 0, (
            f"sample at frame ~5 (within the {audio_offset}-frame offset "
            f"region) should be silence, got {samples[silent_probe]}"
        )
        assert samples[real_probe] != 0, (
            f"sample at frame ~25 (past the offset region) should have "
            f"real content, got {samples[real_probe]}"
        )


def test_trailing_real_audio_beyond_picture_range_is_preserved():
    """Source frames at the very end of the scan hold real soundtrack data
    for virtual picture positions past end_frame -- that tail must be kept
    (non-silent), not dropped."""
    with tempfile.TemporaryDirectory() as tmp:
        num_frames = 30
        _make_sequence(tmp, num_frames)
        source = kod.open_source(tmp)

        fps = 24.0
        sample_rate = 4800
        audio_offset = 21
        end_frame = num_frames - 1

        sr, samples = kod.extract_audio(
            source, top=0, bottom=20, left=0, right=8,
            fps=fps, sample_rate=sample_rate, audio_offset=audio_offset,
            start_frame=0, end_frame=end_frame,
            overlap=0, integrate=True, hpf=0.0, lpf=sample_rate / 2 - 1,
        )

        samples_per_frame = sample_rate / fps
        requested_frames = end_frame + 1
        expected_len = int(round((requested_frames + audio_offset) / fps * sample_rate))
        assert len(samples) == expected_len

        # A probe placed a couple of frames into the tail (past where the
        # picture itself ends) should carry real content from the last
        # scanned source frames, not silence.
        tail_probe = int((requested_frames + 5) * samples_per_frame)
        assert tail_probe < len(samples)
        assert samples[tail_probe] != 0, (
            f"sample at frame ~{requested_frames + 5} (past the picture's "
            f"own end, within the trailing {audio_offset}-frame real-audio "
            f"region) should have real content, got {samples[tail_probe]}"
        )


if __name__ == "__main__":
    test_output_length_extends_by_offset_for_tail_audio()
    test_offset_produces_leading_silence_not_shifted_content()
    test_trailing_real_audio_beyond_picture_range_is_preserved()
    print("OK: all audio_offset checks passed")
