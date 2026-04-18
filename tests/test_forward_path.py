"""
tests/test_forward_path.py
===========================
Тестове за forward outcomes ангажимента.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from analysis.analog_matcher import AnalogResult
from analysis.forward_path import (  # noqa: E402
    DEFAULT_HORIZONS_MONTHS,
    DEFAULT_OUTCOME_DIMS,
    ForwardOutcomes,
    HorizonSummary,
    PerAnalogForward,
    _forward_value,
    forward_outcomes,
)


# ============================================================
# HELPERS
# ============================================================

def _simple_history(n_years: int = 50) -> pd.DataFrame:
    """Синтетична history с 4 dim-а и линеарни тренове."""
    idx = pd.date_range("1976-01-31", periods=n_years * 12, freq="ME")
    n = len(idx)
    return pd.DataFrame({
        "unrate":       4.0 + 0.01 * np.arange(n),        # бавно растящ
        "core_cpi_yoy": 2.5 + 0.005 * np.arange(n),
        "real_ffr":     1.0 + 0.01 * np.sin(np.arange(n) / 6),
        "yc_10y2y":     1.5 + 0.005 * np.cos(np.arange(n) / 12),
    }, index=idx)


def _mk_analog(date: pd.Timestamp, label: str = None) -> AnalogResult:
    return AnalogResult(
        date=date, similarity=0.85, rank=1,
        raw={}, z={},
        episode_label=label,
    )


# ============================================================
# _forward_value
# ============================================================

class TestForwardValuePrimitive:

    def test_finds_value_at_exact_horizon(self):
        idx = pd.date_range("2020-01-31", periods=24, freq="ME")
        s = pd.Series(np.arange(24, dtype=float), index=idx)
        # anchor Jan 2020, horizon 6m → July 2020 → index 6 → value 6
        v = _forward_value(s, idx[0], 6)
        assert v == pytest.approx(6.0)

    def test_returns_none_when_horizon_beyond_series(self):
        idx = pd.date_range("2020-01-31", periods=10, freq="ME")
        s = pd.Series(np.arange(10, dtype=float), index=idx)
        # anchor at end, horizon 12m → няма данни
        v = _forward_value(s, idx[-1], 12)
        assert v is None

    def test_empty_series_returns_none(self):
        s = pd.Series(dtype=float)
        assert _forward_value(s, pd.Timestamp("2020-01-31"), 6) is None


# ============================================================
# forward_outcomes
# ============================================================

class TestForwardOutcomes:

    def test_default_horizons_and_dims(self):
        hist = _simple_history()
        analogs = [_mk_analog(pd.Timestamp("2000-01-31"))]
        out = forward_outcomes(hist, analogs)
        assert out.horizons == DEFAULT_HORIZONS_MONTHS
        assert set(out.dims) == set(DEFAULT_OUTCOME_DIMS)

    def test_per_analog_has_values_for_each_dim_and_horizon(self):
        hist = _simple_history()
        analogs = [_mk_analog(pd.Timestamp("2000-01-31"), "Test Episode")]
        out = forward_outcomes(hist, analogs)
        pa = out.per_analog[0]
        assert pa.analog_date == pd.Timestamp("2000-01-31")
        assert pa.episode_label == "Test Episode"
        for d in DEFAULT_OUTCOME_DIMS:
            for h in DEFAULT_HORIZONS_MONTHS:
                assert h in pa.values[d]
                assert h in pa.deltas[d]

    def test_aggregates_has_median_min_max(self):
        hist = _simple_history()
        analogs = [
            _mk_analog(pd.Timestamp("1990-01-31")),
            _mk_analog(pd.Timestamp("2000-01-31")),
            _mk_analog(pd.Timestamp("2010-01-31")),
        ]
        out = forward_outcomes(hist, analogs)
        for agg in out.aggregates:
            if agg.n > 0:
                assert agg.median_value is not None
                assert agg.min_value is not None
                assert agg.max_value is not None
                assert agg.min_value <= agg.median_value <= agg.max_value

    def test_analog_at_end_gives_none_for_long_horizons(self):
        """Analog в последния месец от history-та не може да има 12m forward."""
        hist = _simple_history()
        last = hist.index[-1]
        analogs = [_mk_analog(last)]
        out = forward_outcomes(hist, analogs)
        pa = out.per_analog[0]
        # 12m напред извън history
        for d in DEFAULT_OUTCOME_DIMS:
            assert 12 not in pa.values[d]
            assert 12 not in pa.deltas[d]

    def test_unrate_rises_consistent_with_forward(self):
        """В нашата синтетика UNRATE расте линеарно — 12m напред трябва
        да е ~0.12 над anchor-а."""
        hist = _simple_history()
        anchor = pd.Timestamp("2000-01-31")
        analogs = [_mk_analog(anchor)]
        out = forward_outcomes(hist, analogs)
        pa = out.per_analog[0]
        # delta unrate 12m = 12 × 0.01 = 0.12
        assert pa.deltas["unrate"][12] == pytest.approx(0.12, rel=1e-3)

    def test_subset_of_outcome_dims(self):
        hist = _simple_history()
        analogs = [_mk_analog(pd.Timestamp("2000-01-31"))]
        out = forward_outcomes(hist, analogs, outcome_dims=["unrate"])
        assert out.dims == ["unrate"]
        pa = out.per_analog[0]
        assert set(pa.values.keys()) == {"unrate"}

    def test_missing_dim_is_filtered(self):
        hist = _simple_history()
        analogs = [_mk_analog(pd.Timestamp("2000-01-31"))]
        out = forward_outcomes(hist, analogs, outcome_dims=["unrate", "nonexistent"])
        assert "nonexistent" not in out.dims

    def test_empty_analogs_returns_empty_per_analog(self):
        hist = _simple_history()
        out = forward_outcomes(hist, analogs=[])
        assert out.per_analog == []
        # aggregates имат 0 observations навсякъде
        for agg in out.aggregates:
            assert agg.n == 0

    def test_horizon_summary_dim_and_horizon_match(self):
        hist = _simple_history()
        analogs = [_mk_analog(pd.Timestamp("2000-01-31"))]
        out = forward_outcomes(hist, analogs, horizons_months=[3, 6, 12], outcome_dims=["unrate"])
        combos = {(a.dim, a.horizon_months) for a in out.aggregates}
        assert ("unrate", 3) in combos
        assert ("unrate", 6) in combos
        assert ("unrate", 12) in combos
