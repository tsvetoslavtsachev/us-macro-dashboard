"""
core/primitives.py
==================
Чисти математически примитиви за икономически анализ.

Без I/O, без state, без external API calls. Само `pd.Series` → число/Series/dict.

Ползват се от analysis/ слоя (Фаза 2+) за breadth, divergence, anomaly и analog.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd


# ============================================================
# SERIES-LEVEL PRIMITIVES
# ============================================================

def z_score(series: pd.Series, window: Optional[int] = None) -> pd.Series:
    """Стандартизира серия (x - mean) / std.

    Args:
        series: Time-series с datetime index.
        window: Ако е зададен, rolling z-score; иначе full-sample.

    Returns:
        Series със същия index, z-score стойности.
    """
    s = series.dropna()
    if s.empty:
        return pd.Series(dtype=float)
    if window is None:
        mu = s.mean()
        sigma = s.std(ddof=0)
        if sigma == 0 or np.isnan(sigma):
            return pd.Series(0.0, index=s.index)
        return (s - mu) / sigma
    mu = s.rolling(window).mean()
    sigma = s.rolling(window).std(ddof=0)
    return (s - mu) / sigma


def percentile(series: pd.Series, window: Optional[int] = None) -> pd.Series:
    """Перцентилен ранг 0–100 на всяко наблюдение.

    NB: Тук като референтна информация, не като композитна оценка (FRAMEWORK.md).
    """
    s = series.dropna()
    if s.empty:
        return pd.Series(dtype=float)
    if window is None:
        return s.rank(pct=True) * 100
    return s.rolling(window).apply(
        lambda w: (pd.Series(w).rank(pct=True).iloc[-1]) * 100,
        raw=False,
    )


def momentum(series: pd.Series, periods: int) -> pd.Series:
    """Абсолютна промяна спрямо N периода назад.

    За YoY% използвай yoy_pct(); тази функция е суров delta.
    """
    s = series.dropna()
    return s.diff(periods=periods)


def acceleration(series: pd.Series, periods: int) -> pd.Series:
    """Второ производно: промяна в momentum-a.

    Полезно за "accelerating / decelerating" сигнали.
    """
    mom = momentum(series, periods)
    return mom.diff(periods=periods)


def yoy_pct(series: pd.Series) -> pd.Series:
    """Year-over-year процентна промяна.

    Автоматично определя frequency (monthly=12, weekly=52, daily=252).
    За custom периоди използвай pct_change директно.
    """
    s = series.dropna()
    if s.empty:
        return pd.Series(dtype=float)
    freq_periods = _infer_yoy_periods(s)
    # Zero/near-zero база guard: при база минаваща през 0 (ratio/спред/нетна позиция)
    # pct_change → ±inf (фалшив екстремум). Заменяме с NaN (легитимно "недефинирано").
    # Безвредно за нивата-индекси днес; образец EA_TOT_MONTHLY (briefing_context).
    return (s.pct_change(periods=freq_periods) * 100).replace([np.inf, -np.inf], np.nan)


def mom_pct(series: pd.Series) -> pd.Series:
    """Month-over-month процентна промяна."""
    return (series.dropna().pct_change(periods=1) * 100).replace([np.inf, -np.inf], np.nan)


def rolling_mean(series: pd.Series, window: int) -> pd.Series:
    """Rolling mean — за 4-седмични средни на claims, 3-месечни средни на NFP."""
    return series.dropna().rolling(window=window, min_periods=window).mean()


def first_diff(series: pd.Series, periods: int = 1) -> pd.Series:
    """Първо производно (за level серии — interest rates, unemployment rate)."""
    return series.dropna().diff(periods=periods)


def _infer_yoy_periods(series: pd.Series) -> int:
    """Познава frequency на серия и връща броя периоди за YoY."""
    idx = series.index
    if not isinstance(idx, pd.DatetimeIndex) or len(idx) < 4:
        return 12  # default fallback
    inferred = pd.infer_freq(idx)
    if inferred is None:
        # Estimate from median delta
        deltas = idx.to_series().diff().dt.days.dropna()
        if deltas.empty:
            return 12
        median_days = deltas.median()
        if median_days <= 2:
            return 252  # daily (business)
        if median_days <= 8:
            return 52   # weekly
        if median_days <= 35:
            return 12   # monthly
        return 4        # quarterly
    freq_char = inferred[0].upper() if inferred else "M"
    return {"D": 252, "B": 252, "W": 52, "M": 12, "Q": 4, "A": 1, "Y": 1}.get(freq_char, 12)


# ============================================================
# TRANSFORM + ROBUST STANDARDIZATION (lens health scoring)
# ============================================================
# Виж LENS_SCORING_METHODOLOGY.md — единен примитив за трите икономики.

def apply_transform(series: pd.Series, transform: str) -> pd.Series:
    """Прилага декларираната каталожна трансформация върху сурова серия.

    level → as-is; yoy_pct/mom_pct/qoq_pct → процентна промяна; first_diff → delta;
    z_score → full-sample z. Това гаси "breadth върху сурови нива" (дефект B):
    номинално растящите серии (CPI индекс, M2 ниво) се четат като ТЕМП, не ниво.
    """
    s = series.dropna()
    if s.empty:
        return s
    if transform == "yoy_pct":
        return yoy_pct(s)
    if transform == "mom_pct":
        return mom_pct(s)
    if transform == "qoq_pct":
        # Frequency-aware: тримесечно=1 период, месечно=3 (1 тримесечие). Гаси бъга
        # където pct_change(3) върху тримесечна серия даваше 3-тримесечна промяна.
        qp = max(1, _infer_yoy_periods(s) // 4)
        return (s.pct_change(periods=qp) * 100).replace([np.inf, -np.inf], np.nan)
    if transform == "first_diff":
        return first_diff(s)
    if transform == "z_score":
        return z_score(s)
    return s  # level


def robust_stats_latest(
    series: pd.Series,
    window_years: int = 10,
    min_obs: int = 36,
) -> Optional[tuple[float, float, float]]:
    """Робастна норма на последната точка спрямо плъзгащ прозорец.

    Връща (latest_value, median, scale), където scale = 1.4826 · MAD —
    σ-еквивалент, устойчив на кратки outlier-и (COVID). Прозорецът е последните
    `window_years` години ДО последното наблюдение (работи и за trim-нати snapshot-и).

    None ако серията има < min_obs точки в прозореца (твърде малко за норма).
    scale=0 (без вариация) → връща scale 0.0; повикващият третира като "на нормата".
    """
    s = series.dropna()
    if s.empty:
        return None
    if isinstance(s.index, pd.DatetimeIndex):
        cutoff = s.index[-1] - pd.DateOffset(years=window_years)
        w = s[s.index >= cutoff]
    else:
        w = s
    if len(w) < min_obs:
        return None
    med = float(w.median())
    mad = float((w - med).abs().median())
    scale = 1.4826 * mad
    return float(s.iloc[-1]), med, scale


def is_extreme_robust(
    series: pd.Series,
    transform: str = "level",
    z_threshold: float = 2.0,
    window_years: int = 10,
    min_obs: int = 36,
) -> Optional[bool]:
    """True ако |robust dev_sigma| на ТРАНСФОРМИРАНАТА серия > праг.

    Гаси дефект B (сурова full-sample z върху растящо ниво → вечен фалшив екстремум):
    прилага каталожния transform (напр. yoy_pct) и мери последната точка спрямо
    robust 10г норма (median ± 1.4826·MAD) — огледало на core.scorer/health.
    `scale==0` (без вариация) → False (на нормата, като _dev_sigma в scorer).
    None ако серията е по-къса от min_obs (недостатъчна норма → caller я skip-ва).
    """
    t = apply_transform(series, transform)
    stats = robust_stats_latest(t, window_years=window_years, min_obs=min_obs)
    if stats is None:
        return None
    latest, med, scale = stats
    if scale == 0 or np.isnan(scale):
        return False
    return abs((latest - med) / scale) > z_threshold


# ============================================================
# MAGNITUDE / SEVERITY (легибилност на отклонението — item F)
# ============================================================
# „Десет подвежда по магнитуд": 0–100 score-ът насища (tanh) и трупа дъното —
# −2σ → score ≈ 10, но и −8σ → score ≈ 0, така че „мек спад" не се различава от
# „крах". σ-магнитудът на отклонението носи информацията, която tanh трие.
# ЕДНА глобална скала за всички серии и трите икономики (σ е вече self-scaling по
# robust scale) — без per-series tuning, в духа на DIR_DEADBAND. НЕ влиза в score.
SEVERITY_EDGES = (1.0, 2.0, 3.0)                       # |σ| прагове
SEVERITY_LABELS = ("норма", "забележимо", "разпънато", "екстремно")


def severity_tier(dev_sigma: Optional[float]) -> Optional[str]:
    """|σ| отклонение от нормата/целта → глобален severity лейбъл (annotation).

    Полярностно-агностичен магнитуд: |dev_sigma| < 1 → норма; 1–2 → забележимо;
    2–3 → разпънато; ≥3 → екстремно. None → None (недостатъчно данни)."""
    if dev_sigma is None or (isinstance(dev_sigma, float) and np.isnan(dev_sigma)):
        return None
    a = abs(float(dev_sigma))
    if a < SEVERITY_EDGES[0]:
        return SEVERITY_LABELS[0]
    if a < SEVERITY_EDGES[1]:
        return SEVERITY_LABELS[1]
    if a < SEVERITY_EDGES[2]:
        return SEVERITY_LABELS[2]
    return SEVERITY_LABELS[3]


# ============================================================
# BREADTH PRIMITIVES (peer group level)
# ============================================================

def breadth_positive(
    group: dict[str, pd.Series],
    transform: str = "momentum",
    periods: int = 1,
) -> float:
    """Процент серии в група с положителен latest signal.

    Args:
        group: {series_id: pd.Series}
        transform: "momentum" (delta) или "level" (последна стойност спрямо mean)
        periods: За momentum — колко периода назад.

    Returns:
        float в [0, 1] — фракция положителни.
    """
    if not group:
        return float("nan")
    positives = 0
    valid = 0
    for _, s in group.items():
        latest = _latest_signal(s, transform, periods)
        if latest is None or np.isnan(latest):
            continue
        valid += 1
        if latest > 0:
            positives += 1
    return positives / valid if valid > 0 else float("nan")


def breadth_extreme(
    group: dict[str, pd.Series],
    transforms: Optional[dict[str, str]] = None,
    z_threshold: float = 2.0,
    min_obs: int = 36,
) -> float:
    """Процент серии в група с |robust dev_sigma| > threshold (transform-aware).

    Огледало на unified scorer: каталожен transform + robust 10г z вместо сурова
    full-sample z (която маркираше монотонно растящи нива — PAYEMS/USPRIV — като
    вечни фалшиви екстремуми). `transforms`: {series_id → caталожен transform};
    липсващ ключ → 'level'. Серия по-къса от min_obs се skip-ва от valid."""
    if not group:
        return float("nan")
    transforms = transforms or {}
    extreme = 0
    valid = 0
    for key, s in group.items():
        res = is_extreme_robust(s, transforms.get(key, "level"), z_threshold, min_obs=min_obs)
        if res is None:
            continue
        valid += 1
        if res:
            extreme += 1
    return extreme / valid if valid > 0 else float("nan")


def diffusion_index(
    group: dict[str, pd.Series],
    periods: int = 1,
) -> float:
    """Класически diffusion index: % increasing + 0.5 × % unchanged.

    Конвертиран към 0–100 скала (икономически стандарт).
    """
    if not group:
        return float("nan")
    increasing = 0
    unchanged = 0
    valid = 0
    for _, s in group.items():
        mom = _latest_signal(s, "momentum", periods)
        if mom is None or np.isnan(mom):
            continue
        valid += 1
        if mom > 0:
            increasing += 1
        elif mom == 0:
            unchanged += 1
    if valid == 0:
        return float("nan")
    return 100 * (increasing + 0.5 * unchanged) / valid


def _latest_signal(s: pd.Series, transform: str, periods: int) -> Optional[float]:
    """Helper: връща последната trend сигнална стойност."""
    s_clean = s.dropna()
    if len(s_clean) < max(2, periods + 1):
        return None
    if transform == "momentum":
        return s_clean.iloc[-1] - s_clean.iloc[-1 - periods]
    if transform == "level":
        return s_clean.iloc[-1] - s_clean.mean()
    return None


# ============================================================
# DIVERGENCE PRIMITIVES (cross-group)
# ============================================================

def divergence(
    group_a: dict[str, pd.Series],
    group_b: dict[str, pd.Series],
) -> float:
    """Разлика между агрегатните breadth сигнали на две групи.

    Положителна стойност: group_a е по-силна.
    Близо до 0: групите се движат заедно.
    """
    a = breadth_positive(group_a)
    b = breadth_positive(group_b)
    if np.isnan(a) or np.isnan(b):
        return float("nan")
    return a - b


# ============================================================
# ANOMALY DETECTION
# ============================================================

def anomaly_scan(
    series_dict: dict[str, pd.Series],
    z_threshold: float = 2.0,
) -> list[dict[str, Any]]:
    """Връща всички серии с |z_score(latest)| > threshold.

    Sort: по |z| descending.

    Returns:
        list of {series_id, z, direction ("+" or "-"), last_value, last_date}
    """
    results: list[dict[str, Any]] = []
    for series_id, s in series_dict.items():
        z = z_score(s)
        if z.empty:
            continue
        z_last = z.iloc[-1]
        if np.isnan(z_last):
            continue
        if abs(z_last) > z_threshold:
            results.append({
                "series_id": series_id,
                "z": round(float(z_last), 2),
                "direction": "+" if z_last > 0 else "-",
                "last_value": round(float(s.iloc[-1]), 4),
                "last_date": s.index[-1].strftime("%Y-%m-%d") if isinstance(s.index, pd.DatetimeIndex) else str(s.index[-1]),
            })
    return sorted(results, key=lambda r: abs(r["z"]), reverse=True)


def new_extreme(
    series: pd.Series,
    lookback_years: int = 5,
) -> Optional[dict[str, Any]]:
    """Проверява дали последното четене е нов max/min за lookback period."""
    s = series.dropna()
    if s.empty or not isinstance(s.index, pd.DatetimeIndex):
        return None
    cutoff = s.index[-1] - pd.DateOffset(years=lookback_years)
    window = s[s.index >= cutoff]
    if len(window) < 2:
        return None
    last_val = s.iloc[-1]
    if last_val == window.max():
        return {"direction": "max", "value": float(last_val), "lookback_years": lookback_years}
    if last_val == window.min():
        return {"direction": "min", "value": float(last_val), "lookback_years": lookback_years}
    return None
