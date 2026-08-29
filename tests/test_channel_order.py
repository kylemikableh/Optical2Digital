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

"""Standalone checks for extract_audio()'s channel_order handling.

Run directly with python3 (this project has no pytest setup):
    python3 tests/test_channel_order.py

extract_stereo_scanline_audio() splits each corrected frame down the middle:
the inner half (left of image) -> LEFT channel, outer half -> RIGHT channel.
channel_order="RL" swaps that mapping for scans whose soundtrack runs
right-to-left, so column 0 of the output is what "LR" would have put in
column 1 and vice versa. Default ("LR") must be byte-for-byte unchanged
from the pre-feature behaviour.
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

WIDTH = 8
HEIGHT = 20


def _make_lr_asymmetric_sequence(tmpdir, num_frames):
    """Write synthetic frames whose left and right halves differ, so the
    two stereo channels carry distinguishable content."""
    for i in range(num_frames):
        left_val = 40 + (i * 5) % 150
        right_val = 220 - (i * 3) % 150
        row = [(left_val, left_val, left_val)] * (WIDTH // 2) \
            + [(right_val, right_val, right_val)] * (WIDTH // 2)
        grid = [list(row) for _ in range(HEIGHT)]
        pixels = dpx_test_helpers._pack_tight(grid, 8, ">")
        buf = dpx_test_helpers._build_dpx(WIDTH, HEIGHT, 8, 50, 0, pixels)
        with open(os.path.join(tmpdir, f"frame{i:04d}.dpx"), "wb") as f:
            f.write(buf)


def _extract(source, channel_order):
    return kod.extract_audio(
        source, top=0, bottom=HEIGHT, left=0, right=WIDTH,
        fps=24.0, sample_rate=4800, audio_offset=0,
        start_frame=0, end_frame=None,
        overlap=0, integrate=True, stereo=True,
        channel_order=channel_order,
    )


def test_default_is_lr_and_channels_differ():
    with tempfile.TemporaryDirectory() as tmp:
        _make_lr_asymmetric_sequence(tmp, 12)
        source = kod.open_source(tmp)

        _, lr = _extract(source, "LR")
        assert lr.ndim == 2 and lr.shape[1] == 2, "expected a 2-channel array"
        assert not np.array_equal(lr[:, 0], lr[:, 1]), \
            "test frames should make the two channels differ"

        # "LR" is also the default when the arg is omitted entirely.
        _, default = kod.extract_audio(
            source, top=0, bottom=HEIGHT, left=0, right=WIDTH,
            fps=24.0, sample_rate=4800, audio_offset=0,
            overlap=0, integrate=True, stereo=True,
        )
        assert np.array_equal(lr, default), \
            "omitting channel_order must match channel_order='LR'"


def test_rl_swaps_the_two_channels():
    with tempfile.TemporaryDirectory() as tmp:
        _make_lr_asymmetric_sequence(tmp, 12)
        source = kod.open_source(tmp)

        _, lr = _extract(source, "LR")
        _, rl = _extract(source, "RL")

        assert np.array_equal(rl[:, 0], lr[:, 1]), \
            "channel_order='RL' column 0 should equal 'LR' column 1"
        assert np.array_equal(rl[:, 1], lr[:, 0]), \
            "channel_order='RL' column 1 should equal 'LR' column 0"


def test_channel_order_ignored_for_mono():
    with tempfile.TemporaryDirectory() as tmp:
        _make_lr_asymmetric_sequence(tmp, 12)
        source = kod.open_source(tmp)

        _, mono_lr = kod.extract_audio(
            source, top=0, bottom=HEIGHT, left=0, right=WIDTH,
            fps=24.0, sample_rate=4800, audio_offset=0,
            overlap=0, integrate=True, stereo=False, channel_order="LR",
        )
        _, mono_rl = kod.extract_audio(
            source, top=0, bottom=HEIGHT, left=0, right=WIDTH,
            fps=24.0, sample_rate=4800, audio_offset=0,
            overlap=0, integrate=True, stereo=False, channel_order="RL",
        )
        assert mono_lr.ndim == 1
        assert np.array_equal(mono_lr, mono_rl), \
            "channel_order must not affect mono output"


if __name__ == "__main__":
    test_default_is_lr_and_channels_differ()
    test_rl_swaps_the_two_channels()
    test_channel_order_ignored_for_mono()
    print("OK: all channel_order checks passed")
