"""
tests/test_guardrails.py
=========================
Unit тестове за analysis/guardrails.py.

Проверяваме:
  Falsification mapping — per regime, non-empty, unknown → empty
  Threshold flags: yield curve inversion, HY OAS levels, Sahm rule, claims spike
  Missing серии → no crash, просто skip
  JSON safety
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from analysis.guardrails import (  # noqa: E402
    FALSIFIERS_BY_REGIME,
    ThresholdFlag,
    get_falsifiers,
    compute_threshold_flags,
    SEVERITY_RED,
    SEVERITY_AMBER,
)
from analysis.executive import REGIME_LABELS


# ============================================================
# HELPERS
# ============================================================

def weekly(values: list[float], end: str = "2026-04-17") -> pd.Series:
    # NB: end must align to W-FRI (Friday) — pandas 2.x не включва крайната дата,
    # ако не е на честотата.
    idx = pd.date_range(end=end, periods=len(values), freq="W-FRI")
    return pd.Series(values, index=idx)


def monthly(values: list[float], end: str = "2026-04-01") -> pd.Series:
    idx = pd.date_range(end=end, periods=len(values), freq="MS")
    return pd.Series(values, index=idx)


# ============================================================
# TESTS — FALSIFIERS
# ============================================================

def test_falsifiers_exist_for_every_regime():
    for r in REGIME_LABELS:
        falsifiers = get_falsifiers(r)
        assert isinstance(falsifiers, list)
        assert len(falsifiers) >= 1, f"regime {r} has no falsifiers"


def test_falsifiers_unknown_regime_returns_empty():
    assert get_falsifiers("does_not_exist") == []


def test_falsifiers_are_strings():
    for r in REGIME_LABELS:
        for f in get_falsifiers(r):
            assert isinstance(f, str)
            assert len(f) > 0


def test_falsifiers_returns_copy():
    # Mutation safety — ако caller модифицира върнатия list, FALSIFIERS_BY_REGIME
    # не трябва да се засяга.
    fals = get_falsifiers("expansion")
    fals.append("mutation attempt")
    assert "mutation attempt" not in FALSIFIERS_BY_REGIME["expansion"]


# ============================================================
# TESTS — YIELD CURVE FLAGS
# ============================================================

def test_yield_curve_inversion_triggers_red():
    snap = {"YC_10Y2Y": weekly([0.5, 0.3, 0.1, -0.2])}
    flags = compute_threshold_flags(snap)
    yc_flags = [f for f in flags if f.key.startswith("yield_curve")]
    assert len(yc_flags) == 1
    assert yc_flags[0].severity == SEVERITY_RED
    assert yc_flags[0].value == -0.2


def test_yield_curve_positive_no_flag():
    snap = {"YC_10Y2Y": weekly([0.5, 0.6, 0.7])}
    flags = compute_threshold_flags(snap)
    assert not any(f.key.startswith("yield_curve") for f in flags)


def test_yield_curve_both_2y_and_3m_inverted():
    snap = {
        "YC_10Y2Y": weekly([-0.3]),
        "YC_10Y3M": weekly([-0.5]),
    }
    flags = compute_threshold_flags(snap)
    yc_flags = [f for f in flags if f.key.startswith("yield_curve")]
    assert len(yc_flags) == 2


# ============================================================
# TESTS — HY OAS
# ============================================================

def test_hy_oas_above_7_is_red():
    snap = {"HY_OAS": weekly([4.5, 5.5, 6.5, 7.2])}
    flags = compute_threshold_flags(snap)
    hy = [f for f in flags if f.key.startswith("hy_oas")]
    assert len(hy) == 1
    assert hy[0].severity == SEVERITY_RED


def test_hy_oas_between_5_and_7_is_amber():
    snap = {"HY_OAS": weekly([4.0, 5.5])}
    flags = compute_threshold_flags(snap)
    hy = [f for f in flags if f.key.startswith("hy_oas")]
    assert len(hy) == 1
    assert hy[0].severity == SEVERITY_AMBER


def test_hy_oas_below_5_no_flag():
    snap = {"HY_OAS": weekly([3.2, 3.5, 4.0])}
    flags = compute_threshold_flags(snap)
    assert not any(f.key.startswith("hy_oas") for f in flags)


# ============================================================
# TESTS — SAHM RULE
# ============================================================

def test_sahm_rule_triggered():
    # 12 месеца; min ~3.5, последни 3 — 4.2 → diff = 0.7 > 0.5 RED
    values = [3.5, 3.5, 3.5, 3.6, 3.7, 3.7, 3.8, 3.9, 4.0, 4.1, 4.2, 4.3]
    snap = {"UNRATE": monthly(values)}
    flags = compute_threshold_flags(snap)
    sahm = [f for f in flags if f.key.startswith("sahm")]
    assert len(sahm) == 1
    assert sahm[0].severity == SEVERITY_RED


def test_sahm_rule_approaching_amber():
    # diff ~ 0.35pp (> 0.3 но < 0.5)
    values = [3.5, 3.5, 3.5, 3.5, 3.5, 3.55, 3.6, 3.6, 3.7, 3.8, 3.85, 3.85]
    snap = {"UNRATE": monthly(values)}
    flags = compute_threshold_flags(snap)
    sahm = [f for f in flags if f.key.startswith("sahm")]
    assert len(sahm) == 1
    assert sahm[0].severity == SEVERITY_AMBER


def test_sahm_rule_stable_no_flag():
    values = [4.0] * 12
    snap = {"UNRATE": monthly(values)}
    flags = compute_threshold_flags(snap)
    assert not any(f.key.startswith("sahm") for f in flags)


def test_sahm_rule_insufficient_history_skipped():
    values = [3.5] * 5
    snap = {"UNRATE": monthly(values)}
    flags = compute_threshold_flags(snap)
    assert not any(f.key.startswith("sahm") for f in flags)


# ============================================================
# TESTS — CLAIMS
# ============================================================

def test_claims_above_300k_is_red():
    snap = {"ICSA": weekly([220, 240, 310])}
    flags = compute_threshold_flags(snap)
    c = [f for f in flags if f.key.startswith("claims")]
    assert len(c) == 1
    assert c[0].severity == SEVERITY_RED


def test_claims_between_275_and_300_is_amber():
    snap = {"ICSA": weekly([220, 240, 280])}
    flags = compute_threshold_flags(snap)
    c = [f for f in flags if f.key.startswith("claims")]
    assert len(c) == 1
    assert c[0].severity == SEVERITY_AMBER


def test_claims_normal_no_flag():
    snap = {"ICSA": weekly([200, 220, 240])}
    flags = compute_threshold_flags(snap)
    assert not any(f.key.startswith("claims") for f in flags)


# ============================================================
# TESTS — EDGE CASES
# ============================================================

def test_empty_snapshot_no_flags_no_crash():
    assert compute_threshold_flags({}) == []


def test_missing_series_safe():
    snap = {"UNRATE": monthly([3.5])}  # под 12m, ще се skip-не
    flags = compute_threshold_flags(snap)
    # Няма YC, HY, ICSA — просто нищо
    assert isinstance(flags, list)


def test_threshold_flag_to_dict_json_safe():
    snap = {"YC_10Y2Y": weekly([-0.5])}
    flags = compute_threshold_flags(snap)
    assert len(flags) == 1
    d = flags[0].to_dict()
    import json
    json.dumps(d)  # не хвърля
    assert d["severity"] == "red"


def test_all_thresholds_activate_together():
    snap = {
        "YC_10Y2Y": weekly([-0.3]),
        "HY_OAS": weekly([8.0]),
        "UNRATE": monthly([3.5]*9 + [4.2, 4.3, 4.4]),
        "ICSA": weekly([320]),
    }
    flags = compute_threshold_flags(snap)
    keys = {f.key for f in flags}
    assert "yield_curve_yc_10y2y" in keys
    assert "hy_oas_stress_red" in keys
    assert "sahm_rule" in keys
    assert "claims_spike_red" in keys
