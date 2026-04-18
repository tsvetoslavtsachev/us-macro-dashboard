"""
tests/test_analysis_divergence.py
==================================
Unit тестове за analysis/divergence.py и catalog/cross_lens_pairs.py.

Тестваме:
  Config validation (cross_lens_pairs.py)
  Intra-lens: notable divergence detection, sorting, empty case
  Cross-lens: state classification (all 5 states), invert logic, insufficient data
  JSON safety (to_dict)
"""
from __future__ import annotations

import sys
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from analysis.divergence import (  # noqa: E402
    compute_intra_lens_divergence,
    compute_cross_lens_divergence,
    IntraLensDivergence,
    IntraLensDivergenceReport,
    CrossLensPairReading,
    CrossLensDivergenceReport,
    _classify_state,
    _aggregate_slot_breadth,
    BREADTH_HIGH,
    BREADTH_LOW,
    INTRA_NOTABLE_DIFF,
)
from catalog.series import series_by_lens  # noqa: E402
from catalog.cross_lens_pairs import (  # noqa: E402
    CROSS_LENS_PAIRS,
    validate_pairs,
    REQUIRED_INTERPRETATION_STATES,
)


# ============================================================
# HELPERS
# ============================================================

def monthly(values: list[float], end: str = "2026-03-01") -> pd.Series:
    idx = pd.date_range(end=end, periods=len(values), freq="MS")
    return pd.Series(values, index=idx)


def trend_up(n: int = 60) -> pd.Series:
    return monthly(list(np.linspace(2.0, 5.0, n)))


def trend_down(n: int = 60) -> pd.Series:
    return monthly(list(np.linspace(5.0, 2.0, n)))


def flat(n: int = 60, level: float = 3.0) -> pd.Series:
    vals = [level + 0.01 * np.sin(i * 0.3) for i in range(n)]
    return monthly(vals)


def _lens_snapshot(lens: str, factory) -> dict[str, pd.Series]:
    return {e["_key"]: factory() for e in series_by_lens(lens)}


def _multi_lens_snapshot(factory_by_lens: dict) -> dict[str, pd.Series]:
    """factory_by_lens: {lens_name: callable} → snapshot за всички серии в тези lenses."""
    out: dict[str, pd.Series] = {}
    for lens, factory in factory_by_lens.items():
        for e in series_by_lens(lens):
            # Не презаписваме ако серията вече е там (multi-lens серии)
            if e["_key"] not in out:
                out[e["_key"]] = factory()
    return out


@pytest.fixture(autouse=True)
def _seed():
    np.random.seed(42)


# ============================================================
# TEST — cross_lens_pairs config validation
# ============================================================

class TestCrossLensPairsConfig:
    def test_all_pairs_pass_validation(self):
        errors = validate_pairs()
        assert errors == [], f"Config errors: {errors}"

    def test_pair_count_at_least_five(self):
        assert len(CROSS_LENS_PAIRS) >= 5

    def test_all_required_states_present(self):
        for pair in CROSS_LENS_PAIRS:
            states = set(pair["interpretations"].keys())
            missing = REQUIRED_INTERPRETATION_STATES - states
            assert not missing, f"{pair['id']}: missing interpretation states {missing}"

    def test_unique_pair_ids(self):
        ids = [p["id"] for p in CROSS_LENS_PAIRS]
        assert len(ids) == len(set(ids)), "Duplicate pair IDs in CROSS_LENS_PAIRS"


# ============================================================
# TEST — state classification
# ============================================================

class TestStateClassification:
    def test_both_up(self):
        assert _classify_state(0.9, 0.8) == "both_up"

    def test_both_down(self):
        assert _classify_state(0.1, 0.2) == "both_down"

    def test_a_up_b_down(self):
        assert _classify_state(0.9, 0.1) == "a_up_b_down"

    def test_a_down_b_up(self):
        assert _classify_state(0.1, 0.9) == "a_down_b_up"

    def test_transition_mixed(self):
        assert _classify_state(0.5, 0.5) == "transition"
        assert _classify_state(0.55, 0.65) == "transition"  # единият just > 0.6, другият не

    def test_insufficient_data(self):
        assert _classify_state(float("nan"), 0.5) == "insufficient_data"
        assert _classify_state(0.5, float("nan")) == "insufficient_data"


# ============================================================
# TEST — cross-lens divergence end-to-end
# ============================================================

class TestCrossLensDivergence:
    def test_all_up_gives_both_up_states(self):
        snapshot = _multi_lens_snapshot({
            "labor": trend_up,
            "growth": trend_up,
            "inflation": trend_up,
            "liquidity": trend_up,
        })
        report = compute_cross_lens_divergence(snapshot)
        # Всяка pair с нормално slot_a,slot_b и без invert ще даде both_up
        # invert променя равенствата — тестваме отделно
        # Но поне няколко pair-а трябва да са both_up когато no invert:
        non_invert_states = [
            p.state for p in report.pairs
            if _pair_has_no_invert(p.pair_id)
        ]
        assert "both_up" in non_invert_states

    def test_pair_report_has_interpretation(self):
        snapshot = _multi_lens_snapshot({
            "labor": trend_up,
            "growth": trend_up,
            "inflation": trend_up,
            "liquidity": trend_up,
        })
        report = compute_cross_lens_divergence(snapshot)
        for p in report.pairs:
            assert p.interpretation
            assert len(p.interpretation) > 5

    def test_empty_snapshot_all_insufficient(self):
        report = compute_cross_lens_divergence(snapshot={})
        for p in report.pairs:
            assert p.state == "insufficient_data"
            assert p.n_a_available == 0
            assert p.n_b_available == 0

    def test_invert_logic_unemployment(self):
        """Labor tightness slot има invert на unemployment.

        Ако unemployment серии trend DOWN (безработицата пада → labor tighter),
        breadth_positive на unemployment = 0.0. След invert → 1.0.
        Aggregate с wage_dynamics (also trend up) → очакваме slot_a около 1.0.
        """
        # Labor: unemployment trend down (tight), wage_dynamics trend up
        snap: dict = {}
        for e in series_by_lens("labor"):
            if e["peer_group"] == "unemployment":
                snap[e["_key"]] = trend_down()  # низка unemployment → labor tight
            elif e["peer_group"] == "wage_dynamics":
                snap[e["_key"]] = trend_up()    # wages растат
            else:
                snap[e["_key"]] = flat()

        # Inflation: trend up (hot)
        for e in series_by_lens("inflation"):
            if e["_key"] not in snap:
                snap[e["_key"]] = trend_up()

        # Намираме stagflation_test pair
        stag = next(p for p in CROSS_LENS_PAIRS if p["id"] == "stagflation_test")
        breadth_a, _, _ = _aggregate_slot_breadth(stag["slot_a"], snap)
        breadth_b, _, _ = _aggregate_slot_breadth(stag["slot_b"], snap)

        # slot_a: unemployment (invert) + wage_dynamics → и двете "up" след invert
        assert breadth_a == pytest.approx(1.0), (
            f"slot_a (labor tightness) очаквахме 1.0, получихме {breadth_a}"
        )
        # slot_b: inflation up → 1.0
        assert breadth_b == pytest.approx(1.0)

    def test_stagflation_interpretation_both_up(self):
        """Labor tight + inflation hot → state=both_up → stagflation interpretation."""
        snap: dict = {}
        # Labor tight: unemployment trend_down, wage_dynamics trend_up
        for e in series_by_lens("labor"):
            if e["peer_group"] == "unemployment":
                snap[e["_key"]] = trend_down()
            elif e["peer_group"] == "wage_dynamics":
                snap[e["_key"]] = trend_up()
            else:
                snap[e["_key"]] = flat()
        # Inflation hot
        for e in series_by_lens("inflation"):
            if e["_key"] not in snap:
                snap[e["_key"]] = trend_up()

        report = compute_cross_lens_divergence(snap)
        stag_reading = next(p for p in report.pairs if p.pair_id == "stagflation_test")
        assert stag_reading.state == "both_up"
        assert "тагфлация" in stag_reading.interpretation.lower() or \
               "stagflation" in stag_reading.interpretation.lower()

    def test_soft_landing_interpretation(self):
        """Labor tight, inflation cooling → state=a_up_b_down → soft landing."""
        snap: dict = {}
        for e in series_by_lens("labor"):
            if e["peer_group"] == "unemployment":
                snap[e["_key"]] = trend_down()  # tight
            elif e["peer_group"] == "wage_dynamics":
                snap[e["_key"]] = trend_up()
            else:
                snap[e["_key"]] = flat()
        for e in series_by_lens("inflation"):
            if e["_key"] not in snap:
                snap[e["_key"]] = trend_down()  # cooling

        report = compute_cross_lens_divergence(snap)
        stag = next(p for p in report.pairs if p.pair_id == "stagflation_test")
        assert stag.state == "a_up_b_down"
        assert "oft landing" in stag.interpretation


# ============================================================
# TEST — intra-lens divergence
# ============================================================

class TestIntraLensDivergence:
    def test_flat_snapshot_no_notable(self):
        """Всички peer_groups с breadth ≈ 0.5 → няма notable divergence."""
        # flat серия → momentum ≈ 0, повечето няма да са positive strict
        snap = _lens_snapshot("labor", flat)
        report = compute_intra_lens_divergence("labor", snap)
        # всички peer_groups имат similar breadth → малко или никакви divergences
        assert len(report.divergences) == 0 or \
               all(abs(d.diff) < INTRA_NOTABLE_DIFF + 0.01 for d in report.divergences)

    def test_notable_divergence_detected(self):
        """Една peer_group trend up, друга trend down → notable divergence."""
        snap: dict = {}
        for e in series_by_lens("labor"):
            if e["peer_group"] == "unemployment":
                snap[e["_key"]] = trend_up()
            elif e["peer_group"] == "claims":
                snap[e["_key"]] = trend_down()
            else:
                snap[e["_key"]] = flat()
        report = compute_intra_lens_divergence("labor", snap)

        names = {(d.group_a, d.group_b) for d in report.divergences}
        assert ("claims", "unemployment") in names or \
               ("unemployment", "claims") in names

    def test_divergences_sorted_by_abs_diff(self):
        snap: dict = {}
        for e in series_by_lens("inflation"):
            if e["peer_group"] == "expectations":
                snap[e["_key"]] = trend_down()  # breadth = 0
            elif e["peer_group"] == "headline_measures":
                snap[e["_key"]] = trend_up()    # breadth = 1
            elif e["peer_group"] == "core_measures":
                snap[e["_key"]] = flat()        # breadth ≈ 0
            else:
                snap[e["_key"]] = trend_up()
        report = compute_intra_lens_divergence("inflation", snap)

        if len(report.divergences) >= 2:
            for i in range(len(report.divergences) - 1):
                assert abs(report.divergences[i].diff) >= abs(report.divergences[i+1].diff)

    def test_invalid_lens_raises(self):
        with pytest.raises(ValueError, match="Unknown lens"):
            compute_intra_lens_divergence("not_a_lens", {})


# ============================================================
# TEST — JSON safety
# ============================================================

class TestJSONSafety:
    def test_cross_lens_report_to_dict_no_nan(self):
        report = compute_cross_lens_divergence(snapshot={})
        d = report.to_dict()
        assert "pairs" in d
        for p in d["pairs"]:
            assert p["breadth_a"] is None or isinstance(p["breadth_a"], (int, float))
            assert p["breadth_b"] is None or isinstance(p["breadth_b"], (int, float))

    def test_intra_report_to_dict_structure(self):
        report = compute_intra_lens_divergence("labor", _lens_snapshot("labor", trend_up))
        d = report.to_dict()
        assert set(d.keys()) == {"lens", "as_of", "divergences"}


# ============================================================
# Helpers
# ============================================================

def _pair_has_no_invert(pair_id: str) -> bool:
    pair = next(p for p in CROSS_LENS_PAIRS if p["id"] == pair_id)
    has_invert_a = any(pair["slot_a"].get("invert", {}).values())
    has_invert_b = any(pair["slot_b"].get("invert", {}).values())
    return not (has_invert_a or has_invert_b)
