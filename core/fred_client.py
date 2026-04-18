"""
econ_v2 — FRED Client
======================
Единен gateway към Federal Reserve Economic Data.
• 12-часов кеш в data/cache.json — не дърпа при всяко стартиране
• Връща pandas Series с DatetimeIndex
• При грешка в API — зарежда последния кеш и предупреждава
"""

import json
import os
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from fredapi import Fred

# Папката на проекта (econ_v2/)
BASE_DIR = Path(__file__).parent.parent
CACHE_FILE = BASE_DIR / "data" / "cache.json"

log = logging.getLogger("fred_client")


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_cache(cache: dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)


def _is_fresh(entry: dict, ttl_hours: int) -> bool:
    if "fetched_at" not in entry:
        return False
    fetched = datetime.fromisoformat(entry["fetched_at"])
    return datetime.now() - fetched < timedelta(hours=ttl_hours)


class FredClient:
    """
    Основен клас за достъп до FRED.

    Употреба:
        client = FredClient(api_key, cache_ttl_hours=12)
        series = client.get("UNRATE", start="2000-01-01")
    """

    def __init__(self, api_key: str, cache_ttl_hours: int = 12):
        self.fred = Fred(api_key=api_key)
        self.ttl = cache_ttl_hours
        self.cache = _load_cache()
        self._dirty = False

    def get(self, series_id: str, start: str = "1970-01-01") -> pd.Series:
        """
        Връща pandas Series за дадена FRED серия.
        Използва кеш ако е пресен, иначе дърпа от API.
        """
        cache_key = f"{series_id}_{start}"

        if cache_key in self.cache and _is_fresh(self.cache[cache_key], self.ttl):
            data = self.cache[cache_key]["data"]
            s = pd.Series(data["values"], index=pd.to_datetime(data["dates"]))
            s.name = series_id
            return s

        try:
            log.info(f"  Fetching {series_id} from FRED...")
            raw = self.fred.get_series(series_id, observation_start=start)
            raw = raw.dropna()

            self.cache[cache_key] = {
                "fetched_at": datetime.now().isoformat(),
                "data": {
                    "dates": [str(d.date()) for d in raw.index],
                    "values": list(raw.values),
                },
            }
            self._dirty = True
            raw.name = series_id
            return raw

        except Exception as e:
            log.warning(f"  FRED error for {series_id}: {e}")
            if cache_key in self.cache:
                log.warning(f"  → Using stale cache for {series_id}")
                data = self.cache[cache_key]["data"]
                s = pd.Series(data["values"], index=pd.to_datetime(data["dates"]))
                s.name = series_id
                return s
            raise RuntimeError(f"No data for {series_id}: {e}")

    def get_many(self, series_ids: list, start: str = "1970-01-01") -> pd.DataFrame:
        """Връща DataFrame с множество серии като колони."""
        frames = {}
        for sid in series_ids:
            try:
                frames[sid] = self.get(sid, start=start)
            except Exception as e:
                log.warning(f"Skipping {sid}: {e}")
        return pd.DataFrame(frames)

    def save_cache(self):
        if self._dirty:
            _save_cache(self.cache)
            self._dirty = False
            log.info("Cache saved.")

    def __del__(self):
        self.save_cache()
