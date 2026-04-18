"""
analysis/analog_matcher.py
==========================
Cosine similarity analog search над 8-dim macro state history.

Функция `find_analogs` дава top-k исторически месеци, най-близки до
настоящия macro state, с два guard-rail-а:

  (a) `exclude_last_months`: отхвърля последните N месеца от search pool-а
      (за да не върне "миналия юни" като аналог на "днес")
  (b) `min_gap_months`: изисква поне N месеца между избрани аналози
      (за да не върне 5 последователни месеца от един епизод)

Ред на избор: greedy — най-високата cosine similarity първа, след което
се suppresса window ±min_gap_months около нея; повтаря до k избрани.

Output включва човешки narrative label ("1979-Q1: Volcker / Oil Shock II")
ако аналогният месец попада в известен исторически епизод. Лейбълите са
конзервативно маркирани — ако не попада в known range, label=None.

Cosine прагове (soft):
  > 0.90 — много силен analog
  0.70–0.90 — добър analog
  0.50–0.70 — слаб analog (ползвай с caveat)
  < 0.50 — практически няма analog (рядко явление)

Тези прагове не са hard cutoff-и; функцията винаги връща top-k. Caller
решава дали да ги филтрира. В briefing-а показваме top-3 и отбелязваме
силата.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


# ============================================================
# HISTORICAL EPISODE LABELS
# ============================================================

# Известни макро-епизоди; label-ът излиза в briefing-а до датата
# на analog-а. Краищата са inclusive. Ако един месец попада в
# няколко епизода (рядко) — първата в списъка печели.
HISTORICAL_EPISODES: list[dict] = [
    {"label": "Oil shock I / Stagflation",      "start": "1973-11-01", "end": "1975-03-01"},
    {"label": "Oil shock II / Pre-Volcker",     "start": "1978-07-01", "end": "1979-10-01"},
    {"label": "Volcker disinflation",           "start": "1979-10-01", "end": "1982-11-01"},
    {"label": "Late-80s expansion",             "start": "1983-01-01", "end": "1989-06-01"},
    {"label": "S&L crisis / Early-90s",         "start": "1989-07-01", "end": "1991-06-01"},
    {"label": "90s expansion (pre-Asia)",       "start": "1991-07-01", "end": "1997-06-01"},
    {"label": "Asia crisis / LTCM",             "start": "1997-07-01", "end": "1998-12-01"},
    {"label": "Late 90s boom",                  "start": "1999-01-01", "end": "2000-03-01"},
    {"label": "Dotcom bust",                    "start": "2000-04-01", "end": "2001-11-01"},
    {"label": "Early 2000s reflation",          "start": "2002-01-01" , "end": "2006-12-01"},
    {"label": "Pre-GFC / Credit crunch",        "start": "2007-01-01", "end": "2007-11-01"},
    {"label": "GFC / Great Recession",          "start": "2007-12-01", "end": "2009-06-01"},
    {"label": "Post-GFC recovery",              "start": "2009-07-01", "end": "2011-07-01"},
    {"label": "EU sovereign crisis",            "start": "2011-08-01", "end": "2012-09-01"},
    {"label": "Taper tantrum era",              "start": "2013-05-01", "end": "2014-06-01"},
    {"label": "China/Oil collapse",             "start": "2015-07-01", "end": "2016-06-01"},
    {"label": "Trump reflation",                "start": "2016-11-01", "end": "2018-09-01"},
    {"label": "Q4 2018 / End of hiking cycle",  "start": "2018-10-01", "end": "2019-06-01"},
    {"label": "Late-cycle 2019",                "start": "2019-07-01", "end": "2020-01-01"},
    {"label": "COVID shock",                    "start": "2020-02-01", "end": "2020-06-01"},
    {"label": "COVID reopening",                "start": "2020-07-01", "end": "2021-12-01"},
    {"label": "Inflation shock / Fed hiking",   "start": "2022-01-01", "end": "2023-07-01"},
    {"label": "Disinflation / Soft landing",    "start": "2023-08-01", "end": "2024-09-01"},
    # 2024-10+ изрично не е labeled; остава current regime (който
    # exclude_last_months bars ще отрежат)
]


def lookup_episode(date: pd.Timestamp) -> Optional[str]:
    """Намира narrative label за дадена дата или None, ако не е в known range."""
    for ep in HISTORICAL_EPISODES:
        start = pd.Timestamp(ep["start"])
        end = pd.Timestamp(ep["end"])
        if start <= date <= end:
            return ep["label"]
    return None


# ============================================================
# DATA CLASS
# ============================================================

@dataclass
class AnalogResult:
    """Един historical analog."""
    date: pd.Timestamp
    similarity: float              # cosine, в [-1, 1]
    rank: int                      # 1..k, 1 = най-добър
    raw: dict[str, float]          # raw values на analog-а
    z: dict[str, float]            # z-scored values
    episode_label: Optional[str]   # narrative епизод или None


# ============================================================
# COSINE SIMILARITY
# ============================================================

def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity на два вектора със същата размерност.

    Връща 0.0 при zero-vector (защитна стойност).
    """
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _cosine_vs_matrix(current: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Vectorized cosine similarity: current (D,) vs matrix (N, D) → array (N,)."""
    # Нормализираме всички редове + current-а
    row_norms = np.linalg.norm(matrix, axis=1)
    cur_norm = np.linalg.norm(current)
    if cur_norm == 0.0:
        return np.zeros(matrix.shape[0])
    # dot products
    dots = matrix @ current
    # guard срещу zero rows
    safe_norms = np.where(row_norms == 0.0, 1.0, row_norms)
    cos = dots / (safe_norms * cur_norm)
    cos[row_norms == 0.0] = 0.0
    return cos


# ============================================================
# GREEDY TOP-K WITH MIN GAP
# ============================================================

def _greedy_topk(
    similarities: pd.Series,
    k: int,
    min_gap_months: int,
) -> list[tuple[pd.Timestamp, float]]:
    """Greedy selection: винаги вземи най-високата оставаща similarity,
    после maskни window ±min_gap_months около нея, повтори до k избрани.

    Args:
        similarities: pd.Series индексирана по дата, стойности = cosine.
        k: колко analog-а да върне максимум.
        min_gap_months: минимум разстояние в месеци между избрани.

    Returns:
        Списък [(date, similarity), ...] сортиран по similarity низходящо.
    """
    remaining = similarities.copy().dropna()
    selected: list[tuple[pd.Timestamp, float]] = []

    gap = pd.DateOffset(months=min_gap_months)
    while len(selected) < k and not remaining.empty:
        top_date = remaining.idxmax()
        top_sim = float(remaining.loc[top_date])
        selected.append((top_date, top_sim))

        # Suppress ±gap около top_date
        mask = (remaining.index >= top_date - gap) & (remaining.index <= top_date + gap)
        remaining = remaining.loc[~mask]

    return selected


# ============================================================
# PUBLIC API
# ============================================================

def find_analogs(
    history_df: pd.DataFrame,
    history_z: pd.DataFrame,
    current_z: np.ndarray,
    current_date: pd.Timestamp,
    k: int = 5,
    min_gap_months: int = 12,
    exclude_last_months: int = 24,
) -> list[AnalogResult]:
    """Top-k historical analogs за текущия macro state.

    Args:
        history_df: raw matrix (за показ на raw values в резултата).
        history_z: z-scored matrix (за similarity computation).
        current_z: np.ndarray (D,) = текущият z-scored vector.
        current_date: pd.Timestamp на текущия state (за exclude_last_months filter).
        k: колко analog-а да върне (default 5).
        min_gap_months: минимум разстояние между избрани analog-а.
        exclude_last_months: отхвърля последните N месеца от search pool-а.

    Returns:
        Списък от AnalogResult, сортирани по similarity низходящо.
        Празен списък ако history_z няма complete cases.
    """
    z_complete = history_z.dropna()
    if z_complete.empty:
        return []

    # Exclude последните N месеца
    cutoff = current_date - pd.DateOffset(months=exclude_last_months)
    z_pool = z_complete.loc[z_complete.index <= cutoff]
    if z_pool.empty:
        return []

    # Compute cosine vs всеки ред от pool-а
    matrix = z_pool.values  # (N, D)
    sims = _cosine_vs_matrix(current_z, matrix)
    sim_series = pd.Series(sims, index=z_pool.index)

    # Greedy top-k with gap constraint
    top_pairs = _greedy_topk(sim_series, k=k, min_gap_months=min_gap_months)

    results: list[AnalogResult] = []
    for rank, (date, sim) in enumerate(top_pairs, start=1):
        raw_row = history_df.loc[date] if date in history_df.index else pd.Series()
        z_row = history_z.loc[date] if date in history_z.index else pd.Series()
        results.append(
            AnalogResult(
                date=date,
                similarity=sim,
                rank=rank,
                raw={c: float(raw_row[c]) for c in history_df.columns if c in raw_row.index and pd.notna(raw_row[c])},
                z={c: float(z_row[c]) for c in history_z.columns if c in z_row.index and pd.notna(z_row[c])},
                episode_label=lookup_episode(date),
            )
        )

    return results


# ============================================================
# STRENGTH CLASSIFICATION
# ============================================================

def classify_strength(similarity: float) -> str:
    """Превежда cosine similarity в словесна оценка.

    - strong:   > 0.90 — много близко съвпадение
    - good:     0.70–0.90
    - weak:     0.50–0.70
    - marginal: < 0.50 — практически няма analog
    """
    if similarity > 0.90:
        return "strong"
    if similarity > 0.70:
        return "good"
    if similarity > 0.50:
        return "weak"
    return "marginal"


STRENGTH_LABELS_BG: dict[str, str] = {
    "strong":   "много силен",
    "good":     "добър",
    "weak":     "слаб",
    "marginal": "маргинален",
}
