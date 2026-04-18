"""
analysis/analog_pipeline.py
===========================
End-to-end pipeline за Historical Analog Engine.

Орекстрира 4-те analog modula в едно извикване:

    fetched {ANALOG_KEY: pd.Series}
        → build_history_matrix
        → z_score_matrix
        → build_current_vector
        → find_analogs (top-k)
        → compare_dimensions (per analog)
        → forward_outcomes

Връща AnalogBundle — компактен data class, който briefing-ът рендирa.

Ако няма достатъчно history (current_vector=None) → връща None.
Това е по дизайн: при недостиг на данни, briefing-ът просто пропуска
"Исторически аналог" секцията, без да crash-ва.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from analysis.analog_comparison import DimensionComparison, compare_dimensions
from analysis.analog_matcher import AnalogResult, find_analogs
from analysis.forward_path import ForwardOutcomes, forward_outcomes
from analysis.macro_vector import (
    MacroState,
    build_current_vector,
    build_history_matrix,
    z_score_matrix,
)


# ============================================================
# BUNDLE
# ============================================================

@dataclass
class AnalogBundle:
    """Всичко, което briefing-ът трябва да покаже за analog section-а."""
    current_state: MacroState
    history_df: pd.DataFrame      # raw history (за forward values на sparklines)
    history_z: pd.DataFrame       # z-scored history
    analogs: list[AnalogResult]
    comparisons: list[DimensionComparison]  # len == len(analogs), ред същият
    forward: ForwardOutcomes


# ============================================================
# PIPELINE
# ============================================================

def compute_analog_bundle(
    fetched: dict[str, pd.Series],
    today: Optional[pd.Timestamp] = None,
    k: int = 3,
    min_gap_months: int = 12,
    exclude_last_months: int = 24,
    horizons_months: Optional[list[int]] = None,
    outcome_dims: Optional[list[str]] = None,
) -> Optional[AnalogBundle]:
    """End-to-end: fetched series → AnalogBundle.

    Args:
        fetched: dict със вси ANALOG_* ключове (виж macro_vector.ANALOG_FETCH_SPEC).
        today: Cut-off за current vector. Ако None, най-късната complete дата.
        k: Колко analog-а да върне (default 3).
        min_gap_months: Минимум месеци между избрани analog-и.
        exclude_last_months: Отрязва последните N месеца от search pool-а.
        horizons_months: Forward horizons (default [3, 6, 12]).
        outcome_dims: Dims за forward outcomes (default [unrate, core_cpi_yoy, real_ffr, yc_10y2y]).

    Returns:
        AnalogBundle или None ако няма complete-case ред в history.
    """
    history_df = build_history_matrix(fetched)
    history_z = z_score_matrix(history_df)

    current = build_current_vector(history_df, history_z, today)
    if current is None:
        return None

    analogs = find_analogs(
        history_df=history_df,
        history_z=history_z,
        current_z=current.as_array(),
        current_date=current.as_of,
        k=k,
        min_gap_months=min_gap_months,
        exclude_last_months=exclude_last_months,
    )

    comparisons = [compare_dimensions(current, a) for a in analogs]
    forward = forward_outcomes(
        history_df=history_df,
        analogs=analogs,
        horizons_months=horizons_months,
        outcome_dims=outcome_dims,
    )

    return AnalogBundle(
        current_state=current,
        history_df=history_df,
        history_z=history_z,
        analogs=analogs,
        comparisons=comparisons,
        forward=forward,
    )
