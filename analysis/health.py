"""
analysis/health.py
==================
Единен lens health примитив (робастен z спрямо 10-г. плъзгащ прозорец + полярност).

Заменя `breadth_positive` като ИЗТОЧНИК на заглавния lens score. Връща:
  - health_z      (лещов робастен z; по-високо = по-здраво; ненасищащ магнитуд)
  - score          (0–100 за репорти: 50·(1+tanh(z/2)); 50 = близката норма)
  - direction      ("expanding" | "contracting" | "mixed" | "insufficient_data")
  - breadth_pct    (% налични серии от здравата страна — второстепенна прозрачност)
  - peer_groups    (per-група z + наличност, за дебъг/таблици)

Виж ../macro-satellite/LENS_SCORING_METHODOLOGY.md.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Optional

import numpy as np
import pandas as pd

from catalog.series import series_by_lens, ALLOWED_LENSES
from catalog.polarity import polarity_for, peer_group_weight, U_BAND
from core.primitives import apply_transform, robust_stats_latest

WINDOW_YEARS = 10
MIN_OBS = 36          # ≥3 г. история в прозореца, иначе серията е "insufficient"
TANH_SLOPE = 2.0      # score = 50·(1+tanh(z/SLOPE)); ±2σ ≈ 88/12
DIR_THRESHOLD = 0.5   # |z| праг за expanding/contracting (в σ)


def series_health_z(
    raw: pd.Series,
    transform: str,
    polarity: Any,
) -> Optional[float]:
    """Сурова серия → health-z (по-високо = по-здраво), или None ако недостатъчно данни."""
    s = apply_transform(raw, transform)
    stats = robust_stats_latest(s, window_years=WINDOW_YEARS, min_obs=MIN_OBS)
    if stats is None:
        return None
    val, med, scale = stats

    # U-форма: отклонение в двете посоки = по-зле
    if isinstance(polarity, tuple) and polarity and polarity[0] == "U":
        if scale == 0 or np.isnan(scale):
            return float(U_BAND)
        if polarity[1] == "target":
            center = float(polarity[2])
        else:  # "self" — собствената норма
            center = med
        z_dev = (val - center) / scale
        return float(U_BAND - abs(z_dev))

    # Линейна полярност
    if scale == 0 or np.isnan(scale):
        return 0.0  # без вариация → на нормата
    z_raw = (val - med) / scale
    sign = float(polarity) if polarity in (1, -1, +1) else 1.0
    return float(sign * z_raw)


def lens_health(lens: str, snapshot: dict[str, pd.Series]) -> dict:
    """Лещов health: серия→z_h→peer-група (средно)→леща (претеглено по peer-група).

    Args:
        lens: една от ALLOWED_LENSES.
        snapshot: {catalog_key → pd.Series} (сурови серии).
    """
    if lens not in ALLOWED_LENSES:
        raise ValueError(f"Unknown lens '{lens}'.")

    by_pg: dict[str, list[str]] = defaultdict(list)
    for entry in series_by_lens(lens):
        pg = entry.get("peer_group")
        if pg:
            by_pg[pg].append((entry["_key"], entry.get("transform", "level")))

    pg_out: list[dict] = []
    pg_zs: list[tuple[float, float]] = []   # (z, weight)
    n_pos = n_avail = 0

    for pg_name in sorted(by_pg.keys()):
        members = by_pg[pg_name]
        zs: list[float] = []
        for key, transform in members:
            s = snapshot.get(key)
            if s is None or s.dropna().empty:
                continue
            zh = series_health_z(s, transform, polarity_for(key, lens))
            if zh is None or (isinstance(zh, float) and math.isnan(zh)):
                continue
            zs.append(zh)
            n_avail += 1
            if zh > 0:
                n_pos += 1
        if not zs:
            pg_out.append({"name": pg_name, "health_z": None, "n_available": 0})
            continue
        pg_z = float(np.mean(zs))
        w = peer_group_weight(pg_name)
        pg_zs.append((pg_z, w))
        pg_out.append({"name": pg_name, "health_z": round(pg_z, 3),
                       "n_available": len(zs), "weight": w})

    if not pg_zs:
        return {"lens": lens, "health_z": None, "score": None,
                "direction": "insufficient_data", "breadth_pct": None,
                "peer_groups": pg_out}

    wsum = sum(w for _, w in pg_zs)
    lens_z = sum(z * w for z, w in pg_zs) / wsum if wsum else float("nan")
    score = 50.0 * (1.0 + math.tanh(lens_z / TANH_SLOPE))
    if lens_z > DIR_THRESHOLD:
        direction = "expanding"
    elif lens_z < -DIR_THRESHOLD:
        direction = "contracting"
    else:
        direction = "mixed"
    breadth_pct = (100.0 * n_pos / n_avail) if n_avail else None

    return {
        "lens": lens,
        "health_z": round(lens_z, 3),
        "score": round(score, 1),
        "direction": direction,
        "breadth_pct": round(breadth_pct, 1) if breadth_pct is not None else None,
        "peer_groups": pg_out,
    }
