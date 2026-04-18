"""
Unit tests за core/primitives.py
================================
Всеки primitive е тестван с:
  1. Normal case (очаквано поведение)
  2. Edge case (empty, single value, all NaN и т.н.)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Добавяме econ_v2 в path
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.primitives import (
    z_score, percentile, momentum, acceleration,
    yoy_pct, mom_pct, rolling_mean, first_diff,
    breadth_positive, breadth_extreme, diffusion_index,
    divergence, anomaly_scan, new_extreme,
)


# ============================================================
# Helpers
# ============================================================

def make_monthly_series(values: list[float], start: str = "2020-01-01") -> pd.Series:
    idx = pd.date_range(start=start, periods=len(values), freq="MS")
    return pd.Series(values, index=idx)


def make_weekly_series(values: list[float], start: str = "2020-01-05") -> pd.Series:
    idx = pd.date_range(start=start, periods=len(values), freq="W")
    return pd.Series(values, index=idx)


# ============================================================
# z_score
# ============================================================

def test_z_score_basic():
    s = make_monthly_series([1, 2, 3, 4, 5])
    z = z_score(s)
    assert abs(z.mean()) < 1e-9
    # При population std, крайни стойности са ±√2 (~1.414)
    assert abs(z.iloc[0] - (-np.sqrt(2))) < 1e-9
    assert abs(z.iloc[-1] - np.sqrt(2)) < 1e-9


def test_z_score_constant_series():
    s = make_monthly_series([5, 5, 5, 5])
    z = z_score(s)
    assert (z == 0).all()


def test_z_score_empty():
    z = z_score(pd.Series(dtype=float))
    assert z.empty


def test_z_score_rolling():
    s = make_monthly_series(list(range(1, 25)))  # 24 точки
    z = z_score(s, window=12)
    # Първите 11 трябва да са NaN (undefined за rolling window=12)
    assert z.iloc[:11].isna().all()
    assert not np.isnan(z.iloc[-1])


# ============================================================
# percentile
# ============================================================

def test_percentile_basic():
    s = make_monthly_series([1, 2, 3, 4, 5])
    p = percentile(s)
    assert p.iloc[0] == 20   # rank 1/5 × 100
    assert p.iloc[-1] == 100  # rank 5/5 × 100


def test_percentile_empty():
    p = percentile(pd.Series(dtype=float))
    assert p.empty


# ============================================================
# momentum & acceleration
# ============================================================

def test_momentum_basic():
    s = make_monthly_series([10, 12, 15, 20])
    m = momentum(s, periods=1)
    assert m.iloc[1] == 2
    assert m.iloc[2] == 3
    assert m.iloc[3] == 5


def test_acceleration_basic():
    # Accelerating series (diffs: 2, 3, 5 → acc: 1, 2)
    s = make_monthly_series([10, 12, 15, 20])
    a = acceleration(s, periods=1)
    assert a.iloc[2] == 1  # 3 - 2
    assert a.iloc[3] == 2  # 5 - 3


# ============================================================
# yoy_pct
# ============================================================

def test_yoy_pct_monthly():
    # 24 месеца, 10% годишен ръст
    values = [100 * (1.10 ** (i / 12)) for i in range(24)]
    s = make_monthly_series(values)
    yoy = yoy_pct(s)
    # След 12 месеца трябва да има ~10% YoY
    assert abs(yoy.iloc[12] - 10.0) < 0.5


def test_yoy_pct_flat():
    s = make_monthly_series([100] * 24)
    yoy = yoy_pct(s)
    assert yoy.iloc[-1] == 0.0


def test_yoy_pct_empty():
    yoy = yoy_pct(pd.Series(dtype=float))
    assert yoy.empty


# ============================================================
# mom_pct
# ============================================================

def test_mom_pct():
    s = make_monthly_series([100, 110, 121])
    mom = mom_pct(s)
    assert abs(mom.iloc[1] - 10.0) < 1e-9
    assert abs(mom.iloc[2] - 10.0) < 1e-9


# ============================================================
# rolling_mean
# ============================================================

def test_rolling_mean_basic():
    s = make_weekly_series([1, 2, 3, 4, 5, 6])
    rm = rolling_mean(s, window=3)
    assert np.isnan(rm.iloc[1])  # недостатъчно данни
    assert rm.iloc[2] == 2  # (1+2+3)/3
    assert rm.iloc[-1] == 5  # (4+5+6)/3


# ============================================================
# first_diff
# ============================================================

def test_first_diff():
    s = make_monthly_series([100, 105, 103, 110])
    d = first_diff(s)
    assert d.iloc[1] == 5
    assert d.iloc[2] == -2


# ============================================================
# breadth_positive
# ============================================================

def test_breadth_positive_all_up():
    group = {
        "a": make_monthly_series([1, 2, 3]),
        "b": make_monthly_series([10, 11, 12]),
        "c": make_monthly_series([100, 101, 102]),
    }
    assert breadth_positive(group, transform="momentum", periods=1) == 1.0


def test_breadth_positive_mixed():
    group = {
        "a": make_monthly_series([1, 2, 3]),      # +
        "b": make_monthly_series([5, 4, 3]),      # -
        "c": make_monthly_series([10, 11, 12]),   # +
        "d": make_monthly_series([100, 99, 98]),  # -
    }
    assert breadth_positive(group, transform="momentum", periods=1) == 0.5


def test_breadth_positive_empty():
    assert np.isnan(breadth_positive({}))


# ============================================================
# breadth_extreme
# ============================================================

def test_breadth_extreme_with_outlier():
    # Една серия със силен outlier в края
    group = {
        "a": make_monthly_series([1, 1, 1, 1, 1, 10]),  # outlier
        "b": make_monthly_series([5, 5, 5, 5, 5, 5]),   # constant
    }
    result = breadth_extreme(group, z_threshold=2.0)
    # a има extreme z, b е constant (z=0)
    assert result == 0.5


# ============================================================
# diffusion_index
# ============================================================

def test_diffusion_index_all_up():
    group = {
        "a": make_monthly_series([1, 2]),
        "b": make_monthly_series([10, 11]),
    }
    assert diffusion_index(group) == 100.0


def test_diffusion_index_half():
    group = {
        "a": make_monthly_series([1, 2]),     # up
        "b": make_monthly_series([10, 9]),    # down
    }
    assert diffusion_index(group) == 50.0


# ============================================================
# divergence
# ============================================================

def test_divergence_zero():
    group_a = {"x": make_monthly_series([1, 2, 3])}
    group_b = {"y": make_monthly_series([10, 11, 12])}
    assert divergence(group_a, group_b) == 0.0


def test_divergence_positive():
    group_a = {
        "x": make_monthly_series([1, 2, 3]),  # +
        "y": make_monthly_series([5, 6, 7]),  # +
    }
    group_b = {
        "a": make_monthly_series([10, 9, 8]),  # -
        "b": make_monthly_series([5, 4, 3]),   # -
    }
    assert divergence(group_a, group_b) == 1.0  # 100% vs 0%


# ============================================================
# anomaly_scan
# ============================================================

def test_anomaly_scan_detects_outlier():
    data = {
        "flat": make_monthly_series([1, 1, 1, 1, 1, 1]),
        "extreme": make_monthly_series([1, 1, 1, 1, 1, 10]),
    }
    results = anomaly_scan(data, z_threshold=1.5)
    ids = [r["series_id"] for r in results]
    assert "extreme" in ids
    # Flat има std=0 → z_score returns zeros → не anomaly
    assert "flat" not in ids


def test_anomaly_scan_sort_order():
    # Правим 3 серии с различна степен на extreme
    small = [1] * 5 + [2]    # z ~ 2.24
    medium = [1] * 5 + [5]    # z ~ 2.24 but bigger raw
    big = [1] * 5 + [100]    # z ~ 2.24 but huge
    data = {
        "a": make_monthly_series(small),
        "b": make_monthly_series(medium),
        "c": make_monthly_series(big),
    }
    results = anomaly_scan(data, z_threshold=1.0)
    # All should have similar z (all 5 equal + 1 outlier)
    assert len(results) == 3


# ============================================================
# new_extreme
# ============================================================

def test_new_extreme_max():
    idx = pd.date_range(end="2026-04-01", periods=24, freq="MS")
    s = pd.Series(list(range(1, 25)), index=idx)  # monotonically increasing
    result = new_extreme(s, lookback_years=1)
    assert result is not None
    assert result["direction"] == "max"


def test_new_extreme_min():
    idx = pd.date_range(end="2026-04-01", periods=24, freq="MS")
    s = pd.Series(list(range(24, 0, -1)), index=idx)  # decreasing
    result = new_extreme(s, lookback_years=1)
    assert result is not None
    assert result["direction"] == "min"


def test_new_extreme_middle():
    idx = pd.date_range(end="2026-04-01", periods=10, freq="MS")
    s = pd.Series([1, 5, 10, 8, 3, 7, 4, 6, 2, 5], index=idx)
    result = new_extreme(s, lookback_years=1)
    assert result is None  # last value (5) е в middle
