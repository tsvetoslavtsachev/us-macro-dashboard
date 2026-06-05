"""
Unit tests за magnitude/severity примитива (item F).
=====================================================
„Десет подвежда по магнитуд": 0–100 score-ът насища (tanh) и трупа дъното, така
че мек спад (−2σ) не се различава от крах (−8σ). σ-магнитудът (dev_sigma) носи
информацията; severity_tier я лейбълва по ЕДНА глобална скала.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.primitives import severity_tier, SEVERITY_EDGES, SEVERITY_LABELS
from core.scorer import score_series, _dev_sigma


def make_monthly(values, start="2010-01-01"):
    idx = pd.date_range(start=start, periods=len(values), freq="MS")
    return pd.Series(values, index=idx)


# ── severity_tier: глобални прагове ───────────────────────────────────────────

@pytest.mark.parametrize("dev,expected", [
    (0.0, "норма"), (0.99, "норма"), (-0.99, "норма"),
    (1.0, "забележимо"), (1.99, "забележимо"), (-1.5, "забележимо"),
    (2.0, "разпънато"), (2.99, "разпънато"), (-2.5, "разпънато"),
    (3.0, "екстремно"), (8.0, "екстремно"), (-12.0, "екстремно"),
])
def test_severity_tier_boundaries(dev, expected):
    assert severity_tier(dev) == expected


def test_severity_tier_symmetric_in_sign():
    # Магнитудът е полярностно-агностичен → |dev| решава.
    for d in (1.3, 2.7, 4.0):
        assert severity_tier(d) == severity_tier(-d)


def test_severity_tier_none_and_nan():
    assert severity_tier(None) is None
    assert severity_tier(float("nan")) is None


def test_severity_constants_are_global_and_ordered():
    # ЕДНА скала за всички серии/икономики (без per-series tuning).
    assert SEVERITY_EDGES == (1.0, 2.0, 3.0)
    assert len(SEVERITY_LABELS) == len(SEVERITY_EDGES) + 1
    assert list(SEVERITY_EDGES) == sorted(SEVERITY_EDGES)


# ── ключовото свойство: разграничава „мек" от „крах" при насищане ─────────────

def test_saturation_distinguished_by_severity():
    """Два сценария, и двата със score близо до пода, но различен магнитуд.

    Норма ~ uniform[−2, 2] (scale ≈ 1.5σ). Полярност +1 (по-високо = по-здраво).
    """
    base = np.linspace(-2.0, 2.0, 118).tolist()
    soft = make_monthly(base + [-3.6])     # ~2–3σ под нормата (мек спад)
    crash = make_monthly(base + [-30.0])   # дълбоко под нормата (крах)

    sd_soft = score_series(soft, transform="level", polarity=+1)
    sd_crash = score_series(crash, transform="level", polarity=+1)

    # Score-ът насища: и двата залепват ниско и НЕ ги различава добре.
    assert sd_soft["score"] < 15 and sd_crash["score"] < 15

    # ... но σ-магнитудът ги различава: крахът е екстремен, мекият спад — не.
    assert abs(sd_crash["dev_sigma"]) > abs(sd_soft["dev_sigma"])
    assert sd_crash["severity"] == "екстремно"
    assert sd_soft["severity"] != "екстремно"


# ── score_series поднася полетата ─────────────────────────────────────────────

def test_score_series_emits_dev_sigma_and_severity():
    s = make_monthly(np.linspace(95, 105, 130).tolist())
    sd = score_series(s, transform="level", polarity=+1)
    assert "dev_sigma" in sd and "severity" in sd
    assert sd["severity"] in SEVERITY_LABELS
    assert isinstance(sd["dev_sigma"], float)


def test_empty_series_severity_is_none():
    sd = score_series(pd.Series(dtype=float), name="x")
    assert sd["dev_sigma"] is None
    assert sd["severity"] is None


# ── dev_sigma: знак суров (над/под референция), U-target спрямо целта ──────────

def test_dev_sigma_sign_is_raw_not_health_oriented():
    # Полярност −1 (по-високо = по-зле), но dev_sigma остава суров „над нормата".
    base = np.linspace(-1.0, 1.0, 118).tolist()
    s = make_monthly(base + [5.0])      # latest далеч НАД нормата (scale > 0)
    sd = score_series(s, transform="level", polarity=-1)
    assert sd["dev_sigma"] > 0          # стойността е НАД нормата (суров знак)
    assert sd["health_z"] < 0           # ... но здравето е надолу (полярност −1)


def test_dev_sigma_u_target_measures_distance_from_target():
    # U-target=2.0: отклонението се мери от целта, не от собствената median.
    med_around = 5.0
    s = make_monthly(([med_around] * 119) + [med_around])
    # latest == median == 5.0; целта е 2.0 → dev_sigma ≈ (5-2)/scale, но scale=0 тук.
    # затова правим серия с вариация:
    vals = (np.linspace(4.0, 6.0, 119).tolist()) + [5.0]
    s = make_monthly(vals)
    dev = _dev_sigma(5.0, float(pd.Series(vals).median()), 1.0, ("U", "target", 2.0))
    assert dev == pytest.approx((5.0 - 2.0) / 1.0)
