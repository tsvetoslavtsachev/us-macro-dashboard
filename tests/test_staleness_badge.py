"""Tests за RELATIVE staleness флаг в quick_briefing (US↔EU parity).

Серия е "stale" само ако е >3 периода зад най-свежата от СЪЩАТА каденция —
хваща егрегиозните изоставащи (HICP-тип, месеци назад), без да флагва нормалния
по-голям release lag на бавните серии. Една глобална каденс-aware логика.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from export.quick_briefing import _lens_readings
from export.data_status import PERIOD_LENGTH_DAYS
from export.weekly_briefing import LENS_ORDER
from catalog.series import series_by_lens, SERIES_CATALOG


def make_monthly(values, start):
    idx = pd.date_range(start=start, periods=len(values), freq="MS")
    return pd.Series(values, index=idx)


def _lens_with_two_monthly():
    """Първата леща с ≥2 месечни серии (детерминистично от каталога)."""
    for lens in LENS_ORDER:
        monthly = [
            m["_key"] for m in series_by_lens(lens)
            if SERIES_CATALOG.get(m["_key"], {}).get("release_schedule") == "monthly"
        ]
        if len(monthly) >= 2:
            return lens, monthly
    raise RuntimeError("Няма леща с ≥2 месечни серии — fixture-ът не може да се построи")


def test_relative_stale_series_flagged_fresh_not():
    """Серия 11 месеца зад свежите си месечни peer-и → stale=True; свежите → False."""
    lens, monthly = _lens_with_two_monthly()
    stale_key = monthly[0]

    snapshot = {}
    for k in monthly:
        # 60 месечни точки, край 2026-05-01 (свежи)
        snapshot[k] = make_monthly(np.linspace(95.0, 105.0, 60).tolist(), start="2021-06-01")
    # изостаналата: край 2025-06-01 → 11 мес. зад свежите (>3 периода за monthly)
    snapshot[stale_key] = make_monthly(np.linspace(95.0, 105.0, 60).tolist(), start="2020-07-01")

    rows = _lens_readings(lens, snapshot, top_n=99)

    stale_rows = [r for r in rows if str(r["date"]).startswith("2025-06")]
    fresh_rows = [r for r in rows if str(r["date"]).startswith("2026-05")]

    assert stale_rows, "изостаналата серия трябва да присъства в readings"
    assert all(r["stale"] is True for r in stale_rows)
    assert fresh_rows, "трябва да има поне една свежа серия за контраст"
    assert all(r["stale"] is False for r in fresh_rows)


def test_normal_lag_not_flagged():
    """Серия само 2 периода зад (нормален lag) → НЕ е stale (праг = >3 периода)."""
    lens, monthly = _lens_with_two_monthly()
    lagged_key = monthly[0]

    snapshot = {}
    for k in monthly:
        snapshot[k] = make_monthly(np.linspace(95.0, 105.0, 60).tolist(), start="2021-06-01")
    # 2 месеца зад (край 2026-03-01) — нормален lag, под прага
    snapshot[lagged_key] = make_monthly(np.linspace(95.0, 105.0, 60).tolist(), start="2021-04-01")

    rows = _lens_readings(lens, snapshot, top_n=99)
    assert rows, "очакваме поне една серия"
    assert all(r["stale"] is False for r in rows)


def test_period_length_constant_mirrors_eu():
    """Праговете на каденцията — заключени (огледало на EU; без per-series tuning)."""
    assert PERIOD_LENGTH_DAYS["weekly"] == 7
    assert PERIOD_LENGTH_DAYS["monthly"] == 30
    assert PERIOD_LENGTH_DAYS["quarterly"] == 90
    assert PERIOD_LENGTH_DAYS["annually"] == 365
