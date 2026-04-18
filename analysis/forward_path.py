"""
analysis/forward_path.py
========================
Forward outcomes: какво се е случило 3/6/12 месеца след всеки analog.

Фокус върху икономически исходи (UNRATE, core CPI YoY, real FFR, 10Y-2Y),
НЕ asset prices. Причината: asset returns са noisy, regime-dependent, и
прилагат малък sample (3-5 analogs) в analog базата. Икономическите
isoодят са ковариантни на analog setup-а и много по-interpretable.

Функции:
    forward_outcomes(history_df, analogs, horizons_months, outcome_dims)
        → ForwardOutcomes със per-analog и aggregate (median/min/max) values.

Caveats (документирани в briefing-а):
    * Sample size = len(analogs). Малко observations → широки ranges.
    * Различни regime structures: политики, institutions, markets
      са се развили значително. "Същият" macro state в 1974 и 2022
      може да даде различен forward path.
    * Forward values включват и бъдещи аномалии (war, COVID, etc.).
      Медианата е по-robust от mean-а.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from analysis.analog_matcher import AnalogResult


DEFAULT_HORIZONS_MONTHS: list[int] = [3, 6, 12]
DEFAULT_OUTCOME_DIMS: list[str] = ["unrate", "core_cpi_yoy", "real_ffr", "yc_10y2y"]


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class PerAnalogForward:
    """Forward values на един analog за всички horizons."""
    analog_date: pd.Timestamp
    episode_label: Optional[str]
    # {dim: {horizon_months: value_after_horizon}}
    values: dict[str, dict[int, float]]
    # {dim: {horizon_months: value_at_horizon − value_at_analog}}
    deltas: dict[str, dict[int, float]]


@dataclass
class HorizonSummary:
    """Aggregate (median / min / max) за един dim × horizon през analogs."""
    dim: str
    horizon_months: int
    n: int                              # колко analog-а имат valid forward
    median_value: Optional[float]
    min_value: Optional[float]
    max_value: Optional[float]
    median_delta: Optional[float]
    min_delta: Optional[float]
    max_delta: Optional[float]


@dataclass
class ForwardOutcomes:
    """Пълен output от forward_outcomes."""
    per_analog: list[PerAnalogForward]
    aggregates: list[HorizonSummary]  # dim × horizon combos
    horizons: list[int]
    dims: list[str]


# ============================================================
# CORE
# ============================================================

def _forward_value(series: pd.Series, anchor: pd.Timestamp, horizon_months: int) -> Optional[float]:
    """Стойност на серия N месеца след anchor.

    Търси най-близкия month-end към anchor + N месеца. Ако няма
    валидна стойност, връща None (analog е твърде близо до края на
    history-я за този horizon).
    """
    target = anchor + pd.DateOffset(months=horizon_months)
    valid = series.dropna()
    if valid.empty:
        return None
    # Намираме последното наблюдение ≤ target; ако е в +/-45 дни window, OK.
    candidates = valid.loc[valid.index <= target]
    if candidates.empty:
        return None
    nearest = candidates.index[-1]
    # Ако nearest е > 45 дни от target, значи по-късна дата не съществува
    # и не можем да говорим за "N месеца напред" — връщаме None.
    gap_days = (target - nearest).days
    if gap_days > 45:
        return None
    return float(valid.loc[nearest])


def forward_outcomes(
    history_df: pd.DataFrame,
    analogs: list[AnalogResult],
    horizons_months: Optional[list[int]] = None,
    outcome_dims: Optional[list[str]] = None,
) -> ForwardOutcomes:
    """Строи forward outcomes matrix + aggregates.

    Args:
        history_df: raw history matrix (колоните съдържат outcome dims).
        analogs: списък от AnalogResult.
        horizons_months: default [3, 6, 12].
        outcome_dims: default ["unrate", "core_cpi_yoy", "real_ffr", "yc_10y2y"].

    Returns:
        ForwardOutcomes с per_analog records + aggregates.
    """
    horizons = list(horizons_months) if horizons_months else list(DEFAULT_HORIZONS_MONTHS)
    dims = list(outcome_dims) if outcome_dims else list(DEFAULT_OUTCOME_DIMS)

    # Филтрираме dims, които съществуват в history_df
    dims = [d for d in dims if d in history_df.columns]

    per_analog: list[PerAnalogForward] = []
    # За aggregates: {(dim, horizon): [values, deltas]}
    collect_values: dict[tuple[str, int], list[float]] = {}
    collect_deltas: dict[tuple[str, int], list[float]] = {}

    for a in analogs:
        anchor = a.date
        anchor_values = {
            d: float(history_df.loc[anchor, d]) if anchor in history_df.index and pd.notna(history_df.loc[anchor, d]) else float("nan")
            for d in dims
        }

        per_values: dict[str, dict[int, float]] = {}
        per_deltas: dict[str, dict[int, float]] = {}
        for d in dims:
            series = history_df[d]
            per_values[d] = {}
            per_deltas[d] = {}
            for h in horizons:
                v = _forward_value(series, anchor, h)
                if v is None:
                    continue
                per_values[d][h] = v
                anchor_val = anchor_values[d]
                if not np.isnan(anchor_val):
                    delta = v - anchor_val
                    per_deltas[d][h] = delta
                    collect_values.setdefault((d, h), []).append(v)
                    collect_deltas.setdefault((d, h), []).append(delta)
                else:
                    collect_values.setdefault((d, h), []).append(v)

        per_analog.append(PerAnalogForward(
            analog_date=anchor,
            episode_label=a.episode_label,
            values=per_values,
            deltas=per_deltas,
        ))

    aggregates: list[HorizonSummary] = []
    for d in dims:
        for h in horizons:
            vals = collect_values.get((d, h), [])
            deltas = collect_deltas.get((d, h), [])
            if vals:
                agg = HorizonSummary(
                    dim=d,
                    horizon_months=h,
                    n=len(vals),
                    median_value=float(np.median(vals)),
                    min_value=float(np.min(vals)),
                    max_value=float(np.max(vals)),
                    median_delta=float(np.median(deltas)) if deltas else None,
                    min_delta=float(np.min(deltas)) if deltas else None,
                    max_delta=float(np.max(deltas)) if deltas else None,
                )
            else:
                agg = HorizonSummary(
                    dim=d,
                    horizon_months=h,
                    n=0,
                    median_value=None,
                    min_value=None,
                    max_value=None,
                    median_delta=None,
                    min_delta=None,
                    max_delta=None,
                )
            aggregates.append(agg)

    return ForwardOutcomes(
        per_analog=per_analog,
        aggregates=aggregates,
        horizons=horizons,
        dims=dims,
    )
