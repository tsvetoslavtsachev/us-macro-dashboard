"""Tests за relative staleness флаг в export_api.latest (US↔EU parity).

`stale`/`periods_behind` се смятат каденс-aware спрямо най-свежата серия от СЪЩАТА
каденция — една глобална логика (огледало на quick_briefing), без per-series tuning.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from export_api import _relative_staleness, build_series_data, ALL_CHART_SERIES
from catalog.series import SERIES_CATALOG


# ── helper (каденс-aware relative staleness) ──────────────────────────────────

def test_egregious_laggard_flagged():
    ref = {"monthly": pd.Timestamp("2026-05-01")}
    stale, pb = _relative_staleness("2025-06-01", "monthly", ref)  # ~11 мес зад
    assert stale is True
    assert pb >= 4


def test_normal_lag_not_flagged():
    ref = {"monthly": pd.Timestamp("2026-05-01")}
    stale, pb = _relative_staleness("2026-03-01", "monthly", ref)  # 2 мес зад
    assert stale is False
    assert pb <= 2


def test_quarterly_two_periods_not_stale():
    # Каденс-aware: 2 тримесечия зад < 3-периоден праг → НЕ stale.
    ref = {"quarterly": pd.Timestamp("2026-04-01")}
    stale, pb = _relative_staleness("2025-10-01", "quarterly", ref)
    assert stale is False
    assert pb <= 2


def test_missing_ref_or_date_safe():
    assert _relative_staleness("2026-01-01", "weekly", {}) == (False, 0)
    assert _relative_staleness(
        None, "monthly", {"monthly": pd.Timestamp("2026-05-01")}
    ) == (False, 0)


# ── integration: build_series_data носи флага в latest{} ──────────────────────

def test_build_series_data_carries_stale_flag():
    """Изостанала серия → latest.stale=True; свеж peer от същата каденция → False."""
    monthly_chart = [
        sid for sid in ALL_CHART_SERIES
        if SERIES_CATALOG.get(sid, {}).get("release_schedule") == "monthly"
    ]
    assert len(monthly_chart) >= 2, "нужни са ≥2 месечни chart серии за fixture-а"
    fresh_key, stale_key = monthly_chart[0], monthly_chart[1]

    idx_fresh = pd.date_range("2021-06-01", periods=60, freq="MS")   # край 2026-05
    idx_stale = pd.date_range("2020-07-01", periods=60, freq="MS")   # край 2025-06
    snapshot = {
        fresh_key: pd.Series(range(1, 61), index=idx_fresh, dtype=float),
        stale_key: pd.Series(range(1, 61), index=idx_stale, dtype=float),
    }

    out = build_series_data(snapshot, date(2026, 6, 6))
    series = out["series"]

    assert fresh_key in series and stale_key in series
    assert series[stale_key]["latest"]["stale"] is True
    assert series[stale_key]["latest"]["periods_behind"] >= 4
    assert series[fresh_key]["latest"]["stale"] is False
    assert series[fresh_key]["latest"]["periods_behind"] == 0
