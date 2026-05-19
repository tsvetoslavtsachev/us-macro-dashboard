"""
sources/external_loader.py
==========================
Зарежда external (non-FRED) indicator series от cache JSON-и и ги конвертира
до pd.Series — same shape като FredAdapter.get_snapshot().

Източници:
  - data/ism_cache.json (ISM_MFG_PMI, ISM_SVCS_PMI)
  - data/confboard_cache.json (CB_LEI, CB_CCI)

Чете history{} полето (а не current — current е само latest month, history
включва и него auto-added). Това дава пълен time-series за downstream
analytics (breadth, cross-lens, anomaly, analog matching).

Usage в --briefing / --status / --export-context:
  external_series = load_external_series(SERIES_CATALOG, base_dir)
  snapshot = adapter.get_snapshot(...) | external_series   # merge
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def load_external_series(
    catalog: dict[str, dict[str, Any]],
    base_dir: Path,
) -> dict[str, pd.Series]:
    """Зарежда всички external series от cache файловете.

    Args:
        catalog: SERIES_CATALOG dict (целият каталог; функцията филтрира
                 по source=="external")
        base_dir: project root (parent на data/, sources/, ...)

    Returns:
        dict {catalog_key → pd.Series} с DatetimeIndex sorted ascending.
        Празни series се пропускат от резултата (no entry в cache, празен
        history, или повреден cache файл).

    Грешки при четене на cache: warn + skip, не raise. Това позволява на
    briefing pipeline-а да работи дори ако external cache липсва (напр.
    при clean checkout без import-нати данни).
    """
    out: dict[str, pd.Series] = {}

    # Групираме по cache_file за да не четем един и същ JSON многократно
    cache_groups: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for key, meta in catalog.items():
        if meta.get("source") != "external":
            continue
        cache_file = meta.get("cache_file")
        if not cache_file:
            logger.warning(f"{key}: липсва 'cache_file' в catalog meta — skip")
            continue
        cache_groups.setdefault(cache_file, []).append((key, meta))

    for cache_file, entries in cache_groups.items():
        cache_path = base_dir / cache_file
        if not cache_path.exists():
            logger.warning(
                f"External cache не съществува: {cache_path}. "
                f"Skip-ват се: {[k for k, _ in entries]}. "
                f"Run python run.py --fetch-ism / --fetch-confboard за първи fetch."
            )
            continue

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Cannot read {cache_path}: {e}. Skip group.")
            continue

        for key, meta in entries:
            cache_key = meta["id"]
            entry = cache_data.get(cache_key)
            if not entry:
                logger.info(f"{key}: cache_key '{cache_key}' липсва в {cache_file}")
                continue
            history = entry.get("history") or {}
            if not history:
                logger.info(f"{key}: empty history (current scrape only). Skip.")
                continue
            try:
                series = pd.Series(history, dtype=float)
                series.index = pd.to_datetime(series.index)
                series = series.sort_index()
            except (ValueError, TypeError) as e:
                logger.warning(f"{key}: cannot build pd.Series от history: {e}")
                continue
            out[key] = series
            logger.debug(f"{key}: loaded {len(series)} obs")

    return out


def get_external_cache_status(
    catalog: dict[str, dict[str, Any]],
    base_dir: Path,
) -> dict[str, dict[str, Any]]:
    """Status info за external indicators — за Data Status Screen.

    Връща dict {catalog_key → status_info}. Status_info shape:
      {
        is_cached: bool,
        last_fetched: str | None,
        month_covered: str | None,
        headline: float | None,
        parse_quality: str | None,
        n_history_observations: int,
        history_source: str | None,
        history_range: tuple[str, str] | None,
      }
    """
    out: dict[str, dict[str, Any]] = {}

    cache_groups: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for key, meta in catalog.items():
        if meta.get("source") != "external":
            continue
        cache_file = meta.get("cache_file")
        if not cache_file:
            continue
        cache_groups.setdefault(cache_file, []).append((key, meta))

    for cache_file, entries in cache_groups.items():
        cache_path = base_dir / cache_file
        if not cache_path.exists():
            for key, _ in entries:
                out[key] = _empty_status()
            continue

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
        except (OSError, json.JSONDecodeError):
            for key, _ in entries:
                out[key] = _empty_status()
            continue

        for key, meta in entries:
            cache_key = meta["id"]
            entry = cache_data.get(cache_key)
            if not entry:
                out[key] = _empty_status()
                continue
            current = entry.get("current") or {}
            history = entry.get("history") or {}
            dates = sorted(history.keys())
            out[key] = {
                # FRED-compatible fields (за data_status._build_row съвместимост)
                "is_cached": True,
                "last_fetched": current.get("last_fetched"),
                "last_observation": dates[-1] if dates else None,
                "n_observations": len(history),
                # External-only fields (за бъдеща употреба)
                "month_covered": current.get("month"),
                "headline": current.get("headline"),
                "parse_quality": current.get("parse_quality"),
                "history_source": entry.get("history_source"),
                "history_range": (dates[0], dates[-1]) if dates else None,
            }

    return out


def _empty_status() -> dict[str, Any]:
    return {
        # FRED-compatible
        "is_cached": False,
        "last_fetched": None,
        "last_observation": None,
        "n_observations": 0,
        # External-only
        "month_covered": None,
        "headline": None,
        "parse_quality": None,
        "history_source": None,
        "history_range": None,
    }


# ============================================================
# Unified adapter wrapper (за data_status compatibility)
# ============================================================

class UnifiedStatusAdapter:
    """Routes get_cache_status() към FRED adapter или external statuses
    според дали key-ът е cached в external.

    Минимална обвивка — само за data_status генерация, която очаква
    obj.get_cache_status(key) → dict. Не дублира fetch logic.
    """

    def __init__(self, fred_adapter, external_statuses: dict[str, dict[str, Any]]):
        self._fred = fred_adapter
        self._external = external_statuses

    def get_cache_status(self, key: str) -> dict[str, Any]:
        if key in self._external:
            return self._external[key]
        if hasattr(self._fred, "get_cache_status"):
            return self._fred.get_cache_status(key)
        return {}
