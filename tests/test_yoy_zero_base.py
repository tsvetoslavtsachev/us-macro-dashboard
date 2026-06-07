"""Tests за zero/near-zero база guard в YoY/MoM/QoQ примитивите (нишка 7, латентно).

База минаваща през 0 (ratio/спред/нетна позиция) → pct_change ±inf (фалшив екстремум)
→ guard заменя с NaN. Безвредно за нивата-индекси днес; капан ако добавим zero-crossing
серия. Образец: EA_TOT_MONTHLY (replace inf) в briefing_context.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.primitives import yoy_pct, mom_pct, apply_transform


def make_monthly(vals, start="2010-01-01"):
    return pd.Series([float(v) for v in vals],
                     index=pd.date_range(start, periods=len(vals), freq="MS"))


def test_yoy_zero_base_is_nan_not_inf():
    # 13 месеца: база (м.0)=0, текущ (м.12)=5 → 5/0 → inf → guard → NaN
    out = yoy_pct(make_monthly([0.0] + [1.0] * 11 + [5.0]))
    assert not np.isinf(out.to_numpy()).any()
    assert pd.isna(out.iloc[-1])


def test_mom_zero_base_is_nan():
    out = mom_pct(make_monthly([0.0, 3.0]))
    assert not np.isinf(out.to_numpy()).any()
    assert pd.isna(out.iloc[-1])


def test_qoq_zero_base_is_nan():
    q = pd.Series([1.0, 1.0, 1.0, 0.0, 5.0, 1.0, 1.0, 1.0],
                  index=pd.date_range("2018-01-01", periods=8, freq="QS"))
    out = apply_transform(q, "qoq_pct")
    assert not np.isinf(out.to_numpy()).any()


def test_normal_series_unaffected():
    # нормална индекс-серия (база ~100) → guard НЕ променя нищо
    out = yoy_pct(make_monthly(list(range(100, 114))))
    assert out.dropna().notna().all()
    assert not np.isinf(out.to_numpy()).any()
    assert out.iloc[-1] == pytest.approx((113 / 101 - 1) * 100)
