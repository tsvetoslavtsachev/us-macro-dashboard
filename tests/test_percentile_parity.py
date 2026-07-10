"""
tests/test_percentile_parity.py
================================
O3 Вълна 1 (КОКПИТ) · живо доказателство №1 — една реална серия дава СЪЩОТО
percentile число в api / briefing / web при default (10-г. канон).

Трите повърхности вече споделят прозореца:
  • api  (export_api → series_data.json `latest.percentile`) = score_series
    percentile: trailing-10г ранг върху ТРАНСФОРМИРАНАТА величина.
  • briefing (export/briefing_context._percentile_5y, HISTORY_YEARS=10 канон).
  • web (macro-web index.html): при default (10г канон) показва JSON `latest.percentile`
    директно (не преизчислява) → числото е ТОЧНО api-числото; при мръднат слайдер
    показва изследователски прозорец с изричен етикет.

За level-серия (transform=level) трансформираната величина = суровата, така че
api-percentile и briefing-percentile смятат едно и също нещо върху един и същ
10-г. прозорец → трябва да съвпаднат (до закръгление 1 знак на api слоя).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.scorer import score_series  # noqa: E402
from export.briefing_context import _percentile_5y, HISTORY_YEARS  # noqa: E402


def monthly(values, end="2026-03-01"):
    idx = pd.date_range(end=end, periods=len(values), freq="MS")
    return pd.Series(values, index=idx)


def test_briefing_canon_is_ten_years():
    """B5: briefing_context канонът е 10г (не 5г)."""
    assert HISTORY_YEARS == 10


def test_api_equals_briefing_percentile_level_series():
    """Живо док. №1: api percentile == briefing percentile за level-серия, при
    default 10-г. прозорец. (Web при default показва api-числото директно.)"""
    rng = np.random.default_rng(11)
    s = monthly(list(4.0 + np.cumsum(rng.normal(0.0, 0.15, 220))))

    api = score_series(s, name="LEVEL_X", transform="level", polarity=+1)
    api_pct = api["percentile"]
    brief_pct = _percentile_5y(s)  # history_years=HISTORY_YEARS=10

    assert api_pct is not None and brief_pct is not None
    # api закръгля до 1 знак; briefing връща суров float → допуск 0.06.
    assert api_pct == pytest.approx(brief_pct, abs=0.06), (
        f"api={api_pct} != briefing={brief_pct} — прозорците се разминаха"
    )
    # Прозорецът е канонният 10-г. (носи се на лицето).
    assert api["percentile_window"] == "10г"


def test_percentile_window_label_present_and_canonical():
    """Прозорец-етикетът е винаги на лицето (голо percentile = дефект)."""
    rng = np.random.default_rng(5)
    s = monthly(list(3.0 + np.cumsum(rng.normal(0.0, 0.1, 200))))
    api = score_series(s, name="X", transform="level", polarity=+1)
    assert api["percentile_window"] in ("10г", "пълна история")
    assert api["percentile_window"] == "10г"  # достатъчна история → канон
