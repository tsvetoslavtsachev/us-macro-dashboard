"""
sources/press_release_scraper.py
================================
Унифицирана scraper рамка за housing press releases:

  • NAHB Housing Market Index (HMI)        — monthly, 3rd Mon
  • MBA Mortgage Applications (purchase)    — weekly, Wed
  • NAR Pending Home Sales Index (PHSI)     — monthly, last Wed
  • NAR Housing Affordability Index history — supplements FRED FIXHAI

ДИЗАЙН (Phase B/architecture-first):
  • Един BaseAdapter с urllib + JSON cache + history merge logic
  • Три специфични subclass-а; всеки декларира URL + parse strategy
  • Cache shape е identical с ism_cache / confboard_cache / zillow_cache:
      { "<id>": {"current": {...}, "history": {...}, "last_fetched": ..., ...} }
  • external_loader.load_external_series() автоматично ги picks-up
    щом catalog entry-то стане source="external"
  • PARSING е stubbed днес (returns parse_quality="pending"); архитектурата работи

ЛЕГАЛНОСТ:
  • Press releases са public domain снимки от dissemination сайтовете
  • Scrape-ваме само headline числа (latest single value)
  • НЕ копираме full reports или time-series history (тези са paid)
  • Истинската history идва от Bloomberg ingestion tool (Phase C)

ЗАЩО stub имплементация:
  Web scraping е fragile (HTML менявa). За production usage:
    1. Implement parse_html() per source (regex/BS4)
    2. Add regression tests с captured fixtures
    3. Maintain debug capture в data/<source>_debug/

  Днес ние финализираме architecture; parsing идва when needed.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


USER_AGENT = "Mozilla/5.0 (us-macro-dashboard press-release-scraper)"
REQUEST_TIMEOUT_SECONDS = 60


# ============================================================
# BASE
# ============================================================

class PressReleaseAdapter:
    """Base class за press-release scrapers.

    Subclass-ите override:
      - SOURCE_NAME: short ID за logs ("nahb", "mba", "nar")
      - DEFAULT_CACHE_PATH: relative път към JSON cache
      - INDICATORS: dict {indicator_key → {url, parse_hint, schedule}}
      - parse_html(indicator_key, html) → dict
            Връща {month/week, headline, parse_quality, ...} или
            {parse_quality: "pending"} ако не е имплементирано.
    """

    SOURCE_NAME: str = "base"
    DEFAULT_CACHE_PATH: str = ""
    INDICATORS: dict[str, dict[str, Any]] = {}

    def __init__(
        self,
        cache_path: str | Path | None = None,
        base_dir: Optional[Path] = None,
    ):
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).parent.parent
        cache_path = cache_path or self.DEFAULT_CACHE_PATH
        self.cache_path = self.base_dir / cache_path
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict[str, Any]] = self._load_cache()

    # ─── cache I/O ────────────────────────────────────────────
    def _load_cache(self) -> dict[str, dict[str, Any]]:
        if not self.cache_path.exists():
            return {}
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"{self.SOURCE_NAME}: cache load failed ({e}); start empty.")
            return {}

    def save_cache(self) -> None:
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2, ensure_ascii=False)
        except OSError as e:
            logger.error(f"{self.SOURCE_NAME}: cache save failed: {e}")

    # ─── download ─────────────────────────────────────────────
    def _download_html(self, url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            raw = resp.read()
        return raw.decode("utf-8", errors="replace")

    # ─── per-source parsing — OVERRIDE in subclass ────────────
    def parse_html(self, indicator_key: str, html: str) -> dict[str, Any]:
        """Default = pending stub. Override in subclass за реална parsing logic.

        Очаквам connect-нат subclass да върне поне:
            {"headline": float, "month": "YYYY-MM-DD"|"YYYY-MM"|None,
             "parse_quality": "ok"|"partial"|"pending"|"failed",
             ...source-specific fields}
        """
        return {"parse_quality": "pending", "headline": None}

    # ─── public API ───────────────────────────────────────────
    def fetch(self, indicator_key: str, force: bool = False) -> dict[str, Any]:
        """Fetch + parse + cache един indicator. Връща current dict."""
        if indicator_key not in self.INDICATORS:
            raise ValueError(
                f"{self.SOURCE_NAME}: unknown indicator '{indicator_key}'. "
                f"Налични: {sorted(self.INDICATORS.keys())}"
            )
        spec = self.INDICATORS[indicator_key]
        url = spec["url"]

        if not force and self._is_fresh(indicator_key, spec):
            entry = self._cache.get(indicator_key, {})
            return entry.get("current", {})

        # Download
        try:
            html = self._download_html(url)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            logger.warning(f"{self.SOURCE_NAME}/{indicator_key}: download failed ({e})")
            entry = self._cache.get(indicator_key, {})
            return entry.get("current", {})

        # Parse
        parsed = self.parse_html(indicator_key, html)
        parsed["last_fetched"] = datetime.now().isoformat()

        # Merge into cache + extend history when parse_quality is ok
        entry = self._cache.setdefault(indicator_key, {"history": {}})
        entry["current"] = parsed
        if parsed.get("parse_quality") == "ok":
            month_key = parsed.get("month")
            headline = parsed.get("headline")
            if month_key and isinstance(headline, (int, float)):
                # history key е канонизирана дата (YYYY-MM-01 за месечни)
                norm = _normalize_date_key(month_key, spec.get("schedule", "monthly"))
                if norm:
                    entry.setdefault("history", {})[norm] = float(headline)
        entry["last_fetched"] = parsed["last_fetched"]
        return parsed

    def fetch_all(self, force: bool = False) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        for key in self.INDICATORS:
            results[key] = self.fetch(key, force=force)
        self.save_cache()
        return results

    # ─── freshness ────────────────────────────────────────────
    def _is_fresh(self, indicator_key: str, spec: dict[str, Any]) -> bool:
        entry = self._cache.get(indicator_key)
        if not entry:
            return False
        ts = entry.get("current", {}).get("last_fetched") or entry.get("last_fetched")
        if not ts:
            return False
        try:
            last = datetime.fromisoformat(ts)
        except ValueError:
            return False
        ttl_days = TTL_DAYS_BY_SCHEDULE.get(spec.get("schedule", "monthly"), 20)
        return (datetime.now() - last).days < ttl_days

    # ─── status (для data_status integration) ─────────────────
    def get_cache_status(self, indicator_key: str) -> dict[str, Any]:
        entry = self._cache.get(indicator_key)
        if not entry:
            return {
                "is_cached": False,
                "last_fetched": None,
                "last_observation": None,
                "n_observations": 0,
            }
        history = entry.get("history") or {}
        dates = sorted(history.keys())
        current = entry.get("current") or {}
        return {
            "is_cached": True,
            "last_fetched": current.get("last_fetched") or entry.get("last_fetched"),
            "last_observation": dates[-1] if dates else current.get("month"),
            "n_observations": len(history),
            "parse_quality": current.get("parse_quality"),
        }


TTL_DAYS_BY_SCHEDULE = {
    "weekly":    3,
    "monthly":  20,
    "quarterly": 60,
}


def _normalize_date_key(date_str: str, schedule: str) -> Optional[str]:
    """Нормализира различни форми за history key.

    Monthly: '2026-04' → '2026-04-01'
    Weekly:  '2026-05-28' → '2026-05-28' (запазваме точната дата)
    """
    if not date_str:
        return None
    try:
        if schedule == "weekly":
            return datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-%m-%d")
        # monthly / quarterly — нормализираме към 1-ви на месеца
        for fmt in ("%Y-%m-%d", "%Y-%m"):
            try:
                d = datetime.strptime(date_str, fmt)
                return d.replace(day=1).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None
    except Exception:
        return None


# ============================================================
# NAHB Housing Market Index (HMI) — monthly, 3rd Monday
# ============================================================

class NAHBAdapter(PressReleaseAdapter):
    """NAHB/Wells Fargo Housing Market Index.

    URL: https://www.nahb.org/news-and-economics/housing-economics/indices/housing-market-index
    Press release pattern: "Builder confidence ... fell/rose N points to XX in MONTH"
    Sub-components: Current Sales, Future Sales, Buyer Traffic.

    HMI стойност > 50 = positive sentiment; < 50 = negative.

    PARSING TODO (когато се имплементира):
      1. Fetch latest press release URL (от индекс страница)
      2. Regex: r'Builder confidence .{0,80}? (\\d+) in (\\w+ \\d{4})'
      3. Sub-indices: r'(Current Sales|Future Sales|Buyer Traffic).{0,40}?(\\d+)'
    """

    SOURCE_NAME = "nahb"
    DEFAULT_CACHE_PATH = "data/nahb_cache.json"
    INDICATORS = {
        "NAHB_HMI": {
            "url": "https://www.nahb.org/news-and-economics/housing-economics/indices/housing-market-index",
            "parse_hint": "Builder confidence index, 3rd Monday release",
            "schedule": "monthly",
        },
    }


# ============================================================
# MBA Mortgage Applications — weekly, Wed
# ============================================================

class MBAAdapter(PressReleaseAdapter):
    """MBA Weekly Applications Survey — Purchase + Refinance indices.

    URL: https://www.mba.org/news-and-research/research-and-economics/single-family-research/weekly-applications-survey
    Press release pattern: "MBA Composite Index ... decreased/increased X.X percent ..."

    Главните метрики:
      - Composite Index (week-over-week %)
      - Purchase Index (week-over-week %)
      - Refinance Index (week-over-week %)

    ⚠ ВНИМАНИЕ: mba.org блокира plain urllib с HTTP 403 (anti-bot, изисква
    full browser headers + cookies). За реално прилагане:
      - Използвай Firecrawl scrape (както ism_adapter / confboard_adapter)
      - Или преминаване към data.mba.org public API endpoint ако съществува
      - Или browser automation (playwright/selenium) за edge cases

    PARSING TODO:
      Regex over press release intro paragraph за всеки от 3-те индекси.
      Press release е embedded в news страница на mba.org.
    """

    SOURCE_NAME = "mba"
    DEFAULT_CACHE_PATH = "data/mba_cache.json"
    INDICATORS = {
        "MBA_PURCHASE_IDX": {
            "url": "https://www.mba.org/news-and-research/research-and-economics/single-family-research/weekly-applications-survey",
            "parse_hint": "Purchase Index, weekly Wed release",
            "schedule": "weekly",
        },
        "MBA_REFINANCE_IDX": {
            "url": "https://www.mba.org/news-and-research/research-and-economics/single-family-research/weekly-applications-survey",
            "parse_hint": "Refinance Index, weekly Wed release",
            "schedule": "weekly",
        },
    }


# ============================================================
# NAR Pending Home Sales Index — monthly, last Wed
# ============================================================

class NARAdapter(PressReleaseAdapter):
    """NAR Pending Home Sales Index (PHSI) — leading indicator на Existing Home Sales.

    PHSI няма FRED ticker (NAR proprietary за history). Press releases са free
    за latest single value.

    URL: https://www.nar.realtor/research-and-statistics/housing-statistics/pending-home-sales
    Press release pattern: "Pending Home Sales index ... XX.X in MONTH, a YY.Y% change..."

    PHSI = 100 е базата (2001 average).

    PARSING TODO:
      1. Fetch latest PR от NAR newsroom
      2. Regex: r'Pending Home Sales.+?(\\d+\\.\\d) in (\\w+ \\d{4})'
      3. MoM change: r'(?:rose|fell|increased|decreased) (\\d+\\.\\d) percent'
    """

    SOURCE_NAME = "nar"
    DEFAULT_CACHE_PATH = "data/nar_cache.json"
    INDICATORS = {
        "NAR_PHSI": {
            "url": "https://www.nar.realtor/research-and-statistics/housing-statistics/pending-home-sales",
            "parse_hint": "Pending Home Sales Index, monthly last Wed",
            "schedule": "monthly",
        },
    }
