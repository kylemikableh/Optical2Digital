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

"""Checks for the stitching-progress plumbing (stitch_with_overlap(),
apply_overlap_offsets(), and extract_audio()'s reset_progress phases).

Run directly with python3 (this project has no pytest setup):
    python3 tests/test_stitch_progress.py
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
    for i in range(num_frames):
        val = 40 + (i * 7) % 200
        grid = [[(val, val, val)] * width for _ in range(height)]
        pixels = dpx_test_helpers._pack_tight(grid, 8, ">")
        buf = dpx_test_helpers._build_dpx(width, height, 8, 50, 0, pixels)
        with open(os.path.join(tmpdir, f"frame{i:04d}.dpx"), "wb") as f:
            f.write(buf)


def test_stitch_with_overlap_progress_matches_no_callback_output():
    rng = np.random.default_rng(11)
    frames = [rng.random(40) for _ in range(15)]

    reported = []
    result_with_cb = kod.stitch_with_overlap(
        frames, 0.25, progress_callback=lambda c, t: reported.append((c, t)), progress_every=3
    )
    result_without_cb = kod.stitch_with_overlap(frames, 0.25)

    assert np.array_equal(result_with_cb, result_without_cb), (
        "progress_callback must not change stitching output"
    )
    assert reported, "expected at least one progress report"
    total_pairs = len(frames) - 1
    assert reported[-1] == (total_pairs, total_pairs), (
        f"expected final report to be ({total_pairs}, {total_pairs}), got {reported[-1]}"
    )
    currents = [c for c, t in reported]
    assert currents == sorted(currents), "progress must be monotonically non-decreasing"
    assert all(t == total_pairs for c, t in reported), "total must stay constant across reports"


def test_apply_overlap_offsets_progress_matches_no_callback_output():
    rng = np.random.default_rng(12)
    frames = [rng.random(30) for _ in range(10)]
    offsets = [rng.integers(0, 5) for _ in range(9)]

    reported = []
    result_with_cb = kod.apply_overlap_offsets(
        frames, offsets, progress_callback=lambda c, t: reported.append((c, t)), progress_every=2
    )
    result_without_cb = kod.apply_overlap_offsets(frames, offsets)

    assert np.array_equal(result_with_cb, result_without_cb)
    total_pairs = len(frames) - 1
    assert reported[-1] == (total_pairs, total_pairs)


def test_stitch_progress_reports_every_pair_when_progress_every_is_1():
    rng = np.random.default_rng(13)
    frames = [rng.random(20) for _ in range(6)]
    reported = []
    kod.stitch_with_overlap(
        frames, 0.25, progress_callback=lambda c, t: reported.append((c, t)), progress_every=1
    )
    assert reported == [(i, 5) for i in range(1, 6)], reported


def test_single_frame_no_progress_calls():
    """A single frame has no pairs to stitch -- progress_callback must not
    be called (nothing to report, and total_pairs would be 0)."""
    reported = []
    kod.stitch_with_overlap(
        [np.zeros(10)], 0.25, progress_callback=lambda c, t: reported.append((c, t))
    )
    assert reported == []


def test_extract_audio_reports_stitching_and_resets_for_quick_phases():
    """End-to-end: extract_audio() with overlap>0 should report stitching
    progress via progress_callback (current/total pairs, not frame counts),
    and reset to (0, 0) before the offset-computation/resampling/filtering
    phases (verified indirectly via the reset_progress mechanism itself in
    the unit tests above; here we just confirm extract_audio() actually
    reaches a stitching-phase progress report distinct from the frame-loop
    phase, i.e. total resets downward from the frame count to the smaller
    pair count)."""
    with tempfile.TemporaryDirectory() as tmp:
        num_frames = 12
        _make_sequence(tmp, num_frames)
        source = kod.open_source(tmp)

        phases = []
        progress_reports = []

        def phase_cb(msg):
            phases.append(msg)

        def progress_cb(current, total):
            progress_reports.append((current, total))

        kod.extract_audio(
            source, top=0, bottom=20, left=0, right=8,
            fps=24.0, sample_rate=4800, audio_offset=0,
            start_frame=0, end_frame=num_frames - 1,
            overlap=0.25, integrate=True,
            phase_callback=phase_cb, progress_callback=progress_cb, progress_every=1,
        )

        assert any(p.startswith("Stitching") for p in phases), phases
        # The frame-processing phase reports totals of `num_frames`; the
        # stitching phase's pair-count total (num_frames - 1) must show up
        # distinctly among the reports, proving stitching progress actually
        # flows through progress_callback (not just the frame loop's).
        totals_seen = {t for c, t in progress_reports}
        assert (num_frames - 1) in totals_seen, (
            f"expected a stitching-phase total of {num_frames - 1} among {sorted(totals_seen)}"
        )
        # reset_progress phases (offset computation is stereo-only here, so
        # just resampling/filtering apply) should contribute at least one
        # (0, 0) report between stitching and the run's end.
        assert (0, 0) in progress_reports, "expected a (0, 0) reset before a quick phase"


if __name__ == "__main__":
    test_stitch_with_overlap_progress_matches_no_callback_output()
    print("OK: stitch_with_overlap_progress_matches_no_callback_output")
    test_apply_overlap_offsets_progress_matches_no_callback_output()
    print("OK: apply_overlap_offsets_progress_matches_no_callback_output")
    test_stitch_progress_reports_every_pair_when_progress_every_is_1()
    print("OK: stitch_progress_reports_every_pair_when_progress_every_is_1")
    test_single_frame_no_progress_calls()
    print("OK: single_frame_no_progress_calls")
    test_extract_audio_reports_stitching_and_resets_for_quick_phases()
    print("OK: extract_audio_reports_stitching_and_resets_for_quick_phases")
    print("All stitch-progress tests passed.")
