"""Regression: режимът не бива да брои замръзнала серия (audit 2026-06-07 #1, #2).

`build_regime_snapshot` пуска egregious-laggard серии (>3 периода зад най-свежата от
същата каденция) от breadth → режим пътя; дисплеят остава върху пълния snapshot.
Същият gate се ползва в build_macro_state + quick_briefing + weekly_briefing.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from export.data_status import build_regime_snapshot
from catalog.series import SERIES_CATALOG


def _monthly_keys(n: int = 2) -> list[str]:
    keys = [
        k for k, m in SERIES_CATALOG.items()
        if m.get("release_schedule") == "monthly"
    ][:n]
    assert len(keys) == n, "нужни са достатъчно месечни серии в каталога"
    return keys


def test_frozen_series_excluded():
    """Замръзнала месечна серия (~12 мес зад свеж peer) → вън от режимния snapshot."""
    fresh_key, frozen_key = _monthly_keys(2)
    idx_fresh = pd.date_range("2021-07-01", periods=60, freq="MS")    # край 2026-06
    idx_frozen = pd.date_range("2020-07-01", periods=60, freq="MS")   # край 2025-06
    snap = {
        fresh_key: pd.Series(range(60), index=idx_fresh, dtype=float),
        frozen_key: pd.Series(range(60), index=idx_frozen, dtype=float),
    }
    clean, excluded = build_regime_snapshot(snap)
    assert frozen_key in excluded
    assert fresh_key not in excluded
    assert frozen_key not in clean
    assert fresh_key in clean


def test_normal_lag_kept():
    """2 месеца зад (< 3-периоден праг) → серията остава."""
    a, b = _monthly_keys(2)
    idx_a = pd.date_range("2021-07-01", periods=60, freq="MS")   # край 2026-06
    idx_b = pd.date_range("2021-05-01", periods=60, freq="MS")   # край 2026-04
    snap = {
        a: pd.Series(range(60), index=idx_a, dtype=float),
        b: pd.Series(range(60), index=idx_b, dtype=float),
    }
    clean, excluded = build_regime_snapshot(snap)
    assert excluded == []
    assert a in clean and b in clean


def test_empty_and_none_pass_through():
    """Празна / None серия не се изключва (downstream я обработва както преди)."""
    (a,) = _monthly_keys(1)
    snap = {a: pd.Series(dtype=float), "X_UNKNOWN_SERIES": None}
    clean, excluded = build_regime_snapshot(snap)
    assert excluded == []
    assert a in clean and "X_UNKNOWN_SERIES" in clean


def test_build_macro_state_surfaces_annotation():
    """Интеграция: замръзнала серия → executive_summary.stale_excluded_keys."""
    from export_api import build_macro_state

    fresh_idx = pd.date_range("2021-07-01", periods=60, freq="MS")    # 2026-06
    frozen_idx = pd.date_range("2020-07-01", periods=60, freq="MS")   # 2025-06
    snap = {
        k: pd.Series(range(1, 61), index=fresh_idx, dtype=float)
        for k in SERIES_CATALOG
    }
    frozen_key = _monthly_keys(1)[0]
    snap[frozen_key] = pd.Series(range(1, 61), index=frozen_idx, dtype=float)

    state = build_macro_state(snap, date(2026, 6, 6))
    es = state["executive_summary"]
    assert es["stale_excluded_count"] >= 1
    assert frozen_key in es["stale_excluded_keys"]
