"""
tests/test_executive.py
=======================
Unit тестове за analysis/executive.py.

Проверяваме:
  Regime класификация — всичките 8 лейбъла от различни state комбинации
  Lens rows builder — aggregate direction и breadth агрегация
  Supporting signals — top anomaly, NEW-5Y count, HIGH non-consensus
  Narrative — opening sentence per regime, counter-signals
  JSON safety (to_dict)
  Fallback при insufficient data
"""
from __future__ import annotations

import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from analysis.executive import (  # noqa: E402
    compute_executive_summary,
    RegimeSnapshot,
    LensRegimeRow,
    REGIME_LABELS,
    REGIME_LABELS_BG,
    _classify_regime,
    _aggregate_direction,
    _most_diagnostic_lens,
    _build_lens_rows,
    _extract_supporting_signals,
)
from analysis.breadth import LensBreadthReport, PeerGroupBreadth
from analysis.divergence import CrossLensPairReading, CrossLensDivergenceReport
from analysis.anomaly import AnomalyReport, AnomalyReading
from analysis.non_consensus import NonConsensusReport, NonConsensusReading


# ============================================================
# FIXTURE HELPERS
# ============================================================

def make_cross_report(states: dict[str, str]) -> CrossLensDivergenceReport:
    """Build минимален CrossLensDivergenceReport от {pair_id: state} map."""
    pairs = []
    for pid, state in states.items():
        pairs.append(CrossLensPairReading(
            pair_id=pid,
            name_bg=f"Pair {pid}",
            question_bg="test?",
            slot_a_label="A",
            slot_b_label="B",
            breadth_a=0.7 if "up" in state else 0.3,
            breadth_b=0.7 if state in ("both_up", "a_down_b_up") else 0.3,
            n_a_available=3,
            n_b_available=3,
            state=state,
            interpretation="test",
        ))
    return CrossLensDivergenceReport(as_of="2026-04-18", pairs=pairs)


def make_pg(name: str, direction: str, breadth: float, n_avail: int = 3) -> PeerGroupBreadth:
    return PeerGroupBreadth(
        name=name,
        n_members=n_avail,
        n_available=n_avail,
        breadth_positive=breadth,
        breadth_extreme=0.0,
        direction=direction,
        extreme_members=[],
        missing_members=[],
    )


def make_lens_report(lens: str, peer_groups: list[PeerGroupBreadth]) -> LensBreadthReport:
    return LensBreadthReport(lens=lens, as_of="2026-04-18", peer_groups=peer_groups)


def make_lens_reports(breadth_by_lens: dict) -> dict:
    """breadth_by_lens: {lens: [(pg_name, direction, breadth), ...]}."""
    out = {}
    for lens, specs in breadth_by_lens.items():
        pgs = [make_pg(n, d, b) for n, d, b in specs]
        out[lens] = make_lens_report(lens, pgs)
    return out


def make_anomaly_report(
    top_specs: list[tuple] = None,
    by_lens_specs: dict = None,
) -> AnomalyReport:
    """top_specs: list of (key, z, is_new_extreme, lens_list).
       by_lens_specs: {lens: [AnomalyReading, ...]}.
    """
    top = []
    if top_specs:
        for key, z, ne, lenses in top_specs:
            top.append(AnomalyReading(
                series_key=key,
                series_name_bg=key,
                lens=lenses,
                peer_group="test",
                tags=[],
                last_value=1.0,
                last_date="2026-04-18",
                z_score=z,
                direction="up" if z > 0 else "down",
                is_new_extreme=ne,
                new_extreme_direction="max" if ne and z > 0 else ("min" if ne else None),
                lookback_years=5,
                narrative_hint="",
            ))
    by_lens = by_lens_specs or {}
    return AnomalyReport(
        as_of="2026-04-18",
        threshold=2.0,
        lookback_years=5,
        total_flagged=len(top),
        top=top,
        by_lens=by_lens,
    )


def make_nc_report(high_keys: list[str] = None) -> NonConsensusReport:
    highlights = []
    if high_keys:
        for k in high_keys:
            highlights.append(NonConsensusReading(
                series_key=k,
                series_name_bg=k,
                lens=["labor"],
                peer_group="test",
                tags=["non_consensus"],
                last_value=1.0,
                last_date="2026-04-18",
                z_score=2.5,
                momentum_1m=0.1,
                peer_breadth=0.5,
                peer_direction="up",
                deviates_from_peers=True,
                signal_strength="high",
                narrative_hint="",
            ))
    return NonConsensusReport(as_of="2026-04-18", by_tag={}, highlights=highlights)


# ============================================================
# TESTS — REGIME CLASSIFICATION
# ============================================================

def test_regime_stagflation_confirmed():
    regime, driver = _classify_regime({"stagflation_test": "both_up"})
    assert regime == "stagflation_confirmed"
    assert driver == "stagflation_test"


def test_regime_soft_landing():
    regime, driver = _classify_regime({"stagflation_test": "a_up_b_down"})
    assert regime == "soft_landing"
    assert driver == "stagflation_test"


def test_regime_disinflation_cooling():
    regime, driver = _classify_regime({"stagflation_test": "both_down"})
    assert regime == "disinflation_cooling"


def test_regime_policy_dilemma():
    regime, _ = _classify_regime({"stagflation_test": "a_down_b_up"})
    assert regime == "policy_dilemma"


def test_regime_credit_stress_override():
    # stag е transition, но credit е a_up_b_down (credit stress)
    regime, driver = _classify_regime({
        "stagflation_test": "transition",
        "credit_policy_transmission": "a_up_b_down",
    })
    assert regime == "credit_stress"
    assert driver == "credit_policy_transmission"


def test_regime_expansion_via_growth_labor():
    regime, driver = _classify_regime({
        "stagflation_test": "transition",
        "growth_labor_lead_lag": "both_up",
    })
    assert regime == "expansion"
    assert driver == "growth_labor_lead_lag"


def test_regime_slowdown_via_growth_labor():
    regime, _ = _classify_regime({
        "stagflation_test": "transition",
        "growth_labor_lead_lag": "both_down",
    })
    assert regime == "slowdown"


def test_regime_transition_fallback():
    regime, driver = _classify_regime({})
    assert regime == "transition"
    assert driver == "none"


def test_regime_credit_stress_does_not_override_stagflation():
    # Ако stag е decisive, credit stress не override-ва
    regime, _ = _classify_regime({
        "stagflation_test": "both_up",
        "credit_policy_transmission": "a_up_b_down",
    })
    assert regime == "stagflation_confirmed"


# ============================================================
# TESTS — DIRECTION AGGREGATION
# ============================================================

def test_aggregate_direction_majority_expanding():
    assert _aggregate_direction(["expanding", "expanding", "mixed"]) == "expanding"


def test_aggregate_direction_majority_contracting():
    assert _aggregate_direction(["contracting", "contracting", "mixed"]) == "contracting"


def test_aggregate_direction_tie_is_mixed():
    # 1 expanding, 1 contracting — нито едното не е >50%
    assert _aggregate_direction(["expanding", "contracting"]) == "mixed"


def test_aggregate_direction_empty_is_insufficient():
    assert _aggregate_direction([]) == "insufficient_data"


# ============================================================
# TESTS — LENS ROWS
# ============================================================

def test_lens_rows_basic_aggregation():
    lens_reports = make_lens_reports({
        "labor": [("wage_dynamics", "expanding", 0.8), ("claims", "contracting", 0.3)],
        "growth": [("hard_activity", "expanding", 0.7)],
        "inflation": [("headline_measures", "expanding", 0.9)],
        "liquidity": [("credit_spreads", "mixed", 0.5)],
    })
    anom = make_anomaly_report(by_lens_specs={
        "labor": [AnomalyReading(
            series_key="UNRATE", series_name_bg="UNRATE", lens=["labor"],
            peer_group="test", tags=[], last_value=1.0, last_date="2026-04-18",
            z_score=2.5, direction="up", is_new_extreme=True,
            new_extreme_direction="max", lookback_years=5, narrative_hint="",
        )]
    })

    rows = _build_lens_rows(lens_reports, anom)
    assert len(rows) == 4
    labor_row = next(r for r in rows if r.lens == "labor")
    assert labor_row.anomaly_count == 1
    assert labor_row.new_extreme_count == 1
    # breadth agg = mean(0.8, 0.3) = 0.55
    assert abs(labor_row.breadth_agg - 0.55) < 0.01
    # 1 expanding + 1 contracting → mixed
    assert labor_row.direction == "mixed"


def test_lens_rows_handles_missing_lens():
    lens_reports = make_lens_reports({
        "labor": [("wage_dynamics", "expanding", 0.8)],
    })
    # growth/inflation/liquidity са липсващи
    anom = make_anomaly_report()
    rows = _build_lens_rows(lens_reports, anom)
    # Все още 4 реда, но 3 от тях са insufficient_data
    assert len(rows) == 4
    non_labor = [r for r in rows if r.lens != "labor"]
    assert all(r.direction == "insufficient_data" for r in non_labor)


# ============================================================
# TESTS — SUPPORTING SIGNALS
# ============================================================

def test_supporting_signals_top_anomaly():
    anom = make_anomaly_report(top_specs=[
        ("M2", 3.5, True, ["liquidity"]),
    ])
    nc = make_nc_report()
    cross = make_cross_report({"stagflation_test": "transition"})

    signals = _extract_supporting_signals(anom, nc, cross)
    assert any("M2" in s and "NEW" in s for s in signals)


def test_supporting_signals_high_nc():
    anom = make_anomaly_report()
    nc = make_nc_report(high_keys=["TEMPHELPS", "USINFO"])
    cross = make_cross_report({})

    signals = _extract_supporting_signals(anom, nc, cross)
    assert any("HIGH non-consensus" in s for s in signals)
    assert any("TEMPHELPS" in s for s in signals)


def test_supporting_signals_active_pairs():
    anom = make_anomaly_report()
    nc = make_nc_report()
    cross = make_cross_report({
        "stagflation_test": "both_up",
        "inflation_anchoring": "a_up_b_down",  # anchored
        "credit_policy_transmission": "transition",  # neutral
    })
    signals = _extract_supporting_signals(anom, nc, cross)
    # transition не се листва; both_up и a_up_b_down се листват
    active_line = next((s for s in signals if "Активни двойки" in s), None)
    assert active_line is not None
    assert "both_up" in active_line
    assert "transition" not in active_line


# ============================================================
# TESTS — MOST DIAGNOSTIC LENS
# ============================================================

def test_most_diagnostic_picks_farthest_from_mid():
    rows = [
        LensRegimeRow(lens="labor", direction="expanding", breadth_agg=0.55,
                      n_peer_groups=2, anomaly_count=0, new_extreme_count=0),
        LensRegimeRow(lens="inflation", direction="expanding", breadth_agg=0.9,
                      n_peer_groups=3, anomaly_count=5, new_extreme_count=1),
        LensRegimeRow(lens="growth", direction="mixed", breadth_agg=0.5,
                      n_peer_groups=1, anomaly_count=0, new_extreme_count=0),
    ]
    diagnostic = _most_diagnostic_lens(rows)
    assert diagnostic is not None
    assert diagnostic.lens == "inflation"  # 0.9 е най-отклонена от 0.5


def test_most_diagnostic_returns_none_when_all_nan():
    rows = [
        LensRegimeRow(lens="labor", direction="insufficient_data", breadth_agg=float("nan"),
                      n_peer_groups=0, anomaly_count=0, new_extreme_count=0),
    ]
    assert _most_diagnostic_lens(rows) is None


# ============================================================
# TESTS — FULL SUMMARY
# ============================================================

def test_compute_executive_summary_stagflation_scenario():
    """End-to-end: stagflation confirmed → regime + narrative."""
    cross = make_cross_report({
        "stagflation_test": "both_up",
        "inflation_anchoring": "a_up_b_down",  # anchored
        "growth_labor_lead_lag": "transition",
        "credit_policy_transmission": "transition",
        "sentiment_vs_hard_data": "transition",
    })
    lens_reports = make_lens_reports({
        "labor": [("wage_dynamics", "expanding", 0.85), ("unemployment", "expanding", 0.7)],
        "growth": [("hard_activity", "mixed", 0.55)],
        "inflation": [("headline_measures", "expanding", 0.9), ("core_measures", "expanding", 0.85)],
        "liquidity": [("policy_rates", "mixed", 0.5)],
    })
    anom = make_anomaly_report(
        top_specs=[("CPI_SHELTER", 3.2, False, ["inflation"])],
        by_lens_specs={"inflation": []},  # keep simple
    )
    nc = make_nc_report()

    snap = compute_executive_summary(cross, lens_reports, anom, nc)

    assert snap.regime_label == "stagflation_confirmed"
    assert snap.regime_label_bg == "Стагфлация (потвърдена)"
    assert snap.primary_driver == "stagflation_test"
    assert "стагфлационна" in snap.narrative_bg.lower()
    # Anchored counter-signal should appear
    assert "anchored" in snap.narrative_bg.lower() or "narrative" in snap.narrative_bg.lower()
    # Lens rows — all 4 present
    assert len(snap.lens_rows) == 4


def test_compute_executive_summary_soft_landing_with_credit_warning():
    cross = make_cross_report({
        "stagflation_test": "a_up_b_down",
        "credit_policy_transmission": "a_up_b_down",  # credit stress counter-signal
    })
    lens_reports = make_lens_reports({
        "labor": [("wage_dynamics", "expanding", 0.8)],
        "growth": [("hard_activity", "expanding", 0.6)],
        "inflation": [("headline_measures", "contracting", 0.2)],
        "liquidity": [("credit_spreads", "expanding", 0.75)],
    })
    anom = make_anomaly_report()
    nc = make_nc_report()

    snap = compute_executive_summary(cross, lens_reports, anom, nc)
    assert snap.regime_label == "soft_landing"
    assert "credit" in snap.narrative_bg.lower()  # counter-signal surfaced


def test_compute_executive_summary_to_dict_json_safe():
    cross = make_cross_report({"stagflation_test": "transition"})
    lens_reports = make_lens_reports({
        "labor": [],  # empty → insufficient
    })
    anom = make_anomaly_report()
    nc = make_nc_report()

    snap = compute_executive_summary(cross, lens_reports, anom, nc)
    d = snap.to_dict()
    # Всички float(NaN) трябва да са None
    import json
    json.dumps(d)  # не хвърля
    for row in d["lens_rows"]:
        if row["breadth_agg"] is not None:
            assert isinstance(row["breadth_agg"], (int, float))


def test_compute_executive_summary_transition_when_no_signals():
    cross = make_cross_report({})
    lens_reports = {}
    anom = make_anomaly_report()
    nc = make_nc_report()

    snap = compute_executive_summary(cross, lens_reports, anom, nc)
    assert snap.regime_label == "transition"


def test_regime_labels_taxonomy_is_complete():
    """Всеки REGIME_LABEL има BG label и CSS class."""
    from analysis.executive import REGIME_CSS_CLASS
    for r in REGIME_LABELS:
        assert r in REGIME_LABELS_BG
        assert r in REGIME_CSS_CLASS
