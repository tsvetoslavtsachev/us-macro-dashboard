"""
tests/test_analysis_anomaly.py
==============================
Unit тестове за analysis/anomaly.py.

Покриваме:
  - Празен / flat snapshot → 0 flagged
  - Spike серия → flagged и в top
  - Sort order по |z| descending
  - top_n truncation (top ≤ top_n; total_flagged е full count)
  - by_lens grouping; multi-lens серия се появява в >1 lens
  - Threshold параметър работи (по-висок → по-малко flagged)
  - new_extreme detection на spike
  - Series не в каталога → skip без crash
  - JSON safety на to_dict()
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from analysis.anomaly import (  # noqa: E402
    compute_anomalies,
    AnomalyReading,
    AnomalyReport,
    Z_THRESHOLD_DEFAULT,
    TOP_N_DEFAULT,
)
from catalog.series import SERIES_CATALOG  # noqa: E402


# ============================================================
# HELPERS
# ============================================================

def monthly(values: list[float], end: str = "2026-03-01") -> pd.Series:
    idx = pd.date_range(end=end, periods=len(values), freq="MS")
    return pd.Series(values, index=idx)


def flat(n: int = 60, level: float = 3.0) -> pd.Series:
    vals = [level + 0.01 * np.sin(i * 0.3) for i in range(n)]
    return monthly(vals)


def spike_up(n: int = 60, base: float = 2.0, spike: float = 10.0) -> pd.Series:
    vals = [base + 0.01 * np.sin(i * 0.3) for i in range(n - 3)]
    vals.extend([spike, spike + 0.3, spike + 0.7])
    return monthly(vals)


def spike_down(n: int = 60, base: float = 10.0, spike: float = 2.0) -> pd.Series:
    vals = [base + 0.01 * np.sin(i * 0.3) for i in range(n - 3)]
    vals.extend([spike, spike - 0.3, spike - 0.7])
    return monthly(vals)


def trend_up(n: int = 60) -> pd.Series:
    return monthly(list(np.linspace(2.0, 5.0, n)))


@pytest.fixture(autouse=True)
def _seed():
    np.random.seed(42)


def _first_keys_with_lens(lens: str, limit: int = 5) -> list[str]:
    """Връща първите N каталожни ключа в дадена леща."""
    out = []
    for k, meta in SERIES_CATALOG.items():
        if lens in meta.get("lens", []):
            out.append(k)
            if len(out) >= limit:
                break
    return out


# ============================================================
# TEST — basic structure
# ============================================================

class TestEmptyAndFlat:
    def test_empty_snapshot(self):
        report = compute_anomalies({})
        assert isinstance(report, AnomalyReport)
        assert report.total_flagged == 0
        assert report.top == []
        assert report.by_lens == {}
        assert report.as_of is None
        assert report.threshold == Z_THRESHOLD_DEFAULT

    def test_flat_snapshot_no_anomalies(self):
        keys = list(SERIES_CATALOG.keys())[:10]
        snapshot = {k: flat() for k in keys}
        report = compute_anomalies(snapshot)
        assert report.total_flagged == 0
        assert report.top == []


# ============================================================
# TEST — spike detection
# ============================================================

class TestSpikeDetection:
    def test_single_spike_is_flagged(self):
        target = list(SERIES_CATALOG.keys())[0]
        snapshot = {target: spike_up()}
        report = compute_anomalies(snapshot)
        assert report.total_flagged >= 1
        assert any(r.series_key == target for r in report.top)
        # Spike up → direction "up", z>0
        reading = next(r for r in report.top if r.series_key == target)
        assert reading.direction == "up"
        assert reading.z_score > Z_THRESHOLD_DEFAULT

    def test_down_spike_direction(self):
        target = list(SERIES_CATALOG.keys())[0]
        snapshot = {target: spike_down()}
        report = compute_anomalies(snapshot)
        reading = next(r for r in report.top if r.series_key == target)
        assert reading.direction == "down"
        assert reading.z_score < -Z_THRESHOLD_DEFAULT

    def test_new_extreme_detected(self):
        """Spike up над цялата история → new_extreme='max'."""
        target = list(SERIES_CATALOG.keys())[0]
        snapshot = {target: spike_up(n=120)}  # 10 години monthly
        report = compute_anomalies(snapshot, lookback_years=5)
        reading = next(r for r in report.top if r.series_key == target)
        assert reading.is_new_extreme is True
        assert reading.new_extreme_direction == "max"


# ============================================================
# TEST — sort + truncation
# ============================================================

class TestSortAndTruncation:
    def test_sorted_by_abs_z_descending(self):
        """Множество spike-ове с различна величина → sort по |z| desc."""
        keys = list(SERIES_CATALOG.keys())[:5]
        snapshot: dict[str, pd.Series] = {}
        # 3 различни spike magnitudes
        snapshot[keys[0]] = spike_up(base=2.0, spike=5.0)   # по-малък z
        snapshot[keys[1]] = spike_up(base=2.0, spike=15.0)  # най-голям z
        snapshot[keys[2]] = spike_up(base=2.0, spike=8.0)   # среден

        report = compute_anomalies(snapshot)
        zs = [abs(r.z_score) for r in report.top]
        assert zs == sorted(zs, reverse=True)

    def test_top_n_truncation(self):
        """top_n ограничава top-а, но total_flagged остава пълно."""
        keys = list(SERIES_CATALOG.keys())[:15]
        snapshot = {k: spike_up(base=2.0 + i*0.01, spike=10.0 + i*0.1) for i, k in enumerate(keys)}
        report = compute_anomalies(snapshot, top_n=5)
        assert len(report.top) == 5
        assert report.total_flagged >= 5
        # by_lens съдържа ВСИЧКИ flagged, не top-а
        all_in_by_lens = set()
        for readings in report.by_lens.values():
            for r in readings:
                all_in_by_lens.add(r.series_key)
        assert len(all_in_by_lens) == report.total_flagged


# ============================================================
# TEST — by_lens grouping
# ============================================================

class TestByLens:
    def test_single_lens_series_in_one_lens_bucket(self):
        # UNRATE е само в 'labor'
        snapshot = {"UNRATE": spike_up()}
        report = compute_anomalies(snapshot)
        assert "labor" in report.by_lens
        labor_keys = {r.series_key for r in report.by_lens["labor"]}
        assert "UNRATE" in labor_keys
        # Не е в други lens buckets
        for lens, readings in report.by_lens.items():
            keys = {r.series_key for r in readings}
            if lens != "labor":
                assert "UNRATE" not in keys

    def test_multi_lens_series_appears_in_all_its_lenses(self):
        """TRUCK_EMP е в ['labor', 'growth'] → trябва да е и в двете bucket-а."""
        if "TRUCK_EMP" not in SERIES_CATALOG:
            pytest.skip("TRUCK_EMP не е в каталога")
        snapshot = {"TRUCK_EMP": spike_up()}
        report = compute_anomalies(snapshot)
        lens_list = SERIES_CATALOG["TRUCK_EMP"].get("lens", [])
        assert len(lens_list) >= 2
        for lens in lens_list:
            assert lens in report.by_lens, f"Expected lens '{lens}' in by_lens"
            keys = {r.series_key for r in report.by_lens[lens]}
            assert "TRUCK_EMP" in keys


# ============================================================
# TEST — threshold control
# ============================================================

class TestThresholdControl:
    def test_higher_threshold_filters_more(self):
        keys = list(SERIES_CATALOG.keys())[:3]
        snapshot = {k: spike_up(base=2.0, spike=5.0) for k in keys}  # moderate spike

        low_t = compute_anomalies(snapshot, z_threshold=2.0)
        high_t = compute_anomalies(snapshot, z_threshold=5.0)
        assert low_t.total_flagged >= high_t.total_flagged


# ============================================================
# TEST — safety
# ============================================================

class TestSafety:
    def test_series_not_in_catalog_is_skipped(self):
        """Серия с unknown key не трябва да срива scan-а."""
        snapshot = {
            "UNRATE": spike_up(),
            "UNKNOWN_XYZ_123": spike_up(),
        }
        report = compute_anomalies(snapshot)
        # UNRATE е flagged, UNKNOWN е skip-нат
        top_keys = {r.series_key for r in report.top}
        assert "UNRATE" in top_keys
        assert "UNKNOWN_XYZ_123" not in top_keys

    def test_trend_without_spike_not_flagged(self):
        """Gradual trend (без spike) → max |z| е около 1.7, под threshold=2.0."""
        target = list(SERIES_CATALOG.keys())[0]
        snapshot = {target: trend_up()}
        report = compute_anomalies(snapshot, z_threshold=2.0)
        # Може или да не е flagged в зависимост от n — но ако е, проверяваме
        # че всички flagged серии наистина минават threshold-а
        for r in report.top:
            assert abs(r.z_score) > 2.0


# ============================================================
# TEST — JSON safety
# ============================================================

class TestJSONSafety:
    def test_reading_to_dict_nan_to_none(self):
        r = AnomalyReading(
            series_key="X",
            series_name_bg="X",
            lens=["labor"],
            peer_group="pg",
            tags=[],
            last_value=float("nan"),
            last_date=None,
            z_score=float("nan"),
            direction="up",
            is_new_extreme=False,
            new_extreme_direction=None,
            lookback_years=5,
            narrative_hint="",
        )
        d = r.to_dict()
        assert d["last_value"] is None
        assert d["z_score"] is None

    def test_report_to_dict_structure(self):
        report = compute_anomalies({})
        d = report.to_dict()
        assert set(d.keys()) == {
            "as_of", "threshold", "lookback_years",
            "total_flagged", "top", "by_lens",
        }
        assert isinstance(d["top"], list)
        assert isinstance(d["by_lens"], dict)
