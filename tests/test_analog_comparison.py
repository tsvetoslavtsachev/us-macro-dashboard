"""
tests/test_analog_comparison.py
================================
Тестове за dim-level comparison между current и analog.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from analysis.analog_comparison import (  # noqa: E402
    DIVERGENCE_THRESHOLD,
    TIGHT_MATCH_THRESHOLD,
    compare_dimensions,
    format_delta_line,
)
from analysis.analog_matcher import AnalogResult
from analysis.macro_vector import MacroState, STATE_VECTOR_DIMS


# ============================================================
# HELPERS
# ============================================================

def _mk_state(z_values: dict[str, float], raw_values: dict[str, float] = None) -> MacroState:
    """Помага при минимални MacroState обекти за тестове."""
    if raw_values is None:
        raw_values = {k: v * 2.0 for k, v in z_values.items()}  # arbitrary raw
    # fill missing dims with 0.0
    z = {d: z_values.get(d, 0.0) for d in STATE_VECTOR_DIMS}
    raw = {d: raw_values.get(d, 0.0) for d in STATE_VECTOR_DIMS}
    return MacroState(as_of=pd.Timestamp("2026-03-31"), raw=raw, z=z)


def _mk_analog(z_values: dict[str, float], raw_values: dict[str, float] = None) -> AnalogResult:
    if raw_values is None:
        raw_values = {k: v * 2.0 for k, v in z_values.items()}
    z = {d: z_values.get(d, 0.0) for d in STATE_VECTOR_DIMS}
    raw = {d: raw_values.get(d, 0.0) for d in STATE_VECTOR_DIMS}
    return AnalogResult(
        date=pd.Timestamp("1981-06-30"),
        similarity=0.88,
        rank=1,
        raw=raw,
        z=z,
        episode_label="Volcker disinflation",
    )


# ============================================================
# TESTS
# ============================================================

class TestCompareDimensions:

    def test_identical_state_has_no_divergences(self):
        cur = _mk_state({d: 0.5 for d in STATE_VECTOR_DIMS})
        ana = _mk_analog({d: 0.5 for d in STATE_VECTOR_DIMS})
        comp = compare_dimensions(cur, ana)
        assert all(d.abs_z_diff == 0.0 for d in comp.similarities)
        assert comp.divergences == []

    def test_similarities_sorted_closest_first(self):
        cur = _mk_state({
            "unrate": 0.0, "core_cpi_yoy": 0.0, "real_ffr": 0.0, "yc_10y2y": 0.0,
            "hy_oas": 0.0, "ip_yoy": 0.0, "breakeven": 0.0, "sahm": 0.0,
        })
        ana = _mk_analog({
            "unrate": 0.1,        # closest
            "core_cpi_yoy": 1.5,  # divergent
            "real_ffr": 0.3,
            "yc_10y2y": -0.2,
            "hy_oas": 0.05,       # second closest
            "ip_yoy": 0.8,
            "breakeven": -1.2,    # divergent
            "sahm": 0.4,
        })
        comp = compare_dimensions(cur, ana)
        # Първата е hy_oas (0.05), втората unrate (0.10)
        assert comp.similarities[0].dim == "hy_oas"
        assert comp.similarities[1].dim == "unrate"

    def test_divergences_contain_only_large_diffs(self):
        cur = _mk_state({d: 0.0 for d in STATE_VECTOR_DIMS})
        ana = _mk_analog({
            "unrate": 0.2,        # tight
            "core_cpi_yoy": 1.5,  # diverge
            "real_ffr": 0.6,      # close (>0.5, <1.0)
            "yc_10y2y": 2.0,      # diverge
            "hy_oas": 0.0,
            "ip_yoy": 0.0,
            "breakeven": 0.0,
            "sahm": 0.0,
        })
        comp = compare_dimensions(cur, ana)
        divergent_dims = {d.dim for d in comp.divergences}
        assert "core_cpi_yoy" in divergent_dims
        assert "yc_10y2y" in divergent_dims
        assert "unrate" not in divergent_dims
        assert "real_ffr" not in divergent_dims

    def test_divergences_sorted_largest_first(self):
        cur = _mk_state({d: 0.0 for d in STATE_VECTOR_DIMS})
        ana = _mk_analog({
            "core_cpi_yoy": 1.2,
            "yc_10y2y": 2.5,
            "hy_oas": 1.8,
        })
        comp = compare_dimensions(cur, ana)
        abs_diffs = [d.abs_z_diff for d in comp.divergences]
        assert abs_diffs == sorted(abs_diffs, reverse=True)

    def test_classification_labels(self):
        cur = _mk_state({d: 0.0 for d in STATE_VECTOR_DIMS})
        ana = _mk_analog({
            "unrate": 0.2,        # abs=0.2 < 0.5 → tight
            "core_cpi_yoy": 0.7,  # abs=0.7 close
            "real_ffr": 1.5,      # abs=1.5 diverge
        })
        comp = compare_dimensions(cur, ana)
        by_dim = {d.dim: d for d in comp.similarities}
        assert by_dim["unrate"].classification == "tight"
        assert by_dim["core_cpi_yoy"].classification == "close"
        assert by_dim["real_ffr"].classification == "diverge"


class TestFormatDeltaLine:

    def test_contains_label_and_values(self):
        cur = _mk_state({"unrate": 0.0}, {"unrate": 4.2})
        ana = _mk_analog({"unrate": 0.5}, {"unrate": 4.8})
        comp = compare_dimensions(cur, ana)
        # Намираме unrate дим delta
        unrate_delta = next(d for d in comp.similarities if d.dim == "unrate")
        line = format_delta_line(unrate_delta)
        assert "Безработица" in line
        assert "4.20" in line
        assert "4.80" in line
        assert "Δz" in line

    def test_positive_sign_prefix(self):
        cur = _mk_state({"unrate": 0.0}, {"unrate": 4.0})
        ana = _mk_analog({"unrate": 0.5}, {"unrate": 4.5})
        comp = compare_dimensions(cur, ana)
        unrate_delta = next(d for d in comp.similarities if d.dim == "unrate")
        line = format_delta_line(unrate_delta)
        assert "Δz=+0.50" in line
