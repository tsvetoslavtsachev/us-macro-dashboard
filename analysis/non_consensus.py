"""
analysis/non_consensus.py
=========================
Триажира tagged серии (`non_consensus`, `ai_exposure`, `structural`) и surface-ва
тези, които произвеждат сигнал — не просто листване на целия tag-нат каталог.

Тагнатите серии са тезен избор (AI замества entry-level labor; supply chain
индикатори водят headline-а; share-ове structural shift-ват). Без триаж тези
23 серии биха наводнили briefing-а с тихи редове. Тук решаваме кое *в момента*
прави нещо различно.

Сигнални критерии:
  1. |z_score(latest)| > Z_THRESHOLD (екстремум спрямо собствена история)
  2. Peer deviation — знакът на последния momentum е противоположен на breadth-а
     на peer_group-а (изчислен БЕЗ самата серия, за да няма циркулярност)

Signal strength:
  high    — и двете
  medium  — само едно
  low     — нито едно (серията остава в by_tag feed-а, но не в highlights)

Изход (dataclass):
  NonConsensusReport
    ├── as_of: str (ISO)
    ├── by_tag: {tag → [Reading, ...]}   # серия може да фигурира в няколко tag-а
    └── highlights: [Reading, ...]       # dedupe-нат union, сортиран по сила

Dependencies:
  - catalog.series — source of truth за tag-овете
  - core.primitives — z_score, momentum, breadth_positive
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import pandas as pd

from catalog.series import (
    ALLOWED_TAGS,
    series_by_tag,
    series_by_peer_group,
)
from core.primitives import z_score, momentum, breadth_positive


# ============================================================
# THRESHOLDS
# ============================================================

Z_THRESHOLD = 2.0                    # |z| > 2 → "екстремум"
PEER_UP_THRESHOLD = 0.6              # breadth > 0.6 → peer_group е "up"
PEER_DOWN_THRESHOLD = 0.4            # breadth < 0.4 → peer_group е "down"
MIN_PEER_SIZE_FOR_DEVIATION = 2      # под 2 остатъчни peer-а → не можем да кажем дали има deviation


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class NonConsensusReading:
    series_key: str
    series_name_bg: str
    lens: list[str]
    peer_group: str
    tags: list[str]
    last_value: float
    last_date: Optional[str]
    z_score: float                   # latest z (full sample)
    momentum_1m: float               # последен период промяна
    peer_breadth: float              # breadth_positive на peer_group БЕЗ самата серия; NaN ако insufficient
    peer_direction: str              # "up" | "down" | "mixed" | "insufficient"
    deviates_from_peers: bool
    signal_strength: str             # "high" | "medium" | "low"
    narrative_hint: str

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("last_value", "z_score", "momentum_1m", "peer_breadth"):
            if isinstance(d[k], float) and np.isnan(d[k]):
                d[k] = None
        return d


@dataclass
class NonConsensusReport:
    as_of: Optional[str]
    by_tag: dict[str, list[NonConsensusReading]] = field(default_factory=dict)
    highlights: list[NonConsensusReading] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "by_tag": {
                tag: [r.to_dict() for r in readings]
                for tag, readings in self.by_tag.items()
            },
            "highlights": [r.to_dict() for r in self.highlights],
        }


# ============================================================
# PUBLIC API
# ============================================================

def compute_non_consensus(
    snapshot: dict[str, pd.Series],
    z_threshold: float = Z_THRESHOLD,
) -> NonConsensusReport:
    """Построява NonConsensusReport за всички tagged серии в каталога.

    Args:
        snapshot: {series_key → pd.Series} (каталожен ключ, не FRED ID).
        z_threshold: праг за |z_score| → "екстремум".

    Returns:
        NonConsensusReport с:
          - by_tag: всяка tagged серия се появява във всеки свой tag
          - highlights: dedupe-нат топ списък, сортиран по signal_strength и |z|
    """
    # Кешираме reading-а по series_key, за да не сметнем два пъти
    # (TEMPHELPS/USINFO са и non_consensus, и ai_exposure)
    readings_by_key: dict[str, NonConsensusReading] = {}

    for tag in sorted(ALLOWED_TAGS):
        for entry in series_by_tag(tag):
            key = entry["_key"]
            if key in readings_by_key:
                continue
            readings_by_key[key] = _build_reading(entry, snapshot, z_threshold)

    # by_tag: листваме серия във всеки неин tag
    by_tag: dict[str, list[NonConsensusReading]] = defaultdict(list)
    for r in readings_by_key.values():
        for t in r.tags:
            if t in ALLOWED_TAGS:
                by_tag[t].append(r)

    # Сортираме вътре във всеки tag по signal strength + |z|
    for t in by_tag:
        by_tag[t].sort(key=_sort_key, reverse=True)

    # Highlights: union, dedupe, отрязваме до high/medium
    highlights = [
        r for r in readings_by_key.values()
        if r.signal_strength in ("high", "medium")
    ]
    highlights.sort(key=_sort_key, reverse=True)

    as_of = _compute_as_of(snapshot, list(readings_by_key.keys()))

    return NonConsensusReport(
        as_of=as_of,
        by_tag=dict(by_tag),
        highlights=highlights,
    )


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _build_reading(
    entry: dict,
    snapshot: dict[str, pd.Series],
    z_threshold: float,
) -> NonConsensusReading:
    """Изгражда един Reading за tagged серия."""
    key = entry["_key"]
    series = snapshot.get(key)

    # Default "insufficient" stub, ако липсват данни
    if series is None or series.dropna().empty:
        return NonConsensusReading(
            series_key=key,
            series_name_bg=entry.get("name_bg", key),
            lens=list(entry.get("lens", [])),
            peer_group=entry.get("peer_group", ""),
            tags=list(entry.get("tags", [])),
            last_value=float("nan"),
            last_date=None,
            z_score=float("nan"),
            momentum_1m=float("nan"),
            peer_breadth=float("nan"),
            peer_direction="insufficient",
            deviates_from_peers=False,
            signal_strength="low",
            narrative_hint=entry.get("narrative_hint", ""),
        )

    clean = series.dropna()
    last_value = float(clean.iloc[-1])
    last_date = clean.index[-1].strftime("%Y-%m-%d") if isinstance(clean.index[-1], pd.Timestamp) else None

    z_series = z_score(series)
    z_last = float(z_series.dropna().iloc[-1]) if not z_series.dropna().empty else float("nan")

    mom_series = momentum(series, periods=1)
    mom_last = float(mom_series.dropna().iloc[-1]) if not mom_series.dropna().empty else float("nan")

    peer_breadth_val, peer_dir = _peer_breadth_excluding(
        entry["peer_group"], key, snapshot
    )

    deviates = _check_deviation(mom_last, peer_dir)

    signal = _classify_signal(z_last, deviates, z_threshold)

    return NonConsensusReading(
        series_key=key,
        series_name_bg=entry.get("name_bg", key),
        lens=list(entry.get("lens", [])),
        peer_group=entry.get("peer_group", ""),
        tags=list(entry.get("tags", [])),
        last_value=round(last_value, 4),
        last_date=last_date,
        z_score=round(z_last, 3) if not np.isnan(z_last) else float("nan"),
        momentum_1m=round(mom_last, 4) if not np.isnan(mom_last) else float("nan"),
        peer_breadth=round(peer_breadth_val, 3) if not np.isnan(peer_breadth_val) else float("nan"),
        peer_direction=peer_dir,
        deviates_from_peers=deviates,
        signal_strength=signal,
        narrative_hint=entry.get("narrative_hint", ""),
    )


def _peer_breadth_excluding(
    peer_group_name: str,
    self_key: str,
    snapshot: dict[str, pd.Series],
) -> tuple[float, str]:
    """Изчислява breadth_positive на peer_group-а БЕЗ самата серия.

    Връща (breadth, direction_label). direction_label е един от:
      "up" (>0.6), "down" (<0.4), "mixed", "insufficient".
    """
    peer_entries = series_by_peer_group(peer_group_name)
    peer_keys = [e["_key"] for e in peer_entries if e["_key"] != self_key]

    available: dict[str, pd.Series] = {}
    for k in peer_keys:
        s = snapshot.get(k)
        if s is None or s.dropna().empty:
            continue
        available[k] = s

    if len(available) < MIN_PEER_SIZE_FOR_DEVIATION:
        return float("nan"), "insufficient"

    bp = breadth_positive(available)
    if np.isnan(bp):
        return float("nan"), "insufficient"

    if bp > PEER_UP_THRESHOLD:
        return float(bp), "up"
    if bp < PEER_DOWN_THRESHOLD:
        return float(bp), "down"
    return float(bp), "mixed"


def _check_deviation(mom_last: float, peer_direction: str) -> bool:
    """True ако сигналната серия върви срещу peer_group-а."""
    if np.isnan(mom_last):
        return False
    if peer_direction == "up" and mom_last < 0:
        return True
    if peer_direction == "down" and mom_last > 0:
        return True
    return False


def _classify_signal(
    z_last: float,
    deviates: bool,
    z_threshold: float,
) -> str:
    """high/medium/low според двата критерия."""
    extreme = not np.isnan(z_last) and abs(z_last) > z_threshold
    if extreme and deviates:
        return "high"
    if extreme or deviates:
        return "medium"
    return "low"


def _sort_key(r: NonConsensusReading) -> tuple:
    """Сортиране: по signal strength, после по |z|."""
    strength_rank = {"high": 2, "medium": 1, "low": 0}[r.signal_strength]
    z_abs = abs(r.z_score) if not np.isnan(r.z_score) else -1.0
    return (strength_rank, z_abs)


def _compute_as_of(
    snapshot: dict[str, pd.Series],
    keys: list[str],
) -> Optional[str]:
    """Max(last_date) сред релевантните серии."""
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
