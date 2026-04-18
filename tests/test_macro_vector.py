"""
tests/test_macro_vector.py
===========================
Тестове за 8-dim macro state vector builder:

  - _yoy_pct, _to_month_end, _compute_sahm_rule
  - _calibrate_proxy
  - build_history_matrix (end-to-end със synthetic FRED-like data)
  - z_score_matrix
  - build_current_vector
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from analysis.macro_vector import (  # noqa: E402
    ANALOG_WINDOW_START,
    ANALOG_FETCH_SPEC,
    BREAKEVEN_START,
    DIM_LABELS_BG,
    DIM_UNITS,
    HY_OAS_START,
    MacroState,
    STATE_VECTOR_DIMS,
    _calibrate_proxy,
    _compute_sahm_rule,
    _to_month_end,
    _yoy_pct,
    build_current_vector,
    build_history_matrix,
    z_score_matrix,
)


# ============================================================
# HELPERS
# ============================================================

def _monthly_range(start: str, end: str) -> pd.DatetimeIndex:
    return pd.date_range(start=start, end=end, freq="M")


def _daily_range(start: str, end: str) -> pd.DatetimeIndex:
    return pd.date_range(start=start, end=end, freq="D")


# ============================================================
# PRIMITIVES
# ============================================================

class TestTransformPrimitives:

    def test_yoy_pct_returns_12m_percent_change(self):
        idx = _monthly_range("2020-01-01", "2021-12-31")
        # ровен ръст 10%/год
        base = 100.0
        vals = [base * (1.10 ** (i / 12)) for i in range(len(idx))]
        s = pd.Series(vals, index=idx)
        yoy = _yoy_pct(s).dropna()
        # 13-ият месец (jan-2021) трябва да е ≈ 10%
        assert yoy.iloc[0] == pytest.approx(10.0, rel=0.02)

    def test_to_month_end_picks_last_observation(self):
        idx = _daily_range("2026-01-01", "2026-03-31")
        s = pd.Series(range(len(idx)), index=idx, dtype=float)
        m = _to_month_end(s)
        # три месеца = три month-end точки
        assert len(m) == 3
        # последната стойност на януари е стойността на 31-ви януари
        jan_end_val = s.loc["2026-01-31"]
        assert m.iloc[0] == jan_end_val


class TestSahmRule:

    def test_flat_unemployment_gives_zero_sahm(self):
        idx = _monthly_range("2020-01-01", "2022-12-31")
        unrate = pd.Series(4.0, index=idx)
        sahm = _compute_sahm_rule(unrate).dropna()
        assert (sahm.abs() < 1e-9).all()

    def test_unemployment_spike_raises_sahm(self):
        """Ако UNRATE стои на 3.5% 12 месеца, после скача на 4.5% за 3 месеца,
        SAHM трябва да е ≈ 1.0 pp."""
        pre_idx = _monthly_range("2020-01-01", "2020-12-31")
        post_idx = _monthly_range("2021-01-01", "2021-03-31")
        pre = pd.Series(3.5, index=pre_idx)
        post = pd.Series(4.5, index=post_idx)
        unrate = pd.concat([pre, post])
        sahm = _compute_sahm_rule(unrate)
        # март 2021 = 3mma(4.5) = 4.5; min trailing 12m = 3.5 → diff = 1.0
        assert sahm.loc["2021-03-31"] == pytest.approx(1.0, rel=1e-3)


# ============================================================
# PROXY CALIBRATION
# ============================================================

class TestCalibrateProxy:

    def test_overlap_rescales_proxy_to_primary_moments(self):
        """Пример: primary в overlap има μ=5, σ=2; proxy има μ=2, σ=1.
        След rescale, proxy трябва да има μ=5, σ=2 на overlap периода."""
        idx = _monthly_range("1970-01-01", "2020-12-31")
        splice = "2000-01-01"

        np.random.seed(42)
        overlap_idx = idx[idx >= splice]
        pre_idx = idx[idx < splice]

        primary_vals = np.concatenate(
            [np.full(len(pre_idx), np.nan),
             np.random.normal(5.0, 2.0, size=len(overlap_idx))]
        )
        primary = pd.Series(primary_vals, index=idx)

        proxy = pd.Series(
            np.random.normal(2.0, 1.0, size=len(idx)),
            index=idx,
        )

        out = _calibrate_proxy(primary, proxy, splice)
        # post-splice — ползва primary; pre-splice — rescaled proxy
        post = out.loc[splice:].dropna()
        pre = out.loc[out.index < splice].dropna()
        # Primary post — както подадено
        assert np.allclose(post.values, primary.loc[splice:].dropna().values)
        # Pre-splice proxy, rescaled → μ≈5, σ≈2
        assert pre.mean() == pytest.approx(5.0, abs=0.5)
        assert pre.std(ddof=0) == pytest.approx(2.0, abs=0.5)

    def test_no_overlap_falls_back_to_raw_concat(self):
        """Ако няма overlap ≥12 месеца, фактически ползва proxy raw."""
        idx_pre = _monthly_range("1980-01-01", "1989-12-31")
        idx_post = _monthly_range("2000-01-01", "2010-12-31")
        proxy = pd.Series(3.0, index=idx_pre)
        primary = pd.Series(5.0, index=idx_post)
        # Без overlap
        full_idx = idx_pre.union(idx_post)
        primary_full = primary.reindex(full_idx)
        proxy_full = proxy.reindex(full_idx)

        out = _calibrate_proxy(primary_full, proxy_full, "2000-01-01")
        # pre-2000 → proxy raw (3.0); post-2000 → primary (5.0)
        assert out.loc[idx_pre[0]] == 3.0
        assert out.loc[idx_post[0]] == 5.0


# ============================================================
# BUILD HISTORY MATRIX
# ============================================================

def _make_synthetic_fetched(start: str = "1975-01-01", end: str = "2026-03-31") -> dict[str, pd.Series]:
    """Produce всичките ANALOG_FETCH_SPEC keys със синтетични-но-реалистични данни."""
    midx = _monthly_range(start, end)
    didx = _daily_range(start, end)

    np.random.seed(7)
    unrate = pd.Series(4.0 + np.random.normal(0, 0.2, len(midx)), index=midx)
    # Core CPI level, growing ~2.5%/yr + small noise
    yrs = np.arange(len(midx)) / 12.0
    core_cpi = pd.Series(100.0 * (1.025 ** yrs), index=midx)
    # DFF daily ~2% + noise
    dff = pd.Series(2.0 + np.random.normal(0, 0.1, len(didx)), index=didx)
    # T10Y2Y daily from 1976+ only
    t10y2y_idx = didx[didx >= "1976-06-01"]
    t10y2y = pd.Series(np.random.normal(1.0, 0.5, len(t10y2y_idx)), index=t10y2y_idx)
    # HY OAS from 1996-12+
    hy_idx = didx[didx >= HY_OAS_START]
    hy = pd.Series(4.0 + np.random.normal(0, 1.0, len(hy_idx)), index=hy_idx)
    # INDPRO monthly
    indpro = pd.Series(100.0 * (1.02 ** yrs), index=midx)
    # Breakeven 10Y from 2003+
    be_idx = didx[didx >= BREAKEVEN_START]
    be = pd.Series(2.0 + np.random.normal(0, 0.3, len(be_idx)), index=be_idx)
    # DGS10 / DGS2 daily
    dgs10 = pd.Series(4.0 + np.random.normal(0, 0.5, len(didx)), index=didx)
    dgs2 = pd.Series(3.0 + np.random.normal(0, 0.5, len(didx)), index=didx)
    # BAA monthly, 5% avg
    baa = pd.Series(5.0 + np.random.normal(0, 0.4, len(midx)), index=midx)
    # Michigan 1Y monthly from 1978+
    mich_idx = midx[midx >= "1978-01-01"]
    mich = pd.Series(3.0 + np.random.normal(0, 1.0, len(mich_idx)), index=mich_idx)

    return {
        "ANALOG_UNRATE": unrate,
        "ANALOG_CORE_CPI": core_cpi,
        "ANALOG_DFF": dff,
        "ANALOG_T10Y2Y": t10y2y,
        "ANALOG_HY_OAS": hy,
        "ANALOG_INDPRO": indpro,
        "ANALOG_T10YIE": be,
        "ANALOG_DGS10": dgs10,
        "ANALOG_DGS2": dgs2,
        "ANALOG_BAA": baa,
        "ANALOG_MICH": mich,
    }


class TestBuildHistoryMatrix:

    def test_returns_all_8_dims(self):
        fetched = _make_synthetic_fetched()
        df = build_history_matrix(fetched)
        assert list(df.columns) == STATE_VECTOR_DIMS
        assert len(df.columns) == 8

    def test_window_starts_at_1976(self):
        fetched = _make_synthetic_fetched()
        df = build_history_matrix(fetched)
        assert df.index[0] >= pd.Timestamp(ANALOG_WINDOW_START)

    def test_monthly_frequency(self):
        fetched = _make_synthetic_fetched()
        df = build_history_matrix(fetched)
        # Индексът да са month-ends
        assert (df.index == df.index.to_period("M").to_timestamp("M")).all() or \
               all(d == (d + pd.offsets.MonthEnd(0)) for d in df.index)

    def test_yoy_dims_have_early_nan(self):
        """YoY изисква 12m история — първите ~12 наблюдения са NaN за yoy колони."""
        fetched = _make_synthetic_fetched()
        df = build_history_matrix(fetched, start="1976-01-01")
        # core_cpi започва от 1975, така че core_cpi_yoy има данни от 1976+
        # ip_yoy също
        assert df["core_cpi_yoy"].dropna().empty is False
        assert df["ip_yoy"].dropna().empty is False

    def test_hy_oas_uses_proxy_pre_1996(self):
        """Преди 1996-12 hy_oas колоната идва от BAA−DGS10, rescaled."""
        fetched = _make_synthetic_fetched()
        df = build_history_matrix(fetched)
        pre = df.loc[:"1996-11-30", "hy_oas"].dropna()
        assert not pre.empty  # proxy трябва да е произвел стойности

    def test_breakeven_uses_proxy_pre_2003(self):
        fetched = _make_synthetic_fetched()
        df = build_history_matrix(fetched)
        pre = df.loc["1978-01-01":"2002-12-31", "breakeven"].dropna()
        assert not pre.empty

    def test_sahm_rule_computed_from_unrate(self):
        fetched = _make_synthetic_fetched()
        df = build_history_matrix(fetched)
        assert df["sahm"].dropna().empty is False

    def test_missing_t10y2y_falls_back_to_dgs10_minus_dgs2(self):
        fetched = _make_synthetic_fetched()
        fetched["ANALOG_T10Y2Y"] = pd.Series(dtype=float)  # празна
        df = build_history_matrix(fetched)
        # Проверяваме, че yc_10y2y пак има данни
        assert df["yc_10y2y"].dropna().empty is False


# ============================================================
# Z-SCORE MATRIX
# ============================================================

class TestZScoreMatrix:

    def test_standard_column_has_zero_mean_unit_std(self):
        idx = _monthly_range("2000-01-01", "2020-12-31")
        df = pd.DataFrame({
            "a": np.random.RandomState(0).normal(5, 2, len(idx)),
            "b": np.random.RandomState(1).normal(-3, 0.5, len(idx)),
        }, index=idx)
        z = z_score_matrix(df)
        assert z["a"].mean() == pytest.approx(0.0, abs=1e-10)
        assert z["a"].std(ddof=0) == pytest.approx(1.0, abs=1e-10)
        assert z["b"].mean() == pytest.approx(0.0, abs=1e-10)
        assert z["b"].std(ddof=0) == pytest.approx(1.0, abs=1e-10)

    def test_constant_column_returns_zeros(self):
        idx = _monthly_range("2000-01-01", "2020-12-31")
        df = pd.DataFrame({"c": 3.0}, index=idx)
        z = z_score_matrix(df)
        assert (z["c"].dropna() == 0.0).all()

    def test_nan_inputs_remain_nan(self):
        idx = _monthly_range("2000-01-01", "2005-12-31")
        vals = [1.0, 2.0, np.nan, 4.0, 5.0] * (len(idx) // 5) + [np.nan] * (len(idx) % 5)
        vals = vals[:len(idx)]
        df = pd.DataFrame({"x": vals}, index=idx)
        z = z_score_matrix(df)
        assert z["x"].isna().sum() > 0


# ============================================================
# CURRENT VECTOR
# ============================================================

class TestBuildCurrentVector:

    def test_returns_last_complete_row(self):
        fetched = _make_synthetic_fetched()
        df = build_history_matrix(fetched)
        z = z_score_matrix(df)
        state = build_current_vector(df, z)
        assert state is not None
        assert isinstance(state, MacroState)
        # последната дата в z (complete cases)
        assert state.as_of == z.dropna().index[-1]

    def test_respects_today_filter(self):
        fetched = _make_synthetic_fetched()
        df = build_history_matrix(fetched)
        z = z_score_matrix(df)
        cutoff = "2010-06-30"
        state = build_current_vector(df, z, today=pd.Timestamp(cutoff))
        assert state is not None
        assert state.as_of <= pd.Timestamp(cutoff)

    def test_empty_returns_none(self):
        empty_df = pd.DataFrame(columns=STATE_VECTOR_DIMS)
        empty_z = pd.DataFrame(columns=STATE_VECTOR_DIMS)
        state = build_current_vector(empty_df, empty_z)
        assert state is None

    def test_empty_with_today_filter_does_not_crash(self):
        """Regression: празен DataFrame + today филтър не трябва да крашва
        с TypeError (Timestamp vs numpy.ndarray cmp).
        """
        empty_df = pd.DataFrame(columns=STATE_VECTOR_DIMS)
        empty_z = pd.DataFrame(columns=STATE_VECTOR_DIMS)
        state = build_current_vector(empty_df, empty_z, today=pd.Timestamp("2026-04-18"))
        assert state is None

    def test_as_array_has_right_dim_order(self):
        fetched = _make_synthetic_fetched()
        df = build_history_matrix(fetched)
        z = z_score_matrix(df)
        state = build_current_vector(df, z)
        arr = state.as_array()
        assert arr.shape == (8,)
        # Всички стойности са z-scored значи финитни
        assert np.all(np.isfinite(arr))


# ============================================================
# METADATA
# ============================================================

class TestMetadata:

    def test_all_dims_have_bg_label(self):
        for d in STATE_VECTOR_DIMS:
            assert d in DIM_LABELS_BG
            assert DIM_LABELS_BG[d]

    def test_all_dims_have_unit(self):
        for d in STATE_VECTOR_DIMS:
            assert d in DIM_UNITS

    def test_fetch_spec_has_all_needed_ids(self):
        keys = {spec["key"] for spec in ANALOG_FETCH_SPEC}
        required = {
            "ANALOG_UNRATE", "ANALOG_CORE_CPI", "ANALOG_DFF",
            "ANALOG_T10Y2Y", "ANALOG_HY_OAS", "ANALOG_INDPRO",
            "ANALOG_T10YIE", "ANALOG_DGS10", "ANALOG_DGS2",
            "ANALOG_BAA", "ANALOG_MICH",
        }
        assert required.issubset(keys)
