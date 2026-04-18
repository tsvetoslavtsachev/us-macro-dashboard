"""
tests/test_delta.py
===================
Unit тестове за analysis/delta.py.

Проверяваме:
  build_state_snapshot — извлича правилни полета от reports
  compute_delta — detect regime change, cross-lens flips, breadth moves, NC deltas
  save_state / load_latest_state — JSON roundtrip + datebased filtering
  Edge cases: no previous, NaN breadth, empty reports
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from analysis.delta import (  # noqa: E402
    BriefingStateSnapshot,
    BriefingDelta,
    CrossLensStateChange,
    BreadthMove,
    build_state_snapshot,
    compute_delta,
    save_state,
    load_latest_state,
    BREADTH_MOVE_THRESHOLD_PP,
)
from analysis.executive import RegimeSnapshot, LensRegimeRow
from analysis.breadth import LensBreadthReport, PeerGroupBreadth
from analysis.divergence import CrossLensPairReading, CrossLensDivergenceReport
from analysis.anomaly import AnomalyReport, AnomalyReading
from analysis.non_consensus import NonConsensusReport, NonConsensusReading


# ============================================================
# FIXTURES
# ============================================================

def make_exec(regime="expansion", regime_bg="Разширяване", as_of="2026-04-18"):
    return RegimeSnapshot(
        as_of=as_of,
        regime_label=regime,
        regime_label_bg=regime_bg,
        regime_css_class="regime-exp",
        primary_driver="growth_labor_lead_lag",
        narrative_bg="test",
        lens_rows=[],
        supporting_signals=[],
    )


def make_cross(states):
    pairs = [
        CrossLensPairReading(
            pair_id=pid, name_bg=pid, question_bg="", slot_a_label="A", slot_b_label="B",
            breadth_a=0.5, breadth_b=0.5, n_a_available=1, n_b_available=1,
            state=st, interpretation="",
        )
        for pid, st in states.items()
    ]
    return CrossLensDivergenceReport(as_of="2026-04-18", pairs=pairs)


def make_lens_reports(specs):
    """specs: {lens: [(pg_name, breadth_positive), ...]}"""
    out = {}
    for lens, pg_specs in specs.items():
        pgs = [
            PeerGroupBreadth(
                name=n, n_members=3, n_available=3,
                breadth_positive=bp, breadth_extreme=0.0,
                direction="expanding" if bp > 0.5 else "contracting",
                extreme_members=[], missing_members=[],
            )
            for n, bp in pg_specs
        ]
        out[lens] = LensBreadthReport(lens=lens, as_of="2026-04-18", peer_groups=pgs)
    return out


def make_anomaly(top_specs):
    """top_specs: [(key, z, is_new_extreme), ...]"""
    top = []
    for key, z, ne in top_specs:
        top.append(AnomalyReading(
            series_key=key, series_name_bg=key, lens=["growth"], peer_group="test",
            tags=[], last_value=1.0, last_date="2026-04-18", z_score=z,
            direction="up" if z > 0 else "down",
            is_new_extreme=ne, new_extreme_direction="max" if ne else None,
            lookback_years=5, narrative_hint="",
        ))
    return AnomalyReport(
        as_of="2026-04-18", threshold=2.0, lookback_years=5,
        total_flagged=len(top), top=top, by_lens={},
    )


def make_nc(high_keys):
    highlights = [
        NonConsensusReading(
            series_key=k, series_name_bg=k, lens=["labor"], peer_group="test",
            tags=[], last_value=1.0, last_date="2026-04-18", z_score=3.0,
            momentum_1m=0.1, peer_breadth=0.5, peer_direction="up",
            deviates_from_peers=True, signal_strength="high", narrative_hint="",
        )
        for k in high_keys
    ]
    return NonConsensusReport(as_of="2026-04-18", by_tag={}, highlights=highlights)


# ============================================================
# TESTS — build_state_snapshot
# ============================================================

def test_build_state_snapshot_captures_regime_and_states():
    exec_snap = make_exec("stagflation_confirmed", "Стагфлация")
    cross = make_cross({"stagflation_test": "both_up", "sentiment_vs_hard_data": "transition"})
    lens_reports = make_lens_reports({"labor": [("wage_dynamics", 0.8)]})
    anom = make_anomaly([("CPI", 3.5, True), ("M2", 2.8, False)])
    nc = make_nc(["TEMPHELPS"])

    snap = build_state_snapshot(exec_snap, cross, lens_reports, anom, nc,
                                generated_on=date(2026, 4, 18))
    assert snap.regime_label == "stagflation_confirmed"
    assert snap.generated_on == "2026-04-18"
    assert snap.cross_lens_states == {
        "stagflation_test": "both_up",
        "sentiment_vs_hard_data": "transition",
    }
    assert snap.breadth_by_pg == {"labor/wage_dynamics": 0.8}
    assert snap.high_nc_keys == ["TEMPHELPS"]
    assert snap.top_anomaly_keys == ["CPI", "M2"]
    assert snap.new_extreme_keys == ["CPI"]


def test_build_state_snapshot_nan_breadth_becomes_none():
    exec_snap = make_exec()
    cross = make_cross({})
    lens_reports = make_lens_reports({"labor": [("claims", float("nan"))]})
    anom = make_anomaly([])
    nc = make_nc([])

    snap = build_state_snapshot(exec_snap, cross, lens_reports, anom, nc,
                                generated_on=date(2026, 4, 18))
    assert snap.breadth_by_pg == {"labor/claims": None}


# ============================================================
# TESTS — compute_delta
# ============================================================

def test_compute_delta_no_previous_returns_empty():
    curr = BriefingStateSnapshot(
        as_of="2026-04-18", generated_on="2026-04-18",
        regime_label="expansion", regime_label_bg="Разширяване",
    )
    delta = compute_delta(curr, None)
    assert not delta.has_content
    assert delta.prev_generated_on is None
    assert delta.curr_generated_on == "2026-04-18"


def test_compute_delta_detects_regime_change():
    prev = BriefingStateSnapshot(
        as_of="2026-04-11", generated_on="2026-04-11",
        regime_label="expansion", regime_label_bg="Разширяване",
    )
    curr = BriefingStateSnapshot(
        as_of="2026-04-18", generated_on="2026-04-18",
        regime_label="stagflation_confirmed", regime_label_bg="Стагфлация",
    )
    delta = compute_delta(curr, prev)
    assert delta.regime_change == ("Разширяване", "Стагфлация")
    assert delta.has_content


def test_compute_delta_detects_cross_lens_flips():
    prev = BriefingStateSnapshot(
        as_of="2026-04-11", generated_on="2026-04-11",
        regime_label="expansion", regime_label_bg="X",
        cross_lens_states={"stagflation_test": "transition", "credit_policy_transmission": "both_up"},
    )
    curr = BriefingStateSnapshot(
        as_of="2026-04-18", generated_on="2026-04-18",
        regime_label="expansion", regime_label_bg="X",
        cross_lens_states={"stagflation_test": "both_up", "credit_policy_transmission": "both_up"},
    )
    delta = compute_delta(curr, prev)
    assert len(delta.cross_lens_changes) == 1
    assert delta.cross_lens_changes[0].pair_id == "stagflation_test"
    assert delta.cross_lens_changes[0].from_state == "transition"
    assert delta.cross_lens_changes[0].to_state == "both_up"


def test_compute_delta_breadth_move_above_threshold():
    prev = BriefingStateSnapshot(
        as_of="2026-04-11", generated_on="2026-04-11",
        regime_label="x", regime_label_bg="x",
        breadth_by_pg={"inflation/core_measures": 0.4, "labor/claims": 0.6},
    )
    curr = BriefingStateSnapshot(
        as_of="2026-04-18", generated_on="2026-04-18",
        regime_label="x", regime_label_bg="x",
        breadth_by_pg={"inflation/core_measures": 0.7, "labor/claims": 0.65},
    )
    delta = compute_delta(curr, prev)
    # 0.4 → 0.7 е +30pp → above threshold
    # 0.6 → 0.65 е +5pp → below threshold (10pp)
    assert len(delta.breadth_moves) == 1
    m = delta.breadth_moves[0]
    assert m.lens == "inflation"
    assert m.peer_group == "core_measures"
    assert abs(m.delta_pp - 0.3) < 0.01


def test_compute_delta_breadth_move_threshold_boundary():
    # Точно над 10pp — включваме
    prev = BriefingStateSnapshot(
        as_of="x", generated_on="2026-04-11",
        regime_label="x", regime_label_bg="x",
        breadth_by_pg={"labor/claims": 0.4},
    )
    curr = BriefingStateSnapshot(
        as_of="y", generated_on="2026-04-18",
        regime_label="x", regime_label_bg="x",
        breadth_by_pg={"labor/claims": 0.55},  # +15pp, чисто над threshold
    )
    delta = compute_delta(curr, prev)
    assert len(delta.breadth_moves) == 1


def test_compute_delta_breadth_move_below_threshold_skipped():
    prev = BriefingStateSnapshot(
        as_of="x", generated_on="2026-04-11",
        regime_label="x", regime_label_bg="x",
        breadth_by_pg={"labor/claims": 0.4},
    )
    curr = BriefingStateSnapshot(
        as_of="y", generated_on="2026-04-18",
        regime_label="x", regime_label_bg="x",
        breadth_by_pg={"labor/claims": 0.45},  # +5pp, под threshold
    )
    delta = compute_delta(curr, prev)
    assert delta.breadth_moves == []


def test_compute_delta_breadth_skips_none():
    prev = BriefingStateSnapshot(
        as_of="x", generated_on="2026-04-11",
        regime_label="x", regime_label_bg="x",
        breadth_by_pg={"labor/claims": None},
    )
    curr = BriefingStateSnapshot(
        as_of="y", generated_on="2026-04-18",
        regime_label="x", regime_label_bg="x",
        breadth_by_pg={"labor/claims": 0.8},
    )
    delta = compute_delta(curr, prev)
    # None → не може да се пресметне delta
    assert delta.breadth_moves == []


def test_compute_delta_nc_additions_and_removals():
    prev = BriefingStateSnapshot(
        as_of="x", generated_on="2026-04-11",
        regime_label="x", regime_label_bg="x",
        high_nc_keys=["TEMPHELPS", "USINFO"],
    )
    curr = BriefingStateSnapshot(
        as_of="y", generated_on="2026-04-18",
        regime_label="x", regime_label_bg="x",
        high_nc_keys=["TEMPHELPS", "C_AND_I_LOANS"],
    )
    delta = compute_delta(curr, prev)
    assert delta.new_high_nc == ["C_AND_I_LOANS"]
    assert delta.vanished_high_nc == ["USINFO"]


def test_compute_delta_new_extremes_surfaced():
    prev = BriefingStateSnapshot(
        as_of="x", generated_on="2026-04-11",
        regime_label="x", regime_label_bg="x",
        new_extreme_keys=["CPI"],
    )
    curr = BriefingStateSnapshot(
        as_of="y", generated_on="2026-04-18",
        regime_label="x", regime_label_bg="x",
        new_extreme_keys=["CPI", "M2"],
    )
    delta = compute_delta(curr, prev)
    assert delta.new_extremes_surfaced == ["M2"]
    assert delta.new_extremes_resolved == []


def test_compute_delta_breadth_moves_sorted_by_magnitude():
    prev = BriefingStateSnapshot(
        as_of="x", generated_on="2026-04-11",
        regime_label="x", regime_label_bg="x",
        breadth_by_pg={
            "a/x": 0.5, "a/y": 0.5, "a/z": 0.5,
        },
    )
    curr = BriefingStateSnapshot(
        as_of="y", generated_on="2026-04-18",
        regime_label="x", regime_label_bg="x",
        breadth_by_pg={
            "a/x": 0.9,  # +40pp
            "a/y": 0.15, # -35pp
            "a/z": 0.72, # +22pp
        },
    )
    delta = compute_delta(curr, prev)
    abs_deltas = [abs(m.delta_pp) for m in delta.breadth_moves]
    # Descending by magnitude
    assert abs_deltas == sorted(abs_deltas, reverse=True)
    # +40pp first
    assert delta.breadth_moves[0].peer_group == "x"


def test_compute_delta_has_content_false_when_nothing_changed():
    state = BriefingStateSnapshot(
        as_of="x", generated_on="2026-04-18",
        regime_label="expansion", regime_label_bg="X",
        cross_lens_states={"p": "both_up"},
        breadth_by_pg={"a/b": 0.5},
        high_nc_keys=["K"],
        top_anomaly_keys=["M"],
        new_extreme_keys=["M"],
    )
    # Copy-like
    prev = BriefingStateSnapshot(
        as_of="x", generated_on="2026-04-11",
        regime_label="expansion", regime_label_bg="X",
        cross_lens_states={"p": "both_up"},
        breadth_by_pg={"a/b": 0.5},
        high_nc_keys=["K"],
        top_anomaly_keys=["M"],
        new_extreme_keys=["M"],
    )
    delta = compute_delta(state, prev)
    # top_anomaly rotation не е в has_content критерий нарочно; fokусът е на signal flips
    # Тук нищо не се е променило
    assert not delta.has_content


# ============================================================
# TESTS — persistence
# ============================================================

def test_save_and_load_state_roundtrip(tmp_path):
    snap = BriefingStateSnapshot(
        as_of="2026-04-18", generated_on="2026-04-18",
        regime_label="expansion", regime_label_bg="Разширяване",
        cross_lens_states={"stagflation_test": "transition"},
        breadth_by_pg={"labor/claims": 0.55},
        high_nc_keys=["K1"],
        top_anomaly_keys=["A", "B"],
        new_extreme_keys=["A"],
    )
    path = save_state(snap, state_dir=str(tmp_path))
    assert Path(path).exists()

    loaded = load_latest_state(state_dir=str(tmp_path))
    assert loaded is not None
    assert loaded.regime_label == "expansion"
    assert loaded.breadth_by_pg == {"labor/claims": 0.55}
    assert loaded.high_nc_keys == ["K1"]


def test_load_latest_state_returns_none_on_empty_dir(tmp_path):
    assert load_latest_state(state_dir=str(tmp_path)) is None


def test_load_latest_state_respects_before_cutoff(tmp_path):
    s1 = BriefingStateSnapshot(
        as_of="2026-04-04", generated_on="2026-04-04",
        regime_label="x", regime_label_bg="x",
    )
    s2 = BriefingStateSnapshot(
        as_of="2026-04-11", generated_on="2026-04-11",
        regime_label="y", regime_label_bg="y",
    )
    s3 = BriefingStateSnapshot(
        as_of="2026-04-18", generated_on="2026-04-18",
        regime_label="z", regime_label_bg="z",
    )
    for s in (s1, s2, s3):
        save_state(s, state_dir=str(tmp_path))

    # Before 2026-04-18 → latest < that е 2026-04-11
    loaded = load_latest_state(state_dir=str(tmp_path), before=date(2026, 4, 18))
    assert loaded is not None
    assert loaded.generated_on == "2026-04-11"


def test_load_latest_state_ignores_bad_filenames(tmp_path):
    (tmp_path / "briefing_not-a-date.json").write_text("{}")
    (tmp_path / "other.json").write_text("{}")
    assert load_latest_state(state_dir=str(tmp_path)) is None
