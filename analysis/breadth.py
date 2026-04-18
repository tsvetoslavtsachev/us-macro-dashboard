"""
analysis/breadth.py
===================
Lens-level breadth отчет.

За всяка леща (labor, growth, inflation, liquidity) и даден snapshot от серии,
изчислява breadth метриките за всеки peer_group, който принадлежи към лещата.

Dependencies:
  - catalog.series — за peer_group composition (декларативна истина)
  - core.primitives — за breadth_positive, breadth_extreme, z_score

Изход (dataclass):
  LensBreadthReport
    ├── lens: str
    ├── as_of: str (ISO дата — най-скорошната наблюдавана точка)
    └── peer_groups: list[PeerGroupBreadth]
          ├── name, n_members, n_available
          ├── breadth_positive, breadth_extreme
          ├── direction ("expanding" / "contracting" / "mixed" / "insufficient_data")
          ├── extreme_members (series ключове с |z|>2)
          └── missing_members (каталожни ключове без данни в snapshot-a)

Правила:
  - peer_group с <2 налични серии → direction="insufficient_data", breadth=NaN.
    Това е safety net; в нормалното състояние след Phase 2.5 всички peer_groups
    имат поне 2 членове в каталога. Но ако snapshot е частичен (FRED не е отговорил
    за някоя серия), да не произведем deceptive breadth от 1 серия.
  - Прагове за `direction`:
      > 0.6 → "expanding" (повечето серии в групата движат заедно нагоре)
      < 0.4 → "contracting" (повечето надолу)
      иначе → "mixed"
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import pandas as pd

from catalog.series import series_by_lens, ALLOWED_LENSES
from core.primitives import breadth_positive, breadth_extreme, z_score


# ============================================================
# THRESHOLDS (икономически калибровани; единствено място за tuning)
# ============================================================

BREADTH_EXPANDING_THRESHOLD = 0.6  # > 60% positive → expanding
BREADTH_CONTRACTING_THRESHOLD = 0.4  # < 40% positive → contracting
Z_EXTREME_THRESHOLD = 2.0


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class PeerGroupBreadth:
    name: str
    n_members: int                    # брой записи в каталога
    n_available: int                  # брой серии с реални данни в snapshot-a
    breadth_positive: float           # 0..1, или NaN
    breadth_extreme: float            # 0..1, или NaN
    direction: str                    # "expanding" | "contracting" | "mixed" | "insufficient_data"
    extreme_members: list[str] = field(default_factory=list)
    missing_members: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        # JSON не обича NaN; конвертираме явно
        for k in ("breadth_positive", "breadth_extreme"):
            if isinstance(d[k], float) and np.isnan(d[k]):
                d[k] = None
        return d


@dataclass
class LensBreadthReport:
    lens: str
    as_of: Optional[str]              # ISO дата (YYYY-MM-DD), или None ако snapshot е празен
    peer_groups: list[PeerGroupBreadth]

    def to_dict(self) -> dict:
        return {
            "lens": self.lens,
            "as_of": self.as_of,
            "peer_groups": [pg.to_dict() for pg in self.peer_groups],
        }


# ============================================================
# PUBLIC API
# ============================================================

def compute_lens_breadth(
    lens: str,
    snapshot: dict[str, pd.Series],
) -> LensBreadthReport:
    """Сглобява lens-level breadth отчет.

    Args:
        lens: една от ALLOWED_LENSES ("labor"/"growth"/"inflation"/"liquidity"/"housing").
        snapshot: {series_key → pd.Series} — каталожен ключ, не FRED ID.

    Returns:
        LensBreadthReport с по един PeerGroupBreadth на peer_group.
        peer_groups е сортиран алфабетно по name за детерминистичен output.

    Raises:
        ValueError: ако lens не е в ALLOWED_LENSES.
    """
    if lens not in ALLOWED_LENSES:
        raise ValueError(
            f"Unknown lens '{lens}'. Allowed: {sorted(ALLOWED_LENSES)}"
        )

    catalog_entries = series_by_lens(lens)

    # Групираме каталожни ключове по peer_group
    by_pg: dict[str, list[str]] = defaultdict(list)
    for entry in catalog_entries:
        pg = entry.get("peer_group")
        if pg:
            by_pg[pg].append(entry["_key"])

    peer_reports: list[PeerGroupBreadth] = []
    for pg_name in sorted(by_pg.keys()):
        keys = by_pg[pg_name]
        peer_reports.append(_compute_peer_group_breadth(pg_name, keys, snapshot))

    return LensBreadthReport(
        lens=lens,
        as_of=_compute_as_of(snapshot, [k for keys in by_pg.values() for k in keys]),
        peer_groups=peer_reports,
    )


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _compute_peer_group_breadth(
    pg_name: str,
    catalog_keys: list[str],
    snapshot: dict[str, pd.Series],
) -> PeerGroupBreadth:
    """Изчислява breadth за един peer_group."""
    n_members = len(catalog_keys)

    # Разделяме available vs missing
    available: dict[str, pd.Series] = {}
    missing: list[str] = []
    for k in catalog_keys:
        s = snapshot.get(k)
        if s is None or s.dropna().empty:
            missing.append(k)
        else:
            available[k] = s

    if len(available) < 2:
        # Safety net: по-малко от 2 серии не дава смислен breadth сигнал
        return PeerGroupBreadth(
            name=pg_name,
            n_members=n_members,
            n_available=len(available),
            breadth_positive=float("nan"),
            breadth_extreme=float("nan"),
            direction="insufficient_data",
            extreme_members=[],
            missing_members=sorted(missing),
        )

    bp = breadth_positive(available)
    be = breadth_extreme(available, z_threshold=Z_EXTREME_THRESHOLD)
    extremes = _identify_extreme_members(available, z_threshold=Z_EXTREME_THRESHOLD)
    direction = _classify_direction(bp)

    return PeerGroupBreadth(
        name=pg_name,
        n_members=n_members,
        n_available=len(available),
        breadth_positive=round(float(bp), 3) if not np.isnan(bp) else float("nan"),
        breadth_extreme=round(float(be), 3) if not np.isnan(be) else float("nan"),
        direction=direction,
        extreme_members=sorted(extremes),
        missing_members=sorted(missing),
    )


def _identify_extreme_members(
    group: dict[str, pd.Series],
    z_threshold: float = 2.0,
) -> list[str]:
    """Връща ключовете на серии с |z_score(latest)| > threshold."""
    extremes: list[str] = []
    for k, s in group.items():
        z = z_score(s)
        if z.empty:
            continue
        z_last = z.iloc[-1]
        if np.isnan(z_last):
            continue
        if abs(z_last) > z_threshold:
            extremes.append(k)
    return extremes


def _classify_direction(breadth_positive_value: float) -> str:
    """Маппва числовия breadth в текстова посока."""
    if np.isnan(breadth_positive_value):
        return "insufficient_data"
    if breadth_positive_value > BREADTH_EXPANDING_THRESHOLD:
        return "expanding"
    if breadth_positive_value < BREADTH_CONTRACTING_THRESHOLD:
        return "contracting"
    return "mixed"


def _compute_as_of(
    snapshot: dict[str, pd.Series],
    relevant_keys: list[str],
) -> Optional[str]:
    """Най-скорошната наблюдавана дата сред релевантните серии.

    Защото сериите имат различни release schedules (weekly claims vs monthly CPI),
    "as_of" е max(last_date), не min. Това отразява "последна информация достигнала
    briefing-a".
    """
    dates: list[pd.Timestamp] = []
    for k in relevant_keys:
        s = snapshot.get(k)
        if s is None:
            continue
        s_clean = s.dropna()
        if s_clean.empty:
            continue
        last_idx = s_clean.index[-1]
        if isinstance(last_idx, pd.Timestamp):
            dates.append(last_idx)
    if not dates:
        return None
    return max(dates).strftime("%Y-%m-%d")
