"""qoq_pct трябва да е frequency-aware (parity с EU; гаси „3-тримесечна промяна" бъга)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.primitives import apply_transform


def test_qoq_pct_quarterly_uses_one_period():
    # Тримесечна серия: qoq = промяна спрямо 1 тримесечие назад, НЕ 3.
    idx = pd.date_range("2015-01-01", periods=20, freq="QS")
    s = pd.Series(np.arange(100, 120, dtype=float), index=idx)
    out = apply_transform(s, "qoq_pct").dropna()
    # последна точка 119 vs предходна 118 → ~0.847%
    assert out.iloc[-1] == pytest.approx((119 - 118) / 118 * 100, rel=1e-6)


def test_qoq_pct_monthly_uses_three_periods():
    # Месечна серия: 1 тримесечие = 3 месеца.
    idx = pd.date_range("2015-01-01", periods=24, freq="MS")
    s = pd.Series(np.arange(100, 124, dtype=float), index=idx)
    out = apply_transform(s, "qoq_pct").dropna()
    assert out.iloc[-1] == pytest.approx((123 - 120) / 120 * 100, rel=1e-6)
