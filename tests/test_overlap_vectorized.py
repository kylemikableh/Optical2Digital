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

"""Parity checks for the vectorized overlap-search implementation.

Run directly with python3 (this project has no pytest setup):
    python3 tests/test_overlap_vectorized.py

_overlap_errors_vectorized() replaced the original per-offset Python loop
(kept as _overlap_errors_loop(), the reference implementation) for
performance. These tests assert the two produce matching best_offset (exact)
and best_error (tight float tolerance -- the underlying summation order can
differ slightly between the loop and the batched/masked-sum vectorized
path, so bit-identical isn't guaranteed, only equivalent to within
floating-point noise) across a battery of inputs, including edge cases.
"""
import os
import sys

import numpy as np

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
import KylesOpticalDecoder as kod


def _assert_matches(prev, curr, max_overlap, label):
    search_range = min(max_overlap, len(prev) // 2, len(curr) // 2)

    loop_offset = kod.find_best_overlap(prev, curr, max_overlap)

    if search_range < 2:
        assert loop_offset == 0, f"[{label}] expected 0 for tiny search_range"
        return

    loop_errors = kod._overlap_errors_loop(prev, curr, search_range)
    vec_errors = kod._overlap_errors_vectorized(prev, curr, search_range)

    assert loop_errors.shape == vec_errors.shape, (
        f"[{label}] shape mismatch: loop {loop_errors.shape} vs vec {vec_errors.shape}"
    )
    max_diff = np.max(np.abs(loop_errors - vec_errors))
    assert max_diff < 1e-9, f"[{label}] error arrays diverge by {max_diff}"

    vec_offset = int(np.argmin(vec_errors)) + 1
    loop_offset_ref = int(np.argmin(loop_errors)) + 1
    assert vec_offset == loop_offset_ref, (
        f"[{label}] best_offset mismatch: loop-derived {loop_offset_ref} vs vec {vec_offset}"
    )
    assert loop_offset == vec_offset, (
        f"[{label}] find_best_overlap() ({loop_offset}) doesn't match vectorized argmin ({vec_offset})"
    )

    # _find_best_overlap_with_error() must agree too.
    err_offset, err_value = kod._find_best_overlap_with_error(prev, curr, max_overlap)
    assert err_offset == vec_offset, f"[{label}] _find_best_overlap_with_error offset mismatch"
    assert abs(err_value - float(vec_errors[vec_offset - 1])) < 1e-9, (
        f"[{label}] _find_best_overlap_with_error error value mismatch"
    )


def test_random_arrays():
    rng = np.random.default_rng(1234)
    for trial in range(20):
        n = rng.integers(20, 400)
        prev = rng.random(n) * 2 - 1
        curr = rng.random(n) * 2 - 1
        max_overlap = int(n * rng.uniform(0.05, 0.5))
        _assert_matches(prev, curr, max_overlap, f"random-{trial}")


def test_identical_arrays_exact_tie():
    """All-equal signal: every offset scores error=0. Both the loop (strict
    `<`, first offset wins and is never displaced by a later tie) and the
    vectorized argmin (first occurrence of the minimum) must agree on
    offset=1."""
    prev = np.full(50, 0.5)
    curr = np.full(50, 0.5)
    _assert_matches(prev, curr, 20, "identical-tie")


def test_all_zero_signal():
    prev = np.zeros(60)
    curr = np.zeros(60)
    _assert_matches(prev, curr, 25, "all-zero")


def test_search_range_too_small_returns_zero():
    prev = np.array([1.0, 2.0, 3.0])
    curr = np.array([4.0, 5.0, 6.0])
    assert kod.find_best_overlap(prev, curr, 1) == 0
    assert kod._find_best_overlap_with_error(prev, curr, 1) == (0, 0.0)


def test_clear_best_alignment():
    """A single unambiguous best offset should be found identically by
    both implementations."""
    rng = np.random.default_rng(7)
    base = rng.random(200)
    prev = base.copy()
    offset = 37
    curr = np.concatenate([base[-offset:], rng.random(200 - offset)])
    _assert_matches(prev, curr, 80, "clear-alignment")


def test_large_search_range_uses_loop_fallback():
    """Exercise the _OVERLAP_VECTORIZE_MAX_L fallback path directly."""
    L = kod._OVERLAP_VECTORIZE_MAX_L + 50
    search_range = L + 1
    rng = np.random.default_rng(99)
    prev = rng.random(search_range * 2)
    curr = rng.random(search_range * 2)
    errors = kod._overlap_errors_vectorized(prev, curr, search_range)
    # Falls back to the loop implementation -- confirm it actually matches
    # the loop bit-for-bit (same code path, not just "close").
    loop_errors = kod._overlap_errors_loop(prev, curr, search_range)
    assert np.array_equal(errors, loop_errors), "fallback path should equal the loop exactly"


if __name__ == "__main__":
    test_random_arrays()
    print("OK: random_arrays")
    test_identical_arrays_exact_tie()
    print("OK: identical_arrays_exact_tie")
    test_all_zero_signal()
    print("OK: all_zero_signal")
    test_search_range_too_small_returns_zero()
    print("OK: search_range_too_small_returns_zero")
    test_clear_best_alignment()
    print("OK: clear_best_alignment")
    test_large_search_range_uses_loop_fallback()
    print("OK: large_search_range_uses_loop_fallback")
    print("All overlap-vectorization parity tests passed.")
