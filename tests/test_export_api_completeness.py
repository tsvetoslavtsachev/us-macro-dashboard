"""Tests за export_api пълнота (нишка 2) — ISM/CB/SOFR-OIS/PMI/housing влизат в
series_data.json; snapshot-ът на main() долива external + bloomberg (US<->EU parity).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from export_api import ALL_CHART_SERIES, build_series_data, _bloomberg_bridge_snapshot


NEW_CHART = [
    # growth: external + bloomberg
    "ISM_MFG_PMI", "ISM_SVCS_PMI", "CB_LEI", "CB_CCI",
    "US_PMI_COMPOSITE", "US_PMI_MFG", "US_PMI_SVCS",
    # liquidity: bloomberg SOFR-OIS
    "US_SOFR_OIS_3M", "US_SOFR_OIS_6M", "US_SOFR_OIS_1Y", "US_SOFR_OIS_2Y",
    # housing: bloomberg
    "NAHB_HMI", "MBA_PURCHASE_IDX", "MBA_REFINANCE_IDX", "NAR_PHSI",
]


def test_new_series_in_chart_set():
    for k in NEW_CHART:
        assert k in ALL_CHART_SERIES, f"{k} липсва в CHART_SERIES"


def test_zhvi_excluded():
    # nishka 4 — ZHVI не се освежава от никой job → не го чертаем.
    assert "ZHVI_US_SFR_CONDO" not in ALL_CHART_SERIES


def test_build_series_data_outputs_external_and_bridge():
    """build_series_data извежда external/bloomberg серии когато са в snapshot-а."""
    midx = pd.date_range("2021-06-01", periods=60, freq="MS")
    didx = pd.date_range("2025-03-01", periods=400, freq="D")
    snapshot = {
        "ISM_MFG_PMI":    pd.Series(np.linspace(48, 55, 60), index=midx),   # external
        "CB_LEI":         pd.Series(np.linspace(100, 112, 60), index=midx),  # external
        "US_PMI_COMPOSITE": pd.Series(np.linspace(49, 54, 60), index=midx),  # bridge
        "US_SOFR_OIS_3M": pd.Series(np.linspace(0.05, 0.25, 400), index=didx),  # bridge daily
        "NAHB_HMI":       pd.Series(np.linspace(35, 60, 60), index=midx),    # bridge housing
    }
    out = build_series_data(snapshot, date(2026, 6, 6))
    series = out["series"]
    for k in snapshot:
        assert k in series, f"{k} не излезе в series_data"
        assert "stale" in series[k]["latest"]  # staleness (нишка 1) важи и за тях


def test_bloomberg_bridge_helper_returns_dict():
    # Smoke: helper-ът не хвърля (връща dict дори при липсващ bridge).
    assert isinstance(_bloomberg_bridge_snapshot(), dict)
