"""
analysis/analog_comparison.py
=============================
Dimension-level диагностика на analog resemblance.

Дава отговор на "защо този analog прилича на сега?" — кои dims са
най-близки (similarity drivers) и кои най-далеч (divergences, където
паралелът се разпада). Това е честността на analog-а: не само един
similarity number, а explicit breakdown.

Функции:
    compare_dimensions(current_state, analog)
        → DimensionComparison със sorted similarities & divergences.

Прагове (soft):
    |Δz| < 0.5  — ~еднакви (tight match)
    |Δz| 0.5–1.0 — близки
    |Δz| > 1.0  — съществена разлика (може да е deal-breaker)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from analysis.analog_matcher import AnalogResult
from analysis.macro_vector import DIM_LABELS_BG, DIM_UNITS, MacroState, STATE_VECTOR_DIMS


# Прагове за класификация на dim divergence
TIGHT_MATCH_THRESHOLD = 0.5     # |Δz| < 0.5 → tight
DIVERGENCE_THRESHOLD = 1.0      # |Δz| > 1.0 → съществена разлика


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class DimensionDelta:
    """Разлика на една dim между current и analog."""
    dim: str
    label_bg: str
    current_raw: float
    analog_raw: float
    current_z: float
    analog_z: float
    z_diff: float               # analog − current (positive = analog е по-висок)
    abs_z_diff: float
    classification: str         # "tight" | "close" | "diverge"


@dataclass
class DimensionComparison:
    """Комплектен breakdown на един analog vs current."""
    similarities: list[DimensionDelta]  # sorted by abs_z_diff ascending (closest първи)
    divergences: list[DimensionDelta]   # само тези с abs_z_diff > DIVERGENCE_THRESHOLD


# ============================================================
# COMPARISON
# ============================================================

def _classify_delta(abs_z_diff: float) -> str:
    if abs_z_diff < TIGHT_MATCH_THRESHOLD:
        return "tight"
    if abs_z_diff < DIVERGENCE_THRESHOLD:
        return "close"
    return "diverge"


def compare_dimensions(
    current: MacroState,
    analog: AnalogResult,
) -> DimensionComparison:
    """За даден current state и analog, връща breakdown по всяка dim.

    Args:
        current: MacroState с raw + z.
        analog: AnalogResult с raw + z.

    Returns:
        DimensionComparison:
          - similarities: всичките dims сортирани по abs(z_diff) възходящо
                          (най-тясно съвпадащите първи)
          - divergences: само dims с abs(z_diff) > DIVERGENCE_THRESHOLD,
                         сортирани низходящо (най-съществената първа)
    """
    deltas: list[DimensionDelta] = []
    for dim in STATE_VECTOR_DIMS:
        if dim not in current.z or dim not in analog.z:
            continue
        cur_z = current.z[dim]
        ana_z = analog.z[dim]
        cur_raw = current.raw.get(dim, float("nan"))
        ana_raw = analog.raw.get(dim, float("nan"))
        z_diff = ana_z - cur_z
        abs_z = abs(z_diff)
        deltas.append(
            DimensionDelta(
                dim=dim,
                label_bg=DIM_LABELS_BG.get(dim, dim),
                current_raw=cur_raw,
                analog_raw=ana_raw,
                current_z=cur_z,
                analog_z=ana_z,
                z_diff=z_diff,
                abs_z_diff=abs_z,
                classification=_classify_delta(abs_z),
            )
        )

    similarities = sorted(deltas, key=lambda d: d.abs_z_diff)
    divergences = sorted(
        [d for d in deltas if d.abs_z_diff > DIVERGENCE_THRESHOLD],
        key=lambda d: d.abs_z_diff,
        reverse=True,
    )

    return DimensionComparison(
        similarities=similarities,
        divergences=divergences,
    )


# ============================================================
# HUMAN-READABLE FORMAT
# ============================================================

def format_delta_line(delta: DimensionDelta) -> str:
    """Един ред в БГ: "Безработица: 4.2% vs 4.1% (Δz=+0.1)".

    Ползва се от briefing template-а.
    """
    unit = DIM_UNITS.get(delta.dim, "")
    sign = "+" if delta.z_diff >= 0 else ""
    return (
        f"{delta.label_bg}: {delta.current_raw:.2f}{unit} "
        f"vs {delta.analog_raw:.2f}{unit} "
        f"(Δz={sign}{delta.z_diff:.2f})"
    )
