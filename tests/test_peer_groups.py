"""
tests/test_peer_groups.py
==========================
Тестове за примитивите приложени към новите peer_groups от Phase 2.

Синтетични серии симулират реални макро setup-и:
  - Inflation expectations breadth (stagflation setup)
  - Wage dynamics intra-lens divergence
  - Labor tight × Inflation rising (cross-lens stagflation confirmation)
  - Yield curve inversion (term_structure)
  - Credit spreads widening (HY + IG едновременно)

Целта е не да тестваме primitives (това е в test_primitives.py), а да
потвърдим, че логиката се държи правилно при реалистични макро конфигурации.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# econ_v2/ в Python path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.primitives import (  # noqa: E402
    breadth_positive,
    breadth_extreme,
    divergence,
    z_score,
    new_extreme,
)


# ============================================================
# Helpers за синтетични серии
# ============================================================

def make_monthly_series(values: list[float], end: str = "2026-03-01") -> pd.Series:
    """Създава monthly серия с N стойности, end-dated."""
    idx = pd.date_range(end=end, periods=len(values), freq="MS")
    return pd.Series(values, index=idx)


def stable_then_spike(n: int = 60, stable: float = 2.0, spike: float = 5.0) -> pd.Series:
    """Стабилна серия → spike в последните 3 точки.
    z-score на последната ще е >> 2.
    """
    # Малка детерминистична вълна за да няма std=0, но не достатъчна за |z|>2
    vals = [stable + 0.01 * np.sin(i * 0.3) for i in range(n - 3)]
    vals.extend([spike, spike + 0.2, spike + 0.5])
    return make_monthly_series(vals)


def stable_series(n: int = 60, level: float = 2.0) -> pd.Series:
    """Стабилна серия — z-score близо до 0.

    Детерминистична sinus вълна с ниска амплитуда → гарантира std > 0
    (z_score деление не е 0), но никое наблюдение не може да има |z| > 2.
    """
    vals = [level + 0.01 * np.sin(i * 0.3) for i in range(n)]
    return make_monthly_series(vals)


def trending_up(n: int = 60, start: float = 2.0, end: float = 5.0) -> pd.Series:
    """Тренд нагоре — положителен momentum."""
    vals = list(np.linspace(start, end, n))
    return make_monthly_series(vals)


def trending_down(n: int = 60, start: float = 5.0, end: float = 2.0) -> pd.Series:
    """Тренд надолу — отрицателен momentum."""
    vals = list(np.linspace(start, end, n))
    return make_monthly_series(vals)


# Фиксиране на seed за детерминистичност
@pytest.fixture(autouse=True)
def _set_seed():
    np.random.seed(42)


# ============================================================
# TEST 1 — Inflation expectations breadth (stagflation setup)
# ============================================================

class TestInflationExpectationsBreadth:
    """peer_group: inflation.expectations.

    Серии: MICH_INFL_1Y, BREAKEVEN_10Y, BREAKEVEN_5Y5Y.
    Ако 2 от 3 са в extreme (hot expectations) → breadth = 0.667.
    Това е класически early-warning сигнал за inflation de-anchoring.
    """

    def test_two_of_three_hot_expectations(self):
        group = {
            "MICH_INFL_1Y": stable_then_spike(),   # spike — hot
            "BREAKEVEN_10Y": stable_then_spike(),  # spike — hot
            "BREAKEVEN_5Y5Y": stable_series(),     # stable — NOT hot
        }
        result = breadth_extreme(group, z_threshold=2.0)
        assert result == pytest.approx(2 / 3, abs=0.01)

    def test_all_anchored_expectations(self):
        """Всички стабилни → breadth = 0 (anchored, здрав setup)."""
        group = {
            "MICH_INFL_1Y": stable_series(),
            "BREAKEVEN_10Y": stable_series(),
            "BREAKEVEN_5Y5Y": stable_series(),
        }
        result = breadth_extreme(group, z_threshold=2.0)
        assert result == pytest.approx(0.0)

    def test_all_de_anchored(self):
        """Всички spike → breadth = 1.0 (de-anchoring в ход)."""
        group = {
            "MICH_INFL_1Y": stable_then_spike(),
            "BREAKEVEN_10Y": stable_then_spike(),
            "BREAKEVEN_5Y5Y": stable_then_spike(),
        }
        result = breadth_extreme(group, z_threshold=2.0)
        assert result == pytest.approx(1.0)


# ============================================================
# TEST 2 — Wage dynamics intra-lens divergence
# ============================================================

class TestWageDynamicsDivergence:
    """peer_group: labor.wage_dynamics (AHE, ECIWAG, WAGE_TRACKER_ATL).

    Класически intra-lens divergence signal:
      - AHE (broad average hourly earnings) ускорява
      - ECIWAG (quality-adjusted) се охлажда
    → композицията на заетите се променя, не реалният wage pressure.
    """

    def test_ahe_accelerating_eci_cooling(self):
        """AHE нагоре, ECIWAG надолу → breadth_positive = 0.5."""
        group_ahe_up = {
            "AHE": trending_up(),           # ускорява → positive momentum
            "ECIWAG": trending_down(),      # охлажда → negative momentum
        }
        breadth = breadth_positive(group_ahe_up, transform="momentum", periods=1)
        assert breadth == pytest.approx(0.5)

    def test_both_accelerating(self):
        """И двете нагоре → breadth = 1.0 (true wage pressure)."""
        group = {
            "AHE": trending_up(),
            "ECIWAG": trending_up(),
            "WAGE_TRACKER_ATL": trending_up(),
        }
        breadth = breadth_positive(group, transform="momentum", periods=1)
        assert breadth == pytest.approx(1.0)


# ============================================================
# TEST 3 — Cross-lens divergence (stagflation confirmation)
# ============================================================

class TestCrossLensStagflationSignal:
    """Класически stagflation setup:
      labor lens → tight (unemployment low, wages rising, positive breadth)
      inflation lens → hot (core CPI rising, positive breadth)

    Когато breadth(labor) и breadth(inflation) и двете са високи, това
    потвърждава стагфлационна теза, защото ДВЕТЕ независими лещи показват
    едно и също нещо. За разлика — ако labor tight, но inflation cooling →
    класически soft landing (НЕ стагфлация).
    """

    def test_stagflation_both_high(self):
        """Labor tight + inflation hot → и двете групи имат висок breadth.

        divergence е близо до 0 (групите се движат заедно), breadth на
        всяка група — високо. Това е конфирмативен, не контраиндикативен
        сигнал.
        """
        labor_tight = {
            "UNRATE_INV": trending_up(),  # represents tightening (inverted)
            "AHE": trending_up(),
            "JOBS_FILLED": trending_up(),
        }
        inflation_hot = {
            "CORE_CPI": trending_up(),
            "STICKY_CPI": trending_up(),
            "PCE_CORE": trending_up(),
        }
        b_labor = breadth_positive(labor_tight)
        b_infl = breadth_positive(inflation_hot)
        div = divergence(labor_tight, inflation_hot)

        assert b_labor == pytest.approx(1.0)
        assert b_infl == pytest.approx(1.0)
        assert div == pytest.approx(0.0)  # confirming, not diverging

    def test_soft_landing_labor_tight_inflation_cooling(self):
        """Labor tight, inflation cooling → divergence > 0 (labor по-силен).

        Класически soft landing setup — обратен на стагфлация.
        """
        labor_tight = {
            "UNRATE_INV": trending_up(),
            "AHE": trending_up(),
        }
        inflation_cooling = {
            "CORE_CPI": trending_down(),
            "STICKY_CPI": trending_down(),
        }
        div = divergence(labor_tight, inflation_cooling)
        # labor breadth = 1.0, inflation breadth = 0.0 → div = 1.0
        assert div == pytest.approx(1.0)


# ============================================================
# TEST 4 — Yield curve inversion (term_structure)
# ============================================================

class TestYieldCurveInversion:
    """peer_group: liquidity.term_structure (UST_2Y, UST_10Y, YC_10Y2Y, YC_10Y3M).

    YC_10Y2Y < 0 е inverted curve — класически recession leading indicator.
    Това е single-series signal, не peer_group breadth.
    """

    def test_yc_10y2y_inversion_detected_as_new_extreme(self):
        """YC_10Y2Y с нов 5-year min → recession signal."""
        # 60 месечно: положителни стойности, последна точка — инверсия
        vals = [0.5 + np.random.normal(0, 0.1) for _ in range(57)]
        vals.extend([0.2, -0.1, -0.5])  # клон надолу и инверсия
        yc_10y2y = make_monthly_series(vals)

        result = new_extreme(yc_10y2y, lookback_years=5)
        assert result is not None
        assert result["direction"] == "min"
        assert result["value"] < 0  # inverted

    def test_yc_positive_normal(self):
        """YC положителна — не trigger-ва сигнал."""
        vals = [1.5 + np.random.normal(0, 0.1) for _ in range(60)]
        yc_normal = make_monthly_series(vals)

        result = new_extreme(yc_normal, lookback_years=5)
        # May or may not be a new extreme, but ако е — не е inversion
        if result is not None:
            assert result["value"] > 0


# ============================================================
# TEST 5 — Credit spreads widening (liquidity.credit_spreads)
# ============================================================

class TestCreditSpreadsWidening:
    """peer_group: liquidity.credit_spreads (HY_OAS, IG_OAS).

    Разграничение:
      - HY spike сам → idiosyncratic stress (един сектор)
      - HY + IG и двете spike → systemic stress (credit cycle turning)
    breadth_extreme = 1.0 (и двете) → systemic; 0.5 → idiosyncratic.
    """

    def test_systemic_stress_both_widening(self):
        """HY + IG и двете z > 2 → breadth_extreme = 1.0."""
        group = {
            "HY_OAS": stable_then_spike(stable=3.5, spike=8.0),
            "IG_OAS": stable_then_spike(stable=1.2, spike=3.0),
        }
        breadth = breadth_extreme(group, z_threshold=2.0)
        assert breadth == pytest.approx(1.0)

    def test_idiosyncratic_stress_hy_only(self):
        """HY spike сам, IG стабилен → breadth_extreme = 0.5."""
        group = {
            "HY_OAS": stable_then_spike(stable=3.5, spike=8.0),
            "IG_OAS": stable_series(level=1.2),
        }
        breadth = breadth_extreme(group, z_threshold=2.0)
        assert breadth == pytest.approx(0.5)

    def test_benign_no_stress(self):
        """И двете стабилни → breadth = 0 (no credit stress)."""
        group = {
            "HY_OAS": stable_series(level=3.5),
            "IG_OAS": stable_series(level=1.2),
        }
        breadth = breadth_extreme(group, z_threshold=2.0)
        assert breadth == pytest.approx(0.0)
