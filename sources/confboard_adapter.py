"""
sources/confboard_adapter.py
============================
Conference Board press release scraper през Firecrawl API.

Поддържа два индикатора:
  - cb_lei: Leading Economic Index®
  - cb_cci: Consumer Confidence Index®

И двете нямат clean API; ползваме Firecrawl scrape на topic landing страниците,
които вграждат текущия press release inline. Single-step fetch (за разлика от
ISM който е двустъпков).

Cache shape — същата като ISMAdapter:
  {
    "cb_lei": {
      "indicator": "cb_lei",
      "current": {url_fetched, last_fetched, month, headline, subcomponents,
                  parse_quality, missing_subcomponents, mom_change},
      "history": {iso_date: float, ...},   # за Bloomberg backfill
      "history_source": str | None,
      "history_imported": iso_str | None,
    },
    ...
  }

Free-tier ограничения:
  - Conference Board публикува headline + commentary; historical values
    behind paywall ($1500+/yr full dataset).
  - За backfill: ползвай Bloomberg → scripts/import_bloomberg.py.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

# Reuse generic Firecrawl helpers от ISMAdapter — DRY за HTTP layer.
from sources.ism_adapter import (
    FirecrawlError,
    _scrape_with_firecrawl,
    _normalize_text,
    _month_string_to_iso,
    DEFAULT_RETRY_BACKOFF,
)

logger = logging.getLogger(__name__)


# ============================================================
# CONFIG
# ============================================================

# Conference Board release-ва месечно — TTL ~ release cycle.
CACHE_TTL_DAYS = 25

DEFAULT_CACHE_PATH = "data/confboard_cache.json"

# Per-indicator URL + parsing config. Topic landing pages вграждат latest
# release inline, така че single-step fetch работи (за разлика от ISM).
CB_INDICATORS: dict[str, dict[str, Any]] = {
    "cb_lei": {
        "url": "https://www.conference-board.org/topics/us-leading-indicators",
        "display_name": "Leading Economic Index",
        # LEI е index level (base 2016=100 в текущата ревизия).
        # Sanity range широк за да поеме историческите данни 1959+ когато
        # икономиката беше много по-малка (стойности около 22-23 в края на
        # 1950s, нарастват до 100+ днес). Upper bound 200 за buffer.
        "value_range": (10, 200),
        # LEI няма sub-indices в традиционния смисъл — има 10 components
        # с contributions (positive/negative percentage points). Засега
        # parse-ваме само headline + mom change; contributions = nice-to-have.
        "subcomponent_keys": [],
    },
    "cb_cci": {
        "url": "https://www.conference-board.org/topics/consumer-confidence",
        "display_name": "Consumer Confidence Index",
        # CCI base = 1985=100. Historical обхват: 50-150.
        "value_range": (20, 200),
        # CCI има 2 sub-indices: Present Situation + Expectations.
        "subcomponent_keys": ["Present Situation", "Expectations"],
    },
}


# ============================================================
# Parsing — Conference Board specific
# ============================================================

# Headline patterns. Използваме `[\s\S]{0,N}?` за non-greedy match на ANY
# char (вкл. периоди от числа като "0.6%" и newlines), bounded length да
# избегне cross-paragraph matching.
#
# CCI typical: "Consumer Confidence Index® edged up by 0.6 points to 92.8 (1985=100) in April"
# LEI typical: "Leading Economic Index®(LEI) for the US declined by 0.6% in March 2026 to 97.3 (2016=100)"
#
# Pattern A е по-стриктен (anchor на "for the US" за LEI / "by X points" за CCI);
# Pattern B е по-loose (без anchor). Първият match-ващ wins.

_CCI_HEADLINE_PATTERNS = (
    # Strict — anchor на "by X points to":
    re.compile(
        r"Consumer\s+Confidence\s+Index[\s\S]{0,150}?"
        r"by\s+\d+(?:\.\d+)?\s+points?\s+to\s+(\d+(?:\.\d+)?)",
        re.IGNORECASE,
    ),
    # Loose fallback:
    re.compile(
        r"Consumer\s+Confidence\s+Index[\s\S]{0,200}?\s+to\s+(\d+(?:\.\d+)?)",
        re.IGNORECASE,
    ),
)

_LEI_HEADLINE_PATTERNS = (
    # Strict — "LEI for the US ... in <month> <year> to <value>".
    # Между "LEI" и "for the US" може да има markdown markup като `**`, `)`,
    # `®`, whitespace. `[^a-zA-Z]{0,20}` хваща всичко non-letter.
    re.compile(
        r"(?:LEI|Leading\s+Economic\s+Index)[^a-zA-Z]{0,20}for\s+the\s+US"
        r"[\s\S]{0,150}?"
        r"in\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)"
        r"[\s\S]{0,30}?"
        r"to\s+(\d+(?:\.\d+)?)",
        re.IGNORECASE,
    ),
    # Loose fallback — само anchor на "LEI for the US ... to NUM":
    re.compile(
        r"(?:LEI|Leading\s+Economic\s+Index)[^a-zA-Z]{0,20}for\s+the\s+US"
        r"[\s\S]{0,250}?"
        r"\s+to\s+(\d+(?:\.\d+)?)",
        re.IGNORECASE,
    ),
)

# Sub-component pattern (CCI): "The Present Situation Index ... to 123.8"
# Same `[\s\S]` trick.
_CB_SUBINDEX_PATTERN = re.compile(
    r"(?:The\s+)?([A-Z][A-Za-z\s]+?)\s+Index[\s\S]{0,200}?\s+to\s+(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

# Month: "in April" / "in April 2026". Year често липсва — нужен fallback.
_CB_MONTH_PATTERN = re.compile(
    r"\b(?:in|for)\s+(January|February|March|April|May|June|July|August|September|October|November|December)(?:\s+(\d{4}))?",
    re.IGNORECASE,
)

# Month-over-month change: "edged up by 0.6 points to 92.8" / "decreased 0.3 percent"
_CB_MOM_PATTERN = re.compile(
    r"(?:edged\s+up|rose|increased|fell|declined|decreased|dropped|edged\s+down)\s+(?:by\s+)?(\d+(?:\.\d+)?)\s*(?:points|percent|%|pp)",
    re.IGNORECASE,
)


def _parse_cb_release(
    markdown: str,
    indicator_key: str,
    config: dict[str, Any],
    fallback_year: Optional[int] = None,
) -> dict[str, Any]:
    """Парсва Conference Board press release markdown.

    Returns dict with same shape като ISM parse output:
        {headline, month, subcomponents, parse_quality, missing_subcomponents,
         mom_change}

    Quality:
      "ok"      = headline извлечен + всички expected subcomponents
      "partial" = headline OK, но subcomponents липсват
      "failed"  = няма headline
    """
    result: dict[str, Any] = {
        "headline": None,
        "month": None,
        "mom_change": None,
        "subcomponents": {},
        "parse_quality": "failed",
        "missing_subcomponents": [],
    }
    markdown = _normalize_text(markdown)
    value_min, value_max = config["value_range"]
    expected_subs = set(config["subcomponent_keys"])

    # Headline — пробвай patterns по ред (strict първо, loose втори).
    headline_patterns = _LEI_HEADLINE_PATTERNS if indicator_key == "cb_lei" else _CCI_HEADLINE_PATTERNS
    for pat in headline_patterns:
        found_val = None
        for m in pat.finditer(markdown):
            val = float(m.group(1))
            if value_min <= val <= value_max:
                found_val = val
                break
        if found_val is not None:
            result["headline"] = found_val
            break

    # Month (with year fallback to current year)
    m = _CB_MONTH_PATTERN.search(markdown)
    if m:
        month_name = m.group(1).capitalize()
        year_str = m.group(2)
        if year_str:
            year = int(year_str)
        elif fallback_year:
            year = fallback_year
        else:
            year = datetime.now().year
        result["month"] = f"{month_name} {year}"

    # MoM change (за context, не за validation)
    m = _CB_MOM_PATTERN.search(markdown)
    if m:
        try:
            result["mom_change"] = float(m.group(1))
        except ValueError:
            pass

    # Subcomponents (само за CCI)
    if expected_subs:
        found: dict[str, float] = {}
        for match in _CB_SUBINDEX_PATTERN.finditer(markdown):
            name_raw = match.group(1).strip()
            val = float(match.group(2))
            if not (value_min <= val <= value_max):
                continue
            # Strip leading filler "The" (case-insensitive)
            if name_raw.lower().startswith("the "):
                name_raw = name_raw[4:]
            for expected in expected_subs:
                if name_raw.lower() == expected.lower() and expected not in found:
                    found[expected] = val
                    break
        result["subcomponents"] = found
        result["missing_subcomponents"] = sorted(expected_subs - found.keys())

    # Quality
    if result["headline"] is None:
        result["parse_quality"] = "failed"
    elif expected_subs and len(result["subcomponents"]) < len(expected_subs):
        result["parse_quality"] = "partial"
    else:
        result["parse_quality"] = "ok"

    return result


# ============================================================
# ConfBoardAdapter
# ============================================================

class ConfBoardAdapter:
    """Conference Board press release scraper. Same cache shape като ISMAdapter."""

    def __init__(
        self,
        api_key: str,
        cache_path: str | Path = DEFAULT_CACHE_PATH,
        base_dir: Optional[Path] = None,
        retry_backoff: Optional[list[int]] = None,
    ):
        self.api_key = api_key
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).parent.parent
        self.cache_path = self.base_dir / cache_path
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict[str, Any]] = self._load_cache()
        self.retry_backoff = (
            list(retry_backoff) if retry_backoff is not None
            else list(DEFAULT_RETRY_BACKOFF)
        )
        self._fetch_failures: list[str] = []

    # ─────────────────────────────────────────────────────
    # Cache I/O (history-aware shape) — duplicate logic от ISMAdapter,
    # защото share-ваме формата но не самия cache файл.
    # ─────────────────────────────────────────────────────

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        if not self.cache_path.exists():
            return {}
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"ConfBoard cache load failed ({e}); празен кеш.")
            return {}
        out: dict[str, dict[str, Any]] = {}
        for key, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            entry.setdefault("current", {})
            entry.setdefault("history", {})
            entry.setdefault("history_source", None)
            entry.setdefault("history_imported", None)
            entry.setdefault("indicator", key)
            out[key] = entry
        return out

    def save_cache(self) -> None:
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2, default=str, ensure_ascii=False)
        except OSError as e:
            logger.error(f"ConfBoard cache save failed: {e}")

    # ─────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────

    def fetch(self, indicator_key: str, force: bool = False) -> dict[str, Any]:
        """Fetch single indicator. Returns cache entry dict."""
        if indicator_key not in CB_INDICATORS:
            raise ValueError(
                f"Unknown ConfBoard indicator: {indicator_key}. "
                f"Available: {list(CB_INDICATORS.keys())}"
            )
        return self._fetch_indicator(indicator_key, force=force)

    def fetch_all(self, force: bool = False) -> dict[str, dict[str, Any]]:
        """Fetch all configured indicators. Saves cache веднъж в края."""
        self._fetch_failures = []
        results = {
            key: self.fetch(key, force=force)
            for key in CB_INDICATORS
        }
        self.save_cache()
        return results

    def get_cache_status(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for key, entry in self._cache.items():
            current = entry.get("current") or {}
            out[key] = {
                "is_cached": True,
                "last_fetched": current.get("last_fetched"),
                "month_covered": current.get("month"),
                "headline": current.get("headline"),
                "parse_quality": current.get("parse_quality"),
                "n_subcomponents": len(current.get("subcomponents", {})),
                "n_history_observations": len(entry.get("history", {})),
                "history_source": entry.get("history_source"),
            }
        return out

    def last_fetch_failures(self) -> list[str]:
        return list(self._fetch_failures)

    def invalidate(self, indicator: str) -> None:
        self._cache.pop(indicator, None)

    def invalidate_all(self) -> None:
        self._cache.clear()

    def add_history_observations(
        self,
        cache_key: str,
        observations: dict[str, float],
        source_label: str = "bloomberg_csv",
    ) -> int:
        """Merge historical observations в history{}. Виж ISMAdapter за докс."""
        if cache_key not in CB_INDICATORS:
            raise ValueError(f"Unknown ConfBoard indicator: {cache_key}")
        if cache_key not in self._cache:
            self._cache[cache_key] = {
                "indicator": cache_key,
                "current": {},
                "history": {},
                "history_source": None,
                "history_imported": None,
            }
        value_min, value_max = CB_INDICATORS[cache_key]["value_range"]
        entry = self._cache[cache_key]
        history = entry.setdefault("history", {})
        changes = 0
        for date_str, value in observations.items():
            try:
                fval = float(value)
            except (TypeError, ValueError):
                logger.warning(f"{cache_key}: skip invalid value at {date_str}: {value!r}")
                continue
            if not (value_min <= fval <= value_max):
                logger.warning(f"{cache_key}: skip out-of-range value at {date_str}: {fval}")
                continue
            if history.get(date_str) != fval:
                history[date_str] = fval
                changes += 1
        entry["history_source"] = source_label
        entry["history_imported"] = datetime.now().isoformat()
        return changes

    # ─────────────────────────────────────────────────────
    # Internal — single-step fetch с retry
    # ─────────────────────────────────────────────────────

    def _fetch_indicator(self, cache_key: str, force: bool) -> dict[str, Any]:
        if not force and self._is_cache_fresh(cache_key):
            logger.info(f"{cache_key}: cache fresh, skip refetch")
            return self._cache[cache_key]

        config = CB_INDICATORS[cache_key]
        url = config["url"]

        try:
            markdown = self._scrape_with_retry(url)
        except FirecrawlError as e:
            logger.error(f"{cache_key}: fetch failed — {e}")
            self._fetch_failures.append(cache_key)
            return self._cache.get(cache_key, {})

        parsed = _parse_cb_release(markdown, cache_key, config, fallback_year=datetime.now().year)
        if parsed["parse_quality"] == "failed":
            logger.error(
                f"{cache_key}: parse failed (no headline) on {url}. "
                f"Dumping raw markdown to debug file."
            )
            self._dump_debug_markdown(cache_key, markdown)
            self._fetch_failures.append(cache_key)
            return self._cache.get(cache_key, {})

        if parsed["parse_quality"] == "partial":
            logger.warning(
                f"{cache_key}: partial parse — headline {parsed['headline']} но "
                f"липсват: {parsed['missing_subcomponents']}. Кеширам каквото имам."
            )

        # Build current entry, preserve history
        existing = self._cache.get(cache_key, {})
        current_entry = {
            "url_fetched": url,
            "last_fetched": datetime.now().isoformat(),
            "month": parsed["month"],
            "headline": parsed["headline"],
            "mom_change": parsed["mom_change"],
            "subcomponents": parsed["subcomponents"],
            "parse_quality": parsed["parse_quality"],
            "missing_subcomponents": parsed["missing_subcomponents"],
        }
        self._cache[cache_key] = {
            "indicator": cache_key,
            "current": current_entry,
            "history": existing.get("history", {}),
            "history_source": existing.get("history_source"),
            "history_imported": existing.get("history_imported"),
        }

        # Auto-history (същият pattern като ISM)
        if parsed["headline"] is not None and parsed["month"]:
            iso_date = _month_string_to_iso(parsed["month"])
            if iso_date:
                self._cache[cache_key]["history"][iso_date] = parsed["headline"]
        return self._cache[cache_key]

    def _scrape_with_retry(self, url: str) -> str:
        if not self.api_key or not self.api_key.strip():
            raise FirecrawlError(
                "FIRECRAWL_API_KEY липсва. Виж .env.example или README.",
                transient=False,
            )
        max_retries = len(self.retry_backoff)
        last_err: Optional[FirecrawlError] = None
        for attempt in range(max_retries + 1):
            try:
                return _scrape_with_firecrawl(self.api_key, url)
            except FirecrawlError as e:
                last_err = e
                if not e.transient:
                    raise
                if attempt < max_retries:
                    wait = self.retry_backoff[attempt]
                    logger.warning(f"Firecrawl transient, retry {attempt+1}/{max_retries} след {wait}s — {e}")
                    if wait > 0:
                        time.sleep(wait)
                else:
                    logger.error(f"Firecrawl изчерпан retry budget — {e}")
        assert last_err is not None
        raise last_err

    def _is_cache_fresh(self, cache_key: str) -> bool:
        entry = self._cache.get(cache_key)
        if entry is None:
            return False
        current = entry.get("current") or {}
        last_fetched_str = current.get("last_fetched")
        if not last_fetched_str:
            return False
        try:
            last_fetched = datetime.fromisoformat(last_fetched_str)
        except ValueError:
            return False
        age = datetime.now() - last_fetched
        return age < timedelta(days=CACHE_TTL_DAYS)

    def _dump_debug_markdown(self, cache_key: str, markdown: str) -> None:
        debug_dir = self.cache_path.parent / "confboard_debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        debug_path = debug_dir / f"{cache_key}_{ts}.md"
        try:
            debug_path.write_text(markdown, encoding="utf-8")
            logger.info(f"Debug markdown dumped to {debug_path}")
        except OSError as e:
            logger.warning(f"Failed to dump debug markdown: {e}")
