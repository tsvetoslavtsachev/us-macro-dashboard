"""
sources/zillow_adapter.py
=========================
Zillow Research data adapter — публични CSV downloads (CC0 лиценз).

Zillow Home Value Index (ZHVI) и сродни серии се публикуват като wide-format
CSV файлове в `files.zillowstatic.com/research/public_csvs/`. Този adapter:

  1. Download-ва CSV (без auth, без API key)
  2. Парсва wide-format (rows=регион, cols=ISO дати)
  3. Филтрира по region_name (типично "United States" за национални серии)
  4. Конвертира в long format → ISO date → float dict
  5. Кешира в JSON със същата структура като ism_cache / confboard_cache

Catalog declaration:
    "ZHVI_US_SFRCONDO_SA": {
        "source": "external",
        "id": "ZHVI_US_SFRCONDO_SA",          # cache lookup key
        "cache_file": "data/zillow_cache.json",
        "region": "US",
        "name_bg": "Zillow Home Value Index — All Homes (SFR+Condo, SA)",
        ...
        "zillow_url": "https://files.zillowstatic.com/research/...",
        "zillow_region_name": "United States",
    }

Лиценз: ZHVI и всички Zillow Research данни са под Creative Commons CC0 1.0
(public domain dedication). Свободно за всякаква употреба, включително
republish в нашите public dashboards. Виж: https://www.zillow.com/research/data/
"""
from __future__ import annotations

import csv
import io
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ============================================================
# CONFIG
# ============================================================

DEFAULT_CACHE_PATH = "data/zillow_cache.json"
REQUEST_TIMEOUT_SECONDS = 60
USER_AGENT = "Mozilla/5.0 (us-macro-dashboard zillow-adapter)"

# Cache TTL — Zillow обновява monthly (около 15-ти на месец); 20 дни е
# консервативно (refresh опит влиза в правилния прозорец).
CACHE_TTL_DAYS = 20


# ============================================================
# ZillowAdapter
# ============================================================

class ZillowAdapter:
    """Download + parse + cache Zillow public CSVs."""

    def __init__(
        self,
        cache_path: str | Path = DEFAULT_CACHE_PATH,
        base_dir: Optional[Path] = None,
    ):
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).parent.parent
        self.cache_path = self.base_dir / cache_path
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict[str, Any]] = self._load_cache()

    # ─────────────────────────────────────────────────────
    # Cache I/O
    # ─────────────────────────────────────────────────────

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        if not self.cache_path.exists():
            return {}
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Zillow cache load failed ({e}); празен start.")
            return {}

    def save_cache(self) -> None:
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2, ensure_ascii=False)
        except OSError as e:
            logger.error(f"Zillow cache save failed: {e}")

    # ─────────────────────────────────────────────────────
    # Download + parse
    # ─────────────────────────────────────────────────────

    def _download_csv(self, url: str) -> str:
        """Download Zillow CSV. Raises URLError/HTTPError при мрежов проблем."""
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            raw = resp.read()
        # Zillow CSVs are UTF-8
        return raw.decode("utf-8", errors="replace")

    def _parse_wide_csv(
        self,
        csv_text: str,
        region_name: str,
        region_column: str = "RegionName",
    ) -> dict[str, float]:
        """Парсва wide-format CSV → dict {ISO_date: float}.

        Args:
            csv_text: суров CSV текст.
            region_name: стойност за филтриране (напр. "United States").
            region_column: коя колона да match-ва (default "RegionName").

        Returns:
            Dict {YYYY-MM-DD: value}. Празен ако region_name не е намерен.
        """
        reader = csv.reader(io.StringIO(csv_text))
        try:
            header = next(reader)
        except StopIteration:
            return {}

        # Намираме индекса на region column
        try:
            region_idx = header.index(region_column)
        except ValueError:
            logger.warning(
                f"Region column '{region_column}' не съществува в header. "
                f"Налични: {header[:8]}..."
            )
            return {}

        # Дати в header — идентифицираме като YYYY-MM-DD pattern
        date_cols: list[tuple[int, str]] = []
        for i, col in enumerate(header):
            if _looks_like_iso_date(col):
                date_cols.append((i, col))

        if not date_cols:
            logger.warning("Не намерих дати в header (очаквах YYYY-MM-DD колони).")
            return {}

        # Намираме target row
        for row in reader:
            if len(row) <= region_idx:
                continue
            if row[region_idx].strip() == region_name:
                values: dict[str, float] = {}
                for i, date_str in date_cols:
                    if i >= len(row):
                        continue
                    raw = row[i].strip()
                    if not raw:
                        continue
                    try:
                        values[date_str] = float(raw)
                    except ValueError:
                        continue
                return values

        logger.warning(f"Region '{region_name}' не намерен в CSV.")
        return {}

    # ─────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────

    def fetch(
        self,
        series_key: str,
        url: str,
        region_name: str,
        force: bool = False,
        region_column: str = "RegionName",
    ) -> dict[str, float]:
        """Fetch + cache серия. Връща {ISO_date: value} dict.

        Cache TTL: 20 дни (Zillow обновява monthly). Force прескача TTL.

        При мрежов проблем → връща cached версия (warning log).
        При parse fail → връща празен dict.
        """
        if not force and self._is_cache_fresh(series_key):
            entry = self._cache.get(series_key, {})
            return entry.get("history", {})

        try:
            csv_text = self._download_csv(url)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            logger.warning(f"{series_key}: download failed ({e}); fallback на cache.")
            entry = self._cache.get(series_key, {})
            return entry.get("history", {})

        history = self._parse_wide_csv(csv_text, region_name, region_column)
        if not history:
            logger.warning(f"{series_key}: parse върна 0 obs; fallback на cache.")
            entry = self._cache.get(series_key, {})
            return entry.get("history", {})

        dates_sorted = sorted(history.keys())
        last_date = dates_sorted[-1]
        latest_value = history[last_date]

        self._cache[series_key] = {
            "url": url,
            "region_name": region_name,
            "last_fetched": datetime.now().isoformat(),
            "current": {
                "month": last_date,
                "headline": latest_value,
                "parse_quality": "ok",
                "last_fetched": datetime.now().isoformat(),
            },
            "history": history,
            "history_source": "zillow_csv",
        }
        return history

    def fetch_many(
        self,
        specs: list[dict[str, Any]],
        force: bool = False,
    ) -> dict[str, dict[str, float]]:
        """Batch fetch. Specs:
            [{key, url, region_name, region_column?}, ...]

        Save-ва кеша на края. Връща dict {key → history dict}.
        """
        results: dict[str, dict[str, float]] = {}
        for spec in specs:
            key = spec["key"]
            results[key] = self.fetch(
                series_key=key,
                url=spec["url"],
                region_name=spec["region_name"],
                region_column=spec.get("region_column", "RegionName"),
                force=force,
            )
        self.save_cache()
        return results

    def _is_cache_fresh(self, series_key: str) -> bool:
        entry = self._cache.get(series_key)
        if not entry:
            return False
        ts = entry.get("last_fetched")
        if not ts:
            return False
        try:
            last = datetime.fromisoformat(ts)
        except ValueError:
            return False
        age_days = (datetime.now() - last).days
        return age_days < CACHE_TTL_DAYS

    def get_cache_status(self, series_key: str) -> dict[str, Any]:
        """FRED-compatible status dict за data_status integration."""
        entry = self._cache.get(series_key)
        if not entry:
            return {
                "is_cached": False,
                "last_fetched": None,
                "last_observation": None,
                "n_observations": 0,
            }
        history = entry.get("history") or {}
        dates = sorted(history.keys())
        return {
            "is_cached": True,
            "last_fetched": entry.get("last_fetched"),
            "last_observation": dates[-1] if dates else None,
            "n_observations": len(history),
        }


# ============================================================
# Helpers
# ============================================================

def _looks_like_iso_date(s: str) -> bool:
    """Проверка дали header колона е ISO date (YYYY-MM-DD)."""
    if len(s) != 10:
        return False
    if s[4] != "-" or s[7] != "-":
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False
