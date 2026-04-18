"""
analysis/divergence.py
======================
Два вида divergence:

1) Intra-lens — кои peer_groups вътре в една леща се разминават.
   Напр. labor: claims ↑ (weakening) vs wage_dynamics ↑ (tight) —
   чисто late-cycle signal.

2) Cross-lens — 5 canonical pairs от catalog/cross_lens_pairs.py.
   Всяка pair е икономическа теза; връща state + interpretation.

Без LLM, без narrative генериране. Чиста класификация по прагове.

Dependencies:
  - catalog.series: series_by_lens (за intra-lens enumeration)
  - catalog.cross_lens_pairs: CROSS_LENS_PAIRS config
  - core.primitives: breadth_positive
  - analysis.breadth: логика за grouping (reuse)
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import pandas as pd

from catalog.series import series_by_lens, ALLOWED_LENSES
from catalog.cross_lens_pairs import CROSS_LENS_PAIRS
from core.primitives import breadth_positive


# ============================================================
# THRESHOLDS (единствено място за tuning)
# ============================================================

BREADTH_HIGH = 0.6           # > 0.6 → групата е "up"
BREADTH_LOW = 0.4            # < 0.4 → групата е "down"
INTRA_NOTABLE_DIFF = 0.4     # |breadth_a - breadth_b| >= 0.4 → notable intra-divergence
MIN_PEER_GROUP_SIZE = 2      # под 2 налични серии → skip peer_group


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class IntraLensDivergence:
    lens: str
    group_a: str
    group_b: str
    breadth_a: float
    breadth_b: float
    diff: float                      # breadth_a - breadth_b
    interpretation: str              # human-readable

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("breadth_a", "breadth_b", "diff"):
            if isinstance(d[k], float) and np.isnan(d[k]):
                d[k] = None
        return d


@dataclass
class IntraLensDivergenceReport:
    lens: str
    as_of: Optional[str]
    divergences: list[IntraLensDivergence]  # sorted by |diff| desc

    def to_dict(self) -> dict:
        return {
            "lens": self.lens,
            "as_of": self.as_of,
            "divergences": [d.to_dict() for d in self.divergences],
        }


@dataclass
class CrossLensPairReading:
    pair_id: str
    name_bg: str
    question_bg: str
    slot_a_label: str
    slot_b_label: str
    breadth_a: float                 # aggregate 0..1 (invert-applied)
    breadth_b: float
    n_a_available: int               # union на налични серии в slot_a
    n_b_available: int
    state: str                       # both_up | both_down | a_up_b_down | a_down_b_up | transition | insufficient_data
    interpretation: str

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("breadth_a", "breadth_b"):
            if isinstance(d[k], float) and np.isnan(d[k]):
                d[k] = None
        return d


@dataclass
class CrossLensDivergenceReport:
    as_of: Optional[str]
    pairs: list[CrossLensPairReading]

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "pairs": [p.to_dict() for p in self.pairs],
        }


# ============================================================
# PUBLIC API — INTRA-LENS
# ============================================================

def compute_intra_lens_divergence(
    lens: str,
    snapshot: dict[str, pd.Series],
    notable_threshold: float = INTRA_NOTABLE_DIFF,
) -> IntraLensDivergenceReport:
    """Намира всички peer_group pairs в lens-а с notable divergence.

    Връща само двойките с |diff| >= notable_threshold, sorted по |diff| descending.
    Това е "highlight reel" — не пълен matrix (N*N/2 pairs).
    """
    if lens not in ALLOWED_LENSES:
        raise ValueError(f"Unknown lens '{lens}'. Allowed: {sorted(ALLOWED_LENSES)}")

    # Групираме каталожните ключове по peer_group
    entries = series_by_lens(lens)
    by_pg: dict[str, list[str]] = defaultdict(list)
    for e in entries:
        pg = e.get("peer_group")
        if pg:
            by_pg[pg].append(e["_key"])

    # Изчисляваме breadth за всеки peer_group (skip ако <2 налични)
    pg_breadths: dict[str, float] = {}
    for pg_name, keys in by_pg.items():
        available = _collect_available(keys, snapshot)
        if len(available) < MIN_PEER_GROUP_SIZE:
            continue
        bp = breadth_positive(available)
        if not np.isnan(bp):
            pg_breadths[pg_name] = bp

    # Всички двойки
    divergences: list[IntraLensDivergence] = []
    names = sorted(pg_breadths.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            diff = pg_breadths[a] - pg_breadths[b]
            if abs(diff) < notable_threshold:
                continue
            divergences.append(IntraLensDivergence(
                lens=lens,
                group_a=a,
                group_b=b,
                breadth_a=round(pg_breadths[a], 3),
                breadth_b=round(pg_breadths[b], 3),
                diff=round(diff, 3),
                interpretation=_intra_interpretation(a, b, pg_breadths[a], pg_breadths[b]),
            ))

    divergences.sort(key=lambda d: abs(d.diff), reverse=True)

    return IntraLensDivergenceReport(
        lens=lens,
        as_of=_compute_as_of(snapshot, [k for keys in by_pg.values() for k in keys]),
        divergences=divergences,
    )


# ============================================================
# PUBLIC API — CROSS-LENS
# ============================================================

def compute_cross_lens_divergence(
    snapshot: dict[str, pd.Series],
    pairs: Optional[list[dict]] = None,
) -> CrossLensDivergenceReport:
    """За всяка canonical pair, произвежда reading с state + interpretation."""
    if pairs is None:
        pairs = CROSS_LENS_PAIRS

    readings: list[CrossLensPairReading] = []
    all_relevant_keys: list[str] = []

    for pair in pairs:
        breadth_a, n_a, keys_a = _aggregate_slot_breadth(pair["slot_a"], snapshot)
        breadth_b, n_b, keys_b = _aggregate_slot_breadth(pair["slot_b"], snapshot)
        all_relevant_keys.extend(keys_a)
        all_relevant_keys.extend(keys_b)

        state = _classify_state(breadth_a, breadth_b)
        interp = pair["interpretations"].get(state, "—") if state != "insufficient_data" \
            else "Insufficient data в една от двете групи."

        readings.append(CrossLensPairReading(
            pair_id=pair["id"],
            name_bg=pair["name_bg"],
            question_bg=pair["question_bg"],
            slot_a_label=pair["slot_a"]["label"],
            slot_b_label=pair["slot_b"]["label"],
            breadth_a=round(breadth_a, 3) if not np.isnan(breadth_a) else float("nan"),
            breadth_b=round(breadth_b, 3) if not np.isnan(breadth_b) else float("nan"),
            n_a_available=n_a,
            n_b_available=n_b,
            state=state,
            interpretation=interp,
        ))

    return CrossLensDivergenceReport(
        as_of=_compute_as_of(snapshot, list(set(all_relevant_keys))),
        pairs=readings,
    )


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _collect_available(
    keys: list[str],
    snapshot: dict[str, pd.Series],
) -> dict[str, pd.Series]:
    """Връща серии от snapshot, чиито ключове са в keys И имат non-empty данни."""
    out: dict[str, pd.Series] = {}
    for k in keys:
        s = snapshot.get(k)
        if s is None:
            continue
        if s.dropna().empty:
            continue
        out[k] = s
    return out


def _aggregate_slot_breadth(
    slot: dict,
    snapshot: dict[str, pd.Series],
) -> tuple[float, int, list[str]]:
    """Average of per-peer_group breadth_positive, with invert applied.

    Returns:
        (aggregate_breadth, total_n_available, keys_touched)
    """
    lens = slot["lens"]
    peer_groups = slot["peer_groups"]
    invert_map: dict = slot.get("invert", {})

    entries = series_by_lens(lens)
    by_pg: dict[str, list[str]] = defaultdict(list)
    for e in entries:
        if e.get("peer_group") in peer_groups:
            by_pg[e["peer_group"]].append(e["_key"])

    group_breadths: list[float] = []
    n_available = 0
    keys_touched: list[str] = []

    for pg_name, keys in by_pg.items():
        keys_touched.extend(keys)
        available = _collect_available(keys, snapshot)
        if len(available) < MIN_PEER_GROUP_SIZE:
            continue
        bp = breadth_positive(available)
        if np.isnan(bp):
            continue
        if invert_map.get(pg_name):
            bp = 1.0 - bp
        group_breadths.append(bp)
        n_available += len(available)

    if not group_breadths:
        return float("nan"), 0, keys_touched

    return float(np.mean(group_breadths)), n_available, keys_touched


def _classify_state(breadth_a: float, breadth_b: float) -> str:
    """Категоризира двойка breadth-и в един от 6-те state-а."""
    if np.isnan(breadth_a) or np.isnan(breadth_b):
        return "insufficient_data"
    a_up = breadth_a > BREADTH_HIGH
    a_down = breadth_a < BREADTH_LOW
    b_up = breadth_b > BREADTH_HIGH
    b_down = breadth_b < BREADTH_LOW
    if a_up and b_up:
        return "both_up"
    if a_down and b_down:
        return "both_down"
    if a_up and b_down:
        return "a_up_b_down"
    if a_down and b_up:
        return "a_down_b_up"
    return "transition"


def _intra_interpretation(
    group_a: str,
    group_b: str,
    breadth_a: float,
    breadth_b: float,
) -> str:
    """Прост textual highlight за intra-lens двойка.

    Не претендира за икономическа дълбочина — просто информативна разлика.
    Briefing layer-ът може да го overrid-не с pair-specific narrative.
    """
    if breadth_a > breadth_b:
        return (f"{group_a} е по-силна ({breadth_a:.0%}) отколкото "
                f"{group_b} ({breadth_b:.0%}) — разминаване {breadth_a - breadth_b:+.0%}.")
    return (f"{group_b} е по-силна ({breadth_b:.0%}) отколкото "
            f"{group_a} ({breadth_a:.0%}) — разминаване {breadth_b - breadth_a:+.0%}.")


def _compute_as_of(
    snapshot: dict[str, pd.Series],
    keys: list[str],
) -> Optional[str]:
    """Най-скорошната дата сред релевантните серии."""
    dates: list[pd.Timestamp] = []
    for k in keys:
        s = snapshot.get(k)
        if s is None:
            continue
        s_clean = s.dropna()
        if s_clean.empty:
            continue
        last = s_clean.index[-1]
        if isinstance(last, pd.Timestamp):
            dates.append(last)
    if not dates:
        return None
    return max(dates).strftime("%Y-%m-%d")
