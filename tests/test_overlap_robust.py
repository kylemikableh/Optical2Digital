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

"""Checks for compute_robust_overlap_offset() and _resolve_overlap_offsets().

Run directly with python3 (this project has no pytest setup):
    python3 tests/test_overlap_robust.py

Background: the previous default behavior ran find_best_overlap()
independently for every consecutive frame pair. That search is purely
content-driven with no continuity constraint between pairs, so on
quiet/flat passages every candidate offset ties at ~0 error and
np.argmin always resolves ties to the smallest offset -- silently
collapsing to offset=1 regardless of the true physical overlap -- while
louder passages could land anywhere up to max_overlap depending on exact
waveform shape. Since consecutive frames' true overlap is fixed by
scanner geometry (frame pitch), not by content, this per-pair noise
showed up as non-monotonic, content-dependent sync jitter after the final
global resample (which assumes a constant samples-per-frame density).

compute_robust_overlap_offset() fixes this by computing one reel-wide
offset (confidence-gated median across all pairs) instead of trusting
each pair independently. These tests build synthetic frames cut from one
continuous master signal with a *known* constant true overlap, and verify
that offset is recovered even when some frames are near-silent.
"""
import os
import sys

import numpy as np

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
import KylesOpticalDecoder as kod


def _make_overlapping_frames(rng, num_frames, frame_len, true_overlap, quiet_positions=()):
    """Cut `frame_len`-sample chunks out of one continuous master signal so
    each consecutive pair shares exactly `true_overlap` samples -- the same
    relationship real scanner frames have (fixed physical overlap, since
    each frame captures more of the soundtrack than the film advances).

    Frames at `quiet_positions` are replaced with a near-silent noise floor
    instead of real master-signal content, simulating quiet/flat passages
    where no reliable alignment exists.
    """
    step = frame_len - true_overlap
    total_len = frame_len + step * (num_frames - 1)
    master = rng.normal(size=total_len)
    frames = []
    for i in range(num_frames):
        start = i * step
        frame = master[start:start + frame_len].copy()
        if i in quiet_positions:
            frame[:] = 1e-4 * rng.normal(size=frame_len)
        frames.append(frame)
    return frames


def test_recovers_true_offset_with_all_loud_frames():
    rng = np.random.default_rng(1)
    frames = _make_overlapping_frames(rng, num_frames=20, frame_len=40, true_overlap=10)
    offset = kod.compute_robust_overlap_offset(frames, max_overlap_frac=0.5)
    assert offset == 10, f"expected true overlap 10, got {offset}"


def test_recovers_true_offset_despite_quiet_frame():
    """One frame out of twelve is near-silent (e.g. a quiet passage on the
    print). The two pairs touching it are unreliable, but the remaining
    nine loud-loud pairs should still carry the median to the true offset,
    not collapse toward the quiet pairs' degenerate small-offset result."""
    rng = np.random.default_rng(2)
    frames = _make_overlapping_frames(
        rng, num_frames=12, frame_len=40, true_overlap=8, quiet_positions={6}
    )
    offset = kod.compute_robust_overlap_offset(frames, max_overlap_frac=0.5)
    assert offset == 8, f"expected true overlap 8 despite one quiet frame, got {offset}"


def test_returns_zero_when_reel_is_entirely_silent():
    frames = [np.zeros(40) for _ in range(10)]
    offset = kod.compute_robust_overlap_offset(frames, max_overlap_frac=0.5)
    assert offset == 0, f"expected 0 for an entirely silent reel, got {offset}"


def test_returns_zero_with_fewer_than_two_frames():
    assert kod.compute_robust_overlap_offset([np.zeros(40)], 0.5) == 0
    assert kod.compute_robust_overlap_offset([], 0.5) == 0


def test_returns_zero_when_overlap_disabled():
    rng = np.random.default_rng(3)
    frames = _make_overlapping_frames(rng, num_frames=10, frame_len=40, true_overlap=8)
    assert kod.compute_robust_overlap_offset(frames, max_overlap_frac=0) == 0


def test_resolve_overlap_offsets_applies_one_uniform_offset():
    """The whole point of the fix: unlike the old per-pair search (which
    could pick a different offset for every join), every pair must end up
    with the *same* offset -- eliminating the variable per-frame trimming
    that caused the global resample step to drift out of local sync."""
    rng = np.random.default_rng(4)
    frames = _make_overlapping_frames(rng, num_frames=15, frame_len=40, true_overlap=10)

    offsets = kod._resolve_overlap_offsets(frames, None, False, 0.5, "auto", 0)
    assert offsets is not None
    assert len(offsets) == len(frames) - 1
    assert all(o == 10 for o in offsets), (
        f"expected a single uniform offset (10) for every pair, got {offsets}"
    )

    raw = kod.apply_overlap_offsets(frames, offsets)
    expected_len = 40 + (40 - 10) * (len(frames) - 1)
    assert len(raw) == expected_len, (
        f"expected stitched length {expected_len} (constant samples-per-frame "
        f"after trimming a constant overlap), got {len(raw)}"
    )


def test_resolve_overlap_offsets_locked_mode_uses_manual_value():
    rng = np.random.default_rng(5)
    frames = _make_overlapping_frames(rng, num_frames=8, frame_len=40, true_overlap=10)

    offsets = kod._resolve_overlap_offsets(frames, None, False, 0.5, "locked", 5)
    assert offsets == [5] * (len(frames) - 1)


def test_resolve_overlap_offsets_locked_mode_falls_back_to_auto():
    """locked_offset<=0 in "locked" mode must fall back to the automatic
    computation, not to the old (now-removed) per-pair search."""
    rng = np.random.default_rng(6)
    frames = _make_overlapping_frames(rng, num_frames=15, frame_len=40, true_overlap=10)

    locked_offsets = kod._resolve_overlap_offsets(frames, None, False, 0.5, "locked", 0)
    auto_offsets = kod._resolve_overlap_offsets(frames, None, False, 0.5, "auto", 0)
    assert locked_offsets == auto_offsets


def test_resolve_overlap_offsets_none_when_disabled_or_too_few_frames():
    rng = np.random.default_rng(7)
    frames = _make_overlapping_frames(rng, num_frames=5, frame_len=40, true_overlap=10)
    assert kod._resolve_overlap_offsets(frames, None, False, 0, "auto", 0) is None
    assert kod._resolve_overlap_offsets(frames[:1], None, False, 0.5, "auto", 0) is None


if __name__ == "__main__":
    test_recovers_true_offset_with_all_loud_frames()
    print("OK: recovers_true_offset_with_all_loud_frames")
    test_recovers_true_offset_despite_quiet_frame()
    print("OK: recovers_true_offset_despite_quiet_frame")
    test_returns_zero_when_reel_is_entirely_silent()
    print("OK: returns_zero_when_reel_is_entirely_silent")
    test_returns_zero_with_fewer_than_two_frames()
    print("OK: returns_zero_with_fewer_than_two_frames")
    test_returns_zero_when_overlap_disabled()
    print("OK: returns_zero_when_overlap_disabled")
    test_resolve_overlap_offsets_applies_one_uniform_offset()
    print("OK: resolve_overlap_offsets_applies_one_uniform_offset")
    test_resolve_overlap_offsets_locked_mode_uses_manual_value()
    print("OK: resolve_overlap_offsets_locked_mode_uses_manual_value")
    test_resolve_overlap_offsets_locked_mode_falls_back_to_auto()
    print("OK: resolve_overlap_offsets_locked_mode_falls_back_to_auto")
    test_resolve_overlap_offsets_none_when_disabled_or_too_few_frames()
    print("OK: resolve_overlap_offsets_none_when_disabled_or_too_few_frames")
    print("All overlap-robust tests passed.")
