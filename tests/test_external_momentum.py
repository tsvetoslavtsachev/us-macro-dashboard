"""
tests/test_external_momentum.py
===============================
ПРОЛЕТР4С1 (26.11.2026, реш. Ц. „Да, по препоръките ти“): външната леща на САЩ е в
оценката и се оценява по рязката промяна (scoring_mode="momentum"), като external на EU.
Фискалната остава само за показване. Режимът остава на четирите стари лещи.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from analysis.health import lens_health, series_health_z  # noqa: E402
from catalog import series as catalog_series  # noqa: E402
from catalog.series import SERIES_CATALOG, series_by_lens, validate_catalog  # noqa: E402
from core.primitives import momentum_signal  # noqa: E402
from core.scorer import score_series  # noqa: E402


def _monthly(values, start="2010-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=len(values), freq="MS")
    return pd.Series(values, index=idx, dtype=float)


# ── momentum_signal ──────────────────────────────────────────────────────────

def test_momentum_signal_is_3m_change_of_3m_mean_for_monthly():
    s = _monthly(np.arange(1.0, 25.0) ** 2)
    m = momentum_signal(s)
    sm = s.rolling(3, min_periods=1).mean()
    expected = sm.diff(3).dropna()
    pd.testing.assert_series_equal(m, expected)


def test_momentum_signal_quarterly_uses_one_period():
    idx = pd.date_range("2010-01-01", periods=12, freq="QS")
    s = pd.Series(np.arange(12, dtype=float) ** 2, index=idx)
    m = momentum_signal(s)
    expected = s.rolling(3, min_periods=1).mean().diff(1).dropna()
    pd.testing.assert_series_equal(m, expected)


def test_momentum_signal_empty_stays_empty():
    assert momentum_signal(pd.Series([], dtype=float)).empty


# ── health: series и леща ────────────────────────────────────────────────────

def _trending_with_shock(n=180, shock=40.0):
    rng = np.random.default_rng(7)
    base = np.cumsum(rng.normal(0.0, 1.0, n))       # бавен дрейф: по ниво далеч от нормата
    base[-3:] += shock                                # рязък скок в края
    return _monthly(base)


def test_series_health_z_momentum_scores_the_change_not_the_level():
    s = _trending_with_shock()
    z_level = series_health_z(s, "level", +1)
    z_mom = series_health_z(s, "level", +1, scoring_mode="momentum")
    z_manual = series_health_z(momentum_signal(s), "level", +1)
    assert z_mom == pytest.approx(z_manual)
    assert z_mom != pytest.approx(z_level)
    assert z_mom > 3.0     # скокът е далеч над нормалния тримесечен темп


def test_series_health_z_default_is_level_unchanged():
    s = _trending_with_shock()
    assert series_health_z(s, "level", -1) == series_health_z(s, "level", -1, scoring_mode="level")


def test_lens_health_external_uses_momentum_for_every_member():
    keys = [e["_key"] for e in series_by_lens("external")]
    assert sorted(keys) == ["BOPGSTB", "BOPTEXP", "USD_BROAD"]
    snap = {
        "BOPGSTB": _trending_with_shock(shock=-30.0),
        "BOPTEXP": _monthly(100 + np.arange(180, dtype=float)),
        "USD_BROAD": _monthly(100 + np.sin(np.arange(180) / 6.0) * 5),
    }
    from catalog.polarity import polarity_for
    z = {k: series_health_z(snap[k], SERIES_CATALOG[k]["transform"], polarity_for(k, "external"),
                            scoring_mode="momentum") for k in snap}
    trade = np.mean([z["BOPGSTB"], z["BOPTEXP"]])
    expected = round((trade + z["USD_BROAD"]) / 2, 3)
    assert lens_health("external", snap)["health_z"] == expected


# ── каталогът ────────────────────────────────────────────────────────────────

def test_external_entries_are_momentum_and_fiscal_is_level():
    for k in ("BOPGSTB", "BOPTEXP", "USD_BROAD"):
        assert SERIES_CATALOG[k]["scoring_mode"] == "momentum"
    for k in ("FED_DEFICIT", "FED_DEBT_GDP", "FED_INTEREST"):
        assert SERIES_CATALOG[k].get("scoring_mode", "level") == "level"
    others = [k for k, m in SERIES_CATALOG.items()
              if m.get("scoring_mode", "level") == "momentum" and "external" not in m["lens"]]
    assert others == []


def test_validate_catalog_rejects_unknown_scoring_mode(monkeypatch):
    bad = dict(SERIES_CATALOG["BOPGSTB"], scoring_mode="velocity")
    monkeypatch.setitem(catalog_series.SERIES_CATALOG, "BOPGSTB", bad)
    errs = validate_catalog()
    assert any("scoring_mode" in e and "BOPGSTB" in e for e in errs)


def test_catalog_is_valid():
    assert validate_catalog() == []


# ── scorer (серийният z на лупата) ───────────────────────────────────────────

def test_score_series_momentum_matches_lens_series_z():
    s = _trending_with_shock()
    d = score_series(s, name="X", transform="level", polarity=("U", "self"), scoring_mode="momentum")
    assert d["scoring_mode"] == "momentum"
    assert d["health_z"] == pytest.approx(round(series_health_z(s, "level", ("U", "self"), "momentum"), 2))
    assert d["display_value"] == pytest.approx(round(float(s.iloc[-1]), 4))   # дисплеят е нивото


def test_score_series_default_level_unchanged():
    s = _trending_with_shock()
    a = score_series(s, name="X", transform="level", polarity=+1)
    b = score_series(s, name="X", transform="level", polarity=+1, scoring_mode="level")
    assert a == b and a["scoring_mode"] == "level"


# ── export_api: кои лещи се оценяват ─────────────────────────────────────────

def test_scored_lenses_add_external_but_regime_lenses_stay_four():
    import export_api
    assert export_api.LENSES == ["labor", "growth", "inflation", "liquidity"]
    assert export_api.SCORED_LENSES == export_api.LENSES + ["external"]
    assert "fiscal" not in export_api.SCORED_LENSES
    assert "housing" not in export_api.SCORED_LENSES


# ── build_latest: сборът остава на режимните лещи ─────────────────────────────

def test_manifest_composite_ignores_external_but_lists_it():
    import export_api
    from export.build_latest import COMPOSITE_LENSES, build_manifest
    assert COMPOSITE_LENSES == tuple(export_api.LENSES)
    st = {"region": "US", "as_of_date": "2026-11-26", "generated_at": "x",
          "executive_summary": {"regime_key": "k"}, "top_anomalies": [],
          "lenses": {"labor": {"score": 60.0}, "growth": {"score": 40.0},
                     "external": {"score": 10.0}}}
    m = build_manifest(st)
    assert m["composite_score"] == 50.0
    assert len(m["lenses"]) == 3
