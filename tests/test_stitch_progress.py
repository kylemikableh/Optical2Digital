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

"""Checks for the stitching-progress plumbing (ProgressThrottle,
apply_overlap_offsets() -- the sole stitching path -- and extract_audio()'s
reset_progress phases).

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


class _FakeClock:
    """Stand-in for the stdlib `time` module's monotonic() -- lets tests
    control elapsed wall-clock time deterministically instead of racing
    real time.sleep() calls. Swapped into kod.time (the module-level name
    ProgressThrottle looks up), never the real stdlib `time` module, so it
    can't leak into unrelated code."""

    def __init__(self, t=0.0):
        self.t = t

    def monotonic(self):
        return self.t


def test_progress_throttle_gates_by_wall_time_not_step_count():
    """The actual fix: cadence is gated on elapsed wall-clock time, not a
    fixed step count -- so a burst of steps that take no measurable time
    collapses into one report, and advancing time unlocks the next one,
    regardless of how many steps occurred. This is what makes the reported
    cadence self-adjust to whatever speed the underlying work runs at."""
    fake = _FakeClock(0.0)
    real_time = kod.time
    kod.time = fake
    try:
        reported = []
        throttle = kod.ProgressThrottle(lambda c, t: reported.append((c, t)), min_interval=0.1)

        # First call always fires immediately...
        throttle(1, 10)
        # ...but a burst of further steps with no time elapsed does not,
        # however many of them there are.
        for step in range(2, 6):
            throttle(step, 10)
        assert reported == [(1, 10)], reported

        # Advancing time past min_interval unlocks the next report.
        fake.t = 0.15
        throttle(6, 10)
        assert reported == [(1, 10), (6, 10)], reported

        # The final call (current >= total) always fires, even with no
        # time elapsed -- completion must never be swallowed by the gate.
        throttle(10, 10)
        assert reported[-1] == (10, 10), reported
    finally:
        kod.time = real_time


def test_progress_throttle_reset_forces_immediate_report():
    """reset() is what lets extract_audio() give each new phase (frame
    processing, stitching, ...) its own immediate first report instead of
    inheriting the timing gate from whatever the previous phase last did."""
    fake = _FakeClock(0.0)
    real_time = kod.time
    kod.time = fake
    try:
        reported = []
        throttle = kod.ProgressThrottle(lambda c, t: reported.append((c, t)), min_interval=0.1)
        throttle(1, 10)
        throttle(2, 10)  # suppressed -- no time elapsed
        assert reported == [(1, 10)], reported

        throttle.reset()
        throttle(2, 10)  # fires immediately despite no time elapsed
        assert reported[-1] == (2, 10), reported
    finally:
        kod.time = real_time


def test_apply_overlap_offsets_progress_matches_no_callback_output():
    rng = np.random.default_rng(12)
    frames = [rng.random(30) for _ in range(10)]
    offsets = [rng.integers(0, 5) for _ in range(9)]

    reported = []
    result_with_cb = kod.apply_overlap_offsets(
        frames, offsets, progress_callback=lambda c, t: reported.append((c, t))
    )
    result_without_cb = kod.apply_overlap_offsets(frames, offsets)

    assert np.array_equal(result_with_cb, result_without_cb)
    total_pairs = len(frames) - 1
    assert reported[-1] == (total_pairs, total_pairs)


def test_stitch_progress_reports_every_pair_with_zero_min_interval():
    """min_interval=0 degrades to "report every step" -- monotonic time
    never goes backward, so every call is immediately due."""
    rng = np.random.default_rng(13)
    frames = [rng.random(20) for _ in range(6)]
    offsets = [2] * (len(frames) - 1)
    reported = []
    kod.apply_overlap_offsets(
        frames, offsets, progress_callback=lambda c, t: reported.append((c, t)), min_interval=0
    )
    assert reported == [(i, 5) for i in range(1, 6)], reported


def test_single_frame_no_progress_calls():
    """A single frame has no pairs to stitch -- progress_callback must not
    be called (nothing to report, and total_pairs would be 0)."""
    reported = []
    kod.apply_overlap_offsets(
        [np.zeros(10)], [], progress_callback=lambda c, t: reported.append((c, t))
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
            phase_callback=phase_cb, progress_callback=progress_cb, progress_min_interval=0,
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
        # reset_progress phases (offset computation, resampling, filtering)
        # should contribute at least one (0, 0) report between stitching
        # and the run's end.
        assert (0, 0) in progress_reports, "expected a (0, 0) reset before a quick phase"


if __name__ == "__main__":
    test_progress_throttle_gates_by_wall_time_not_step_count()
    print("OK: progress_throttle_gates_by_wall_time_not_step_count")
    test_progress_throttle_reset_forces_immediate_report()
    print("OK: progress_throttle_reset_forces_immediate_report")
    test_apply_overlap_offsets_progress_matches_no_callback_output()
    print("OK: apply_overlap_offsets_progress_matches_no_callback_output")
    test_stitch_progress_reports_every_pair_with_zero_min_interval()
    print("OK: stitch_progress_reports_every_pair_with_zero_min_interval")
    test_single_frame_no_progress_calls()
    print("OK: single_frame_no_progress_calls")
    test_extract_audio_reports_stitching_and_resets_for_quick_phases()
    print("OK: extract_audio_reports_stitching_and_resets_for_quick_phases")
    print("All stitch-progress tests passed.")
