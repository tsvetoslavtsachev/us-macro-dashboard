"""
tests/test_divergence_transform_aware.py
=========================================
Verify gate за REVIEW-03 т.0.1 (P3-fix-B): режимният вход (cross-lens breadth)
се смята върху КАТАЛОЖНИЯ transform, не върху суровото ниво.

Гейт критерият от мандата: „CPI индекс расте с +0.1% MoM при спадащ YoY →
slot_b НЕ е up". Плюс: level серии = identity (нищо не се променя за тях),
и shadow полетата (legacy raw) присъстват за base-first сверката.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from analysis.divergence import (  # noqa: E402
    compute_cross_lens_divergence,
    _aggregate_slot_breadth,
    _transform_slot_series,
)
from catalog.series import series_by_lens, SERIES_CATALOG  # noqa: E402
from catalog.cross_lens_pairs import CROSS_LENS_PAIRS  # noqa: E402


def monthly(values: list[float], end: str = "2026-03-01") -> pd.Series:
    idx = pd.date_range(end=end, periods=len(values), freq="MS")
    return pd.Series(values, index=idx)


def rising_index_cooling_rate(n: int = 60, base: float = 100.0) -> pd.Series:
    """Индекс, който расте всеки месец (вкл. +0.1% последния), но YoY ПАДА."""
    rates = np.linspace(0.02, 0.001, n)  # месечен темп 2.0% → 0.1%
    vals = base * np.cumprod(1 + rates)
    return monthly(list(vals))


def trend_down(n: int = 60) -> pd.Series:
    return monthly(list(np.linspace(5.0, 2.0, n)))


def flat(n: int = 60, level: float = 3.0) -> pd.Series:
    return monthly([level + 0.01 * np.sin(i * 0.3) for i in range(n)])


def _stag_pair() -> dict:
    return next(p for p in CROSS_LENS_PAIRS if p["id"] == "stagflation_test")


def _yoy_keys_in_slot(slot: dict) -> list[str]:
    keys = []
    for e in series_by_lens(slot["lens"]):
        if e.get("peer_group") in slot["peer_groups"]:
            if SERIES_CATALOG.get(e["_key"], {}).get("transform") == "yoy_pct":
                keys.append(e["_key"])
    return keys


class TestMandateGate:
    def test_rising_index_cooling_yoy_is_not_up(self):
        """ГЕЙТ (REVIEW-03 т.0.1): растящ индекс със спадащ YoY → slot_b НЕ е up.

        Legacy raw shadow за същите данни е "up" (1.0) — точно дефектът,
        който правеше stagflation_confirmed структурно привилегирован.
        """
        stag = _stag_pair()
        yoy_keys = _yoy_keys_in_slot(stag["slot_b"])
        assert yoy_keys, "slot_b на stagflation_test няма yoy_pct серии — сценарият е невалиден"

        snap: dict = {}
        for e in series_by_lens(stag["slot_b"]["lens"]):
            if e.get("peer_group") in stag["slot_b"]["peer_groups"]:
                snap[e["_key"]] = rising_index_cooling_rate()

        breadth_b, raw_b, _, _ = _aggregate_slot_breadth(stag["slot_b"], snap)

        assert breadth_b < 0.4, (
            f"Transform-aware breadth трябва да чете охлаждане (<0.4), получихме {breadth_b}"
        )
        assert raw_b == pytest.approx(1.0), (
            f"Суровият shadow трябва да покаже стария дефект (1.0), получихме {raw_b}"
        )

    def test_level_series_unchanged_by_transform(self):
        """level серии: transform-aware == raw (identity) — нищо не се променя за тях."""
        credit = next(p for p in CROSS_LENS_PAIRS if p["id"] == "credit_policy_transmission")
        # slot_a = credit_spreads (level), slot_b = policy_rates (level)
        for slot in (credit["slot_a"], credit["slot_b"]):
            keys = [
                e["_key"] for e in series_by_lens(slot["lens"])
                if e.get("peer_group") in slot["peer_groups"]
            ]
            transforms = {SERIES_CATALOG.get(k, {}).get("transform") for k in keys}
            if transforms != {"level"}:
                pytest.skip(f"slot вече не е чисто level: {transforms}")
            snap = {k: trend_down() for k in keys}
            bp, bp_raw, _, _ = _aggregate_slot_breadth(slot, snap)
            assert bp == pytest.approx(bp_raw), (
                f"level slot: TA={bp} != raw={bp_raw} — identity нарушен"
            )

    def test_transform_helper_respects_catalog(self):
        """_transform_slot_series: yoy_pct серия става темп; level остава ниво."""
        yoy_key = next(
            (k for k, m in SERIES_CATALOG.items() if m.get("transform") == "yoy_pct"),
            None,
        )
        level_key = next(
            (k for k, m in SERIES_CATALOG.items() if m.get("transform") == "level"),
            None,
        )
        assert yoy_key and level_key

        idx_series = rising_index_cooling_rate()
        out = _transform_slot_series({yoy_key: idx_series, level_key: idx_series})

        # yoy_pct: последната стойност е ТЕМП (~1.2-2.5%), не ниво (~180)
        assert out[yoy_key].iloc[-1] < 30, "yoy_pct серията не е трансформирана в темп"
        # level: identity
        assert out[level_key].iloc[-1] == pytest.approx(float(idx_series.iloc[-1]))

    def test_shadow_fields_flow_to_report(self):
        """state_raw/breadth_*_raw присъстват в pair reading (base-first сверка)."""
        report = compute_cross_lens_divergence(snapshot={})
        for p in report.pairs:
            d = p.to_dict()
            assert "state_raw" in d
            assert "breadth_a_raw" in d
            assert "breadth_b_raw" in d
