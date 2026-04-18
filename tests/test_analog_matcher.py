"""
tests/test_analog_matcher.py
============================
Тестове за cosine-based analog matcher.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from analysis.analog_matcher import (  # noqa: E402
    AnalogResult,
    HISTORICAL_EPISODES,
    STRENGTH_LABELS_BG,
    _cosine,
    _cosine_vs_matrix,
    _greedy_topk,
    classify_strength,
    find_analogs,
    lookup_episode,
)


# ============================================================
# COSINE PRIMITIVES
# ============================================================

class TestCosine:

    def test_identical_vectors_give_one(self):
        a = np.array([1.0, 2.0, 3.0])
        assert _cosine(a, a) == pytest.approx(1.0)

    def test_opposite_vectors_give_minus_one(self):
        a = np.array([1.0, 2.0, 3.0])
        assert _cosine(a, -a) == pytest.approx(-1.0)

    def test_orthogonal_vectors_give_zero(self):
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        assert _cosine(a, b) == pytest.approx(0.0)

    def test_zero_vector_returns_zero(self):
        a = np.array([0.0, 0.0, 0.0])
        b = np.array([1.0, 1.0, 1.0])
        assert _cosine(a, b) == 0.0
        assert _cosine(b, a) == 0.0

    def test_matrix_version_matches_loop(self):
        np.random.seed(0)
        cur = np.random.normal(0, 1, 8)
        mat = np.random.normal(0, 1, (50, 8))
        vec = _cosine_vs_matrix(cur, mat)
        loop = np.array([_cosine(cur, mat[i]) for i in range(50)])
        assert np.allclose(vec, loop)


# ============================================================
# HISTORICAL EPISODES
# ============================================================

class TestLookupEpisode:

    def test_known_gfc_month_labelled(self):
        label = lookup_episode(pd.Timestamp("2008-11-30"))
        assert label is not None
        assert "GFC" in label or "Recession" in label

    def test_known_volcker_labelled(self):
        label = lookup_episode(pd.Timestamp("1981-06-30"))
        assert label is not None
        assert "Volcker" in label

    def test_known_covid_labelled(self):
        label = lookup_episode(pd.Timestamp("2020-03-31"))
        assert label is not None
        assert "COVID" in label

    def test_date_outside_any_episode_returns_none(self):
        # 2024-12 не попада в нито един знaen episode (current regime)
        assert lookup_episode(pd.Timestamp("2024-12-31")) is None

    def test_all_episodes_have_valid_dates(self):
        for ep in HISTORICAL_EPISODES:
            s = pd.Timestamp(ep["start"])
            e = pd.Timestamp(ep["end"])
            assert s <= e, f"episode {ep['label']} has start > end"


# ============================================================
# GREEDY TOP-K
# ============================================================

class TestGreedyTopK:

    def test_picks_top_with_gap(self):
        idx = pd.date_range("2000-01-31", periods=24, freq="ME")
        sims = pd.Series(
            [0.1, 0.2, 0.9, 0.85, 0.3, 0.4, 0.5, 0.55, 0.6,
             0.95, 0.2, 0.2, 0.3, 0.4, 0.5, 0.5, 0.5, 0.5,
             0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
            index=idx,
        )
        # Top-2 с min_gap=3: 0.95 (месец 10), след това не 0.9/0.85 (в gap),
        # а следващата над тях вън от gap window-а
        picks = _greedy_topk(sims, k=2, min_gap_months=3)
        assert len(picks) == 2
        # Първият ред е 0.95 в месец 10 (idx[9])
        assert picks[0][0] == idx[9]
        assert picks[0][1] == pytest.approx(0.95)
        # Вторият — извън ±3 месеца от месец 10 → NOT idx 7,8,9,10,11,12,13
        second_date = picks[1][0]
        assert abs((second_date - idx[9]).days) >= 90  # ≥3 месеца

    def test_k_larger_than_pool_returns_all(self):
        idx = pd.date_range("2020-01-31", periods=3, freq="ME")
        sims = pd.Series([0.5, 0.6, 0.7], index=idx)
        picks = _greedy_topk(sims, k=10, min_gap_months=0)
        assert len(picks) == 3

    def test_min_gap_zero_picks_topk_strictly(self):
        idx = pd.date_range("2020-01-31", periods=5, freq="ME")
        sims = pd.Series([0.1, 0.9, 0.8, 0.7, 0.6], index=idx)
        picks = _greedy_topk(sims, k=3, min_gap_months=0)
        dates = [p[0] for p in picks]
        sims_out = [p[1] for p in picks]
        # Десцендент ред
        assert sims_out == sorted(sims_out, reverse=True)
        assert len(dates) == 3

    def test_empty_input_returns_empty_list(self):
        empty = pd.Series(dtype=float)
        assert _greedy_topk(empty, k=5, min_gap_months=12) == []


# ============================================================
# FIND ANALOGS — END-TO-END
# ============================================================

def _build_synthetic_history(n_months: int = 600):
    """Synthetic 8-dim history за analog search тестване."""
    idx = pd.date_range("1976-01-31", periods=n_months, freq="ME")
    dims = ["unrate", "core_cpi_yoy", "real_ffr", "yc_10y2y",
            "hy_oas", "ip_yoy", "breakeven", "sahm"]
    np.random.seed(13)
    raw = pd.DataFrame(
        np.random.normal(0, 1, size=(n_months, 8)),
        index=idx, columns=dims,
    )
    # z-scored = raw (since mean 0, std 1)
    z = raw.copy()
    # z-score ръчно за да е стриктно коректен
    z = (z - z.mean()) / z.std(ddof=0)
    return raw, z


class TestFindAnalogs:

    def test_returns_k_results_by_default(self):
        raw, z = _build_synthetic_history()
        current = np.array([1.0, -1.0, 0.5, 0.5, 0.0, 0.0, 0.0, 0.0])
        today = raw.index[-1]
        results = find_analogs(raw, z, current, today, k=5)
        assert len(results) == 5

    def test_results_sorted_by_similarity_desc(self):
        raw, z = _build_synthetic_history()
        current = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
        today = raw.index[-1]
        results = find_analogs(raw, z, current, today, k=3)
        sims = [r.similarity for r in results]
        assert sims == sorted(sims, reverse=True)
        # ранк
        assert [r.rank for r in results] == [1, 2, 3]

    def test_exclude_last_months_removes_recent_dates(self):
        raw, z = _build_synthetic_history()
        current = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0])
        today = raw.index[-1]
        results = find_analogs(raw, z, current, today, k=5, exclude_last_months=24)
        # нито един analog да не е по-късно от today − 24 месеца
        cutoff = today - pd.DateOffset(months=24)
        for r in results:
            assert r.date <= cutoff, f"{r.date} > {cutoff}"

    def test_min_gap_enforces_spacing(self):
        raw, z = _build_synthetic_history()
        current = np.array([0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5])
        today = raw.index[-1]
        results = find_analogs(raw, z, current, today, k=5, min_gap_months=24)
        dates = sorted([r.date for r in results])
        for i in range(1, len(dates)):
            delta_months = (dates[i].year - dates[i-1].year) * 12 + (dates[i].month - dates[i-1].month)
            assert delta_months >= 24, f"gap between {dates[i-1]} and {dates[i]} too small"

    def test_synthetic_self_match_excluded(self):
        """Ако current = последния ред на history, той ТРЯБВА да е excluded."""
        raw, z = _build_synthetic_history()
        today = raw.index[-1]
        # current = последния complete ред
        current = z.iloc[-1].values
        results = find_analogs(raw, z, current, today, k=3, exclude_last_months=24)
        for r in results:
            assert r.date != today

    def test_empty_history_returns_empty(self):
        raw = pd.DataFrame()
        z = pd.DataFrame()
        current = np.array([0, 0, 0, 0, 0, 0, 0, 0], dtype=float)
        results = find_analogs(raw, z, current, pd.Timestamp("2026-01-31"), k=5)
        assert results == []

    def test_results_contain_raw_and_z_and_label(self):
        raw, z = _build_synthetic_history()
        current = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
        today = raw.index[-1]
        results = find_analogs(raw, z, current, today, k=3)
        for r in results:
            assert isinstance(r, AnalogResult)
            assert set(r.raw.keys()) == set(raw.columns)
            assert set(r.z.keys()) == set(z.columns)
            # episode_label е или string, или None
            assert r.episode_label is None or isinstance(r.episode_label, str)


# ============================================================
# STRENGTH CLASSIFICATION
# ============================================================

class TestClassifyStrength:

    def test_boundaries(self):
        assert classify_strength(0.95) == "strong"
        assert classify_strength(0.80) == "good"
        assert classify_strength(0.60) == "weak"
        assert classify_strength(0.40) == "marginal"

    def test_edge_cases(self):
        # Точно на границата — стриктно >
        assert classify_strength(0.90) == "good"   # не "strong"
        assert classify_strength(0.70) == "weak"   # не "good"
        assert classify_strength(0.50) == "marginal"

    def test_all_categories_have_bg_label(self):
        for cat in ["strong", "good", "weak", "marginal"]:
            assert cat in STRENGTH_LABELS_BG
            assert STRENGTH_LABELS_BG[cat]
