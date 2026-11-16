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

"""Standalone checks that the CLI (main()) matches the GUI's extraction.

Run directly with python3 (this project has no pytest setup):
    python3 tests/test_cli.py

server.py's /api/extract produces its WAV via extract_audio_to_wav_bytes();
main() must write a byte-identical file for the same settings, including the
CLI-only-until-now options: --stereo, --channel-order, --bit-depth,
--start-frame/--end-frame, the --fps default (the source's own frame rate),
and --dump-crops (which goes through extract_audio()'s dump_crops_dir).
"""
import contextlib
import io
import os
import sys
import tempfile
import wave

import cv2
import numpy as np
from scipy.io import wavfile

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, "tests"))
from test_channel_order import WIDTH, HEIGHT, _make_lr_asymmetric_sequence
import KylesOpticalDecoder as kod

NUM_FRAMES = 12
SAMPLE_RATE = 4800


def _run_cli(argv):
    """Run main() in-process with *argv*, silencing its console output."""
    old_argv = sys.argv
    sys.argv = ["KylesOpticalDecoder.py"] + argv
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            kod.main()
    finally:
        sys.argv = old_argv


def _cli_wav(input_path, out_path, *extra):
    _run_cli([
        "-i", input_path, "-o", out_path,
        "--crop", "0", str(HEIGHT), "0", str(WIDTH),
        "--sample-rate", str(SAMPLE_RATE), "--overlap", "0",
        *extra,
    ])
    with open(out_path, "rb") as f:
        return f.read()


def _gui_wav(source, **kwargs):
    # Mirrors the call server.py's /api/extract makes, with the CLI's defaults.
    params = dict(
        top=0, bottom=HEIGHT, left=0, right=WIDTH,
        sample_rate=SAMPLE_RATE, overlap=0, integrate=True, fps=24.0,
    )
    params.update(kwargs)
    return kod.extract_audio_to_wav_bytes(source, **params)


def _make_video(path, num_frames, fps):
    """Write a lossless (FFV1) video whose frames have distinct L/R halves."""
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"FFV1"), fps, (WIDTH, HEIGHT))
    for i in range(num_frames):
        img = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
        img[:, :WIDTH // 2] = 40 + (i * 5) % 150
        img[:, WIDTH // 2:] = 220 - (i * 3) % 150
        writer.write(img)
    writer.release()


def test_new_flag_defaults():
    old_argv = sys.argv
    sys.argv = ["KylesOpticalDecoder.py", "-i", "x", "--crop", "0", "1", "0", "1"]
    try:
        args = kod.parse_args()
    finally:
        sys.argv = old_argv
    assert args.stereo is False
    assert args.channel_order == "LR"
    assert args.bit_depth == "int16"
    assert args.start_frame == 0
    assert args.end_frame is None
    assert args.fps is None, "fps must default to None so the source's own rate is used"


def test_mono_matches_gui():
    with tempfile.TemporaryDirectory() as tmp:
        frames = os.path.join(tmp, "frames")
        os.makedirs(frames)
        _make_lr_asymmetric_sequence(frames, NUM_FRAMES)
        source = kod.open_source(frames)

        cli = _cli_wav(frames, os.path.join(tmp, "out.wav"))
        assert cli == _gui_wav(source), "CLI mono WAV must be byte-identical to the GUI's"

        _, data = wavfile.read(os.path.join(tmp, "out.wav"))
        assert data.ndim == 1 and data.dtype == np.int16


def test_stereo_matches_gui_for_both_channel_orders():
    with tempfile.TemporaryDirectory() as tmp:
        frames = os.path.join(tmp, "frames")
        os.makedirs(frames)
        _make_lr_asymmetric_sequence(frames, NUM_FRAMES)
        source = kod.open_source(frames)

        outputs = {}
        for order in ("LR", "RL"):
            out = os.path.join(tmp, f"{order}.wav")
            cli = _cli_wav(frames, out, "--stereo", "--channel-order", order)
            assert cli == _gui_wav(source, stereo=True, channel_order=order), \
                f"CLI stereo {order} WAV must be byte-identical to the GUI's"
            _, outputs[order] = wavfile.read(out)

        lr, rl = outputs["LR"], outputs["RL"]
        assert lr.ndim == 2 and lr.shape[1] == 2, "--stereo must write 2 channels"
        assert not np.array_equal(lr[:, 0], lr[:, 1]), \
            "test frames should make the two channels differ"
        assert np.array_equal(rl[:, 0], lr[:, 1]) and np.array_equal(rl[:, 1], lr[:, 0]), \
            "--channel-order RL must swap the two channels"


def test_every_bit_depth_matches_gui():
    expected_width = {"int16": 2, "int24": 3, "int32": 4}
    with tempfile.TemporaryDirectory() as tmp:
        frames = os.path.join(tmp, "frames")
        os.makedirs(frames)
        _make_lr_asymmetric_sequence(frames, NUM_FRAMES)
        source = kod.open_source(frames)

        for bit_depth in kod._BIT_DEPTHS:
            out = os.path.join(tmp, f"{bit_depth}.wav")
            cli = _cli_wav(frames, out, "--stereo", "--bit-depth", bit_depth)
            assert cli == _gui_wav(source, stereo=True, bit_depth=bit_depth), \
                f"CLI {bit_depth} WAV must be byte-identical to the GUI's"
            if bit_depth in expected_width:
                with wave.open(out, "rb") as wf:
                    assert wf.getsampwidth() == expected_width[bit_depth]
                    assert wf.getnchannels() == 2
            else:
                _, data = wavfile.read(out)
                assert data.dtype == np.float32


def test_frame_range_matches_gui():
    start, end, audio_offset = 2, 7, 3
    with tempfile.TemporaryDirectory() as tmp:
        frames = os.path.join(tmp, "frames")
        os.makedirs(frames)
        _make_lr_asymmetric_sequence(frames, NUM_FRAMES)
        source = kod.open_source(frames)

        out = os.path.join(tmp, "out.wav")
        cli = _cli_wav(
            frames, out,
            "--start-frame", str(start), "--end-frame", str(end),
            "--audio-offset", str(audio_offset),
        )
        assert cli == _gui_wav(source, start_frame=start, end_frame=end, audio_offset=audio_offset), \
            "CLI frame-range WAV must be byte-identical to the GUI's"

        # Picture range plus the audio_offset tail -- see extract_audio().
        _, data = wavfile.read(out)
        expected_frames = end - start + 1 + audio_offset
        assert len(data) == round(expected_frames / 24.0 * SAMPLE_RATE)


def test_fps_defaults_to_video_rate_and_explicit_fps_wins():
    with tempfile.TemporaryDirectory() as tmp:
        video = os.path.join(tmp, "clip.avi")
        _make_video(video, NUM_FRAMES, 25.0)
        source = kod.open_source(video)
        assert abs(source.fps - 25.0) < 1e-3

        default = _cli_wav(video, os.path.join(tmp, "default.wav"), "--stereo", "--audio-offset", "0")
        assert default == _gui_wav(source, stereo=True, audio_offset=0, fps=source.fps), \
            "without --fps the CLI must use the video's own frame rate"

        # --fps 24 used to be indistinguishable from "not given" and was
        # silently replaced by the video's rate.
        forced = _cli_wav(video, os.path.join(tmp, "forced.wav"),
                          "--stereo", "--audio-offset", "0", "--fps", "24")
        assert forced == _gui_wav(source, stereo=True, audio_offset=0, fps=24.0), \
            "an explicit --fps 24 must be honoured for a non-24 fps video"
        assert forced != default


def test_fps_defaults_to_24_for_image_sequence():
    with tempfile.TemporaryDirectory() as tmp:
        frames = os.path.join(tmp, "frames")
        os.makedirs(frames)
        _make_lr_asymmetric_sequence(frames, NUM_FRAMES)

        cli = _cli_wav(frames, os.path.join(tmp, "out.wav"))
        assert cli == _gui_wav(kod.open_source(frames), fps=24.0)


def test_dump_crops_writes_one_image_per_picture_frame():
    audio_offset = 2
    with tempfile.TemporaryDirectory() as tmp:
        frames = os.path.join(tmp, "frames")
        os.makedirs(frames)
        _make_lr_asymmetric_sequence(frames, NUM_FRAMES)
        crops = os.path.join(tmp, "crops", "nested")  # CLI must create it

        _cli_wav(frames, os.path.join(tmp, "out.wav"),
                 "--audio-offset", str(audio_offset), "--dump-crops", crops)

        # Picture frames 0..NUM_FRAMES-1+offset are read at (idx - offset);
        # the first `offset` of those have no source frame, so no crop.
        expected = {f"frame_{i:06d}.png" for i in range(audio_offset, NUM_FRAMES + audio_offset)}
        assert set(os.listdir(crops)) == expected

        crop = cv2.imread(os.path.join(crops, f"frame_{audio_offset:06d}.png"), cv2.IMREAD_UNCHANGED)
        assert crop is not None and crop.shape[:2] == (HEIGHT, WIDTH)


def test_dump_crops_does_not_change_audio():
    with tempfile.TemporaryDirectory() as tmp:
        frames = os.path.join(tmp, "frames")
        os.makedirs(frames)
        _make_lr_asymmetric_sequence(frames, NUM_FRAMES)

        plain = _cli_wav(frames, os.path.join(tmp, "a.wav"), "--stereo")
        dumped = _cli_wav(frames, os.path.join(tmp, "b.wav"), "--stereo",
                          "--dump-crops", os.path.join(tmp, "crops"))
        assert plain == dumped


def test_missing_input_exits_with_error():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            _cli_wav(os.path.join(tmp, "does-not-exist"), os.path.join(tmp, "out.wav"))
        except SystemExit as e:
            assert e.code == 1
        else:
            raise AssertionError("expected SystemExit(1) for a missing input")
        assert not os.path.exists(os.path.join(tmp, "out.wav"))


if __name__ == "__main__":
    test_new_flag_defaults()
    test_mono_matches_gui()
    test_stereo_matches_gui_for_both_channel_orders()
    test_every_bit_depth_matches_gui()
    test_frame_range_matches_gui()
    test_fps_defaults_to_video_rate_and_explicit_fps_wins()
    test_fps_defaults_to_24_for_image_sequence()
    test_dump_crops_writes_one_image_per_picture_frame()
    test_dump_crops_does_not_change_audio()
    test_missing_input_exits_with_error()
    print("OK: all CLI checks passed")
