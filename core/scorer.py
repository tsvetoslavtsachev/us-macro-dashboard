"""
econ_v2 — Scorer
=================
Преобразува сурови FRED стойности в нормализирани scores (0–100).

Методология:
• percentile_rank(value, history) → 0–100 спрямо историческото разпределение
• invert=True → обръща логиката (висок unemployment = нисък score)
• z_score → колко стандартни отклонения от средната за периода

Всеки индикатор идва с:
  - score (0–100)
  - percentile (0–100)
  - z_score
  - current_value
  - last_date
  - yoy_change (%)
  - regime_label
"""

import numpy as np
import pandas as pd
from typing import Optional


def percentile_rank(current: float, history: pd.Series) -> float:
    """
    Колко процента от историческите стойности са ПО-НИСКИ от текущата.
    → 100 = текущата е по-висока от всичко виждано
    → 0   = текущата е по-ниска от всичко виждано
    """
    if len(history) == 0:
        return 50.0
    return float(np.sum(history < current) / len(history) * 100)


def z_score(current: float, history: pd.Series) -> float:
    """Стандартизирана стойност спрямо историческото разпределение."""
    if len(history) == 0 or history.std() == 0:
        return 0.0
    return float((current - history.mean()) / history.std())


def normalize(value: float, lo: float, hi: float, invert: bool = False) -> float:
    """
    Линейна нормализация към 0–100.
    lo → 0, hi → 100 (или обратното ако invert=True)
    """
    if hi == lo:
        return 50.0
    score = (value - lo) / (hi - lo) * 100
    score = max(0.0, min(100.0, score))
    return 100.0 - score if invert else score


def score_series(
    series: pd.Series,
    history_start: str = "2000-01-01",
    invert: bool = False,
    name: str = "",
) -> dict:
    """
    Главната функция — взима pandas Series, връща пълен score dict.

    invert=True: по-висока стойност → по-нисък score
    (напр. Unemployment Rate: висок = лошо за пазара на труда)
    """
    series = series.dropna()
    if len(series) == 0:
        return _empty_score(name)

    current_val = float(series.iloc[-1])
    last_date = str(series.index[-1].date())

    # Историческа база за percentile
    history = series[series.index >= pd.Timestamp(history_start)]

    pct = percentile_rank(current_val, history)
    z = z_score(current_val, history)

    # Score: percentile директно (или инвертиран)
    raw_score = pct if not invert else (100.0 - pct)
    score = round(raw_score, 1)

    # YoY промяна
    yoy = _calc_yoy(series)

    return {
        "name": name or series.name or "unknown",
        "score": score,
        "percentile": round(pct, 1),
        "z_score": round(z, 2),
        "current_value": round(current_val, 4),
        "last_date": last_date,
        "yoy_change": yoy,
        "invert": invert,
        "history_n": len(history),
    }


def composite_score(scores: list, weights: Optional[list] = None) -> float:
    """
    Weighted average на score dict-ове или директно числа.
    """
    if not scores:
        return 50.0

    vals = []
    for s in scores:
        if isinstance(s, dict):
            vals.append(s.get("score", 50.0))
        else:
            vals.append(float(s))

    if weights is None:
        weights = [1.0] * len(vals)

    total = sum(w * v for w, v in zip(weights, vals))
    return round(total / sum(weights), 1)


def get_regime(score: float, regimes: list) -> tuple:
    """
    Връща (label, color) за даден score спрямо regime таблица.
    regimes = [(threshold, label, color), ...] — сортирани низходящо по threshold
    """
    for threshold, label, color in sorted(regimes, reverse=True):
        if score >= threshold:
            return label, color
    return regimes[-1][1], regimes[-1][2]


def build_sparkline(series: pd.Series, months: int = 24) -> dict:
    """
    Връща последните N месеца като sparkline данни.
    """
    cutoff = pd.Timestamp.now() - pd.DateOffset(months=months)
    recent = series[series.index >= cutoff].dropna()
    if len(recent) == 0:
        return {"dates": [], "values": []}
    return {
        "dates": [str(d.date()) for d in recent.index],
        "values": [round(float(v), 4) for v in recent.values],
    }


def build_historical_context(series: pd.Series, current_val: float, history_start: str = "2000-01-01") -> dict:
    """
    Връща исторически контекст: min, max, mean, percentile band.
    """
    history = series[series.index >= pd.Timestamp(history_start)].dropna()
    if len(history) == 0:
        return {}
    return {
        "min": round(float(history.min()), 4),
        "max": round(float(history.max()), 4),
        "mean": round(float(history.mean()), 4),
        "median": round(float(history.median()), 4),
        "p25": round(float(history.quantile(0.25)), 4),
        "p75": round(float(history.quantile(0.75)), 4),
        "since": history_start,
        "n_obs": len(history),
    }


# ─── helpers ─────────────────────────────────────────────────────────────────

def _calc_yoy(series: pd.Series) -> Optional[float]:
    try:
        now = series.index[-1]
        year_ago = now - pd.DateOffset(years=1)
        past = series[series.index <= year_ago]
        if len(past) == 0:
            return None
        old_val = float(past.iloc[-1])
        cur_val = float(series.iloc[-1])
        if old_val == 0:
            return None
        return round((cur_val - old_val) / abs(old_val) * 100, 2)
    except Exception:
        return None


def _empty_score(name: str) -> dict:
    return {
        "name": name,
        "score": 50.0,
        "percentile": 50.0,
        "z_score": 0.0,
        "current_value": None,
        "last_date": None,
        "yoy_change": None,
        "invert": False,
        "history_n": 0,
    }
