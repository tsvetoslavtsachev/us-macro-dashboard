"""
sources/ism_adapter.py
======================
ISM PMI scraper през Firecrawl API.

ISM Manufacturing PMI и Services PMI се публикуват на 1-ви и 3-ти business
day на месеца. Няма clean API → използваме Firecrawl за scrape на public
press release страницата.

Двустъпков fetch:
  1. Index страница (`/reports/ism-pmi-reports/`) — извличаме текущия
     "View Report" link (URL съдържа името на месеца, променя се).
  2. Report страница — scrape + regex parse на headline + sub-indices.

Free-tier ограничения:
  - Само латест месец (historical time-series е paid subscription)
  - 4 credits на refresh (2 страници × 2 индикатора), 500/месец free tier

Не знае за analysis слоя — работи само със scrape + parse + cache.

Стилови решения от fred_adapter.py:
  - JSON cache с per-indicator metadata (last_fetched, month_covered)
  - Tolerant парсинг — ако само headline се извлече, кешираме само него
  - Validation: PMI стойностите трябва да са в [0, 100]
  - Без heavy deps — само urllib + json + re
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

logger = logging.getLogger(__name__)


# ============================================================
# CONFIG
# ============================================================

# ISM публикува месечно. Cache TTL = 25 дни значи следваща refresh опит
# най-рано 25 дни след последния — все още в текущия месец, преди следващ
# release. Briefing pipeline-ът override-ва това с auto-stale check.
CACHE_TTL_DAYS = 25

DEFAULT_CACHE_PATH = "data/ism_cache.json"

ISM_INDEX_URL = "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/"
FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v1/scrape"

# Retry config — Firecrawl rate limits + transient 5xx
DEFAULT_RETRY_BACKOFF = [2, 5, 15]  # секунди между опитите

# HTTP request timeout (Firecrawl scrape може да отнеме време при slow target)
REQUEST_TIMEOUT_SECONDS = 60

# Валидни sub-index имена в ISM Manufacturing PMI report (за parse валидация)
MANUFACTURING_SUBINDICES = {
    "New Orders",
    "Production",
    "Employment",
    "Supplier Deliveries",
    "Inventories",
    "Customers' Inventories",
    "Prices",
    "Backlog of Orders",
    "New Export Orders",
    "Imports",
}

# Services има малко по-различен набор
SERVICES_SUBINDICES = {
    "Business Activity",
    "New Orders",
    "Employment",
    "Supplier Deliveries",
    "Inventories",
    "Prices",
    "Backlog of Orders",
    "New Export Orders",
    "Imports",
    "Inventory Sentiment",
}


# ============================================================
# Firecrawl HTTP client (минимален, без deps)
# ============================================================

class FirecrawlError(Exception):
    """Базова грешка от Firecrawl. .transient за класификация."""
    def __init__(self, msg: str, transient: bool = False):
        super().__init__(msg)
        self.transient = transient


def _scrape_with_firecrawl(api_key: str, url: str) -> str:
    """Scrape URL през Firecrawl, връща markdown.

    Raises FirecrawlError при failure (с transient=True/False за retry логика).
    """
    payload = json.dumps({
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": True,
        "excludeTags": ["nav", "footer", "aside", "header"],
    }).encode("utf-8")

    req = urllib.request.Request(
        FIRECRAWL_SCRAPE_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        # 4xx → permanent (bad key, bad URL); 5xx → transient
        is_transient = 500 <= e.code < 600
        raise FirecrawlError(
            f"Firecrawl HTTP {e.code} on {url}: {e.reason}",
            transient=is_transient,
        ) from e
    except urllib.error.URLError as e:
        raise FirecrawlError(
            f"Firecrawl network error on {url}: {e.reason}",
            transient=True,
        ) from e
    except TimeoutError as e:
        raise FirecrawlError(
            f"Firecrawl timeout on {url}",
            transient=True,
        ) from e

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise FirecrawlError(
            f"Firecrawl returned non-JSON for {url}: {e}",
            transient=False,
        ) from e

    if not data.get("success"):
        err = data.get("error", "unknown error")
        raise FirecrawlError(f"Firecrawl unsuccessful for {url}: {err}", transient=False)

    inner = data.get("data", {})
    status = inner.get("metadata", {}).get("statusCode")
    if status and status >= 400:
        # ISM върна 404 на нашия URL (напр. месецът се е сменил)
        raise FirecrawlError(
            f"Target page returned HTTP {status} for {url}",
            transient=False,
        )

    markdown = inner.get("markdown", "")
    if not markdown:
        raise FirecrawlError(f"Firecrawl returned empty markdown for {url}", transient=False)
    return markdown


# ============================================================
# Parsing helpers
# ============================================================

def _extract_report_links(index_markdown: str) -> dict[str, str]:
    """От index страницата извлича URL-ите на текущите Manufacturing и Services
    report-и.

    Index страницата има по две "View Report" линка след sections "Manufacturing PMI"
    и "Services PMI". Returns dict с ключове "manufacturing" / "services" → URL.

    Empty dict ако нищо не намерено (структурата на страницата се е променила).
    """
    out: dict[str, str] = {}
    # Намери всички View Report линкове. URL pattern:
    #   /reports/ism-pmi-reports/pmi/<month>/      → manufacturing
    #   /reports/ism-pmi-reports/services/<month>/ → services
    for url in re.findall(r"\[View Report\]\(([^)]+)\)", index_markdown):
        if "/pmi/" in url and "manufacturing" not in out:
            out["manufacturing"] = url
        elif "/services/" in url and "services" not in out:
            out["services"] = url
    return out


_HEADLINE_PATTERNS = (
    # "Manufacturing PMI® at 52.7%"
    re.compile(r"(?:Manufacturing|Services)\s+PMI[®\s]*at\s+(\d+(?:\.\d+)?)\s*%"),
    # "PMI® registered 52.7 percent"
    re.compile(r"PMI[®\s]*registered\s+(\d+(?:\.\d+)?)\s*percent"),
)

# Sub-index patterns. Multiple за да хванем различни phrasings от ISM-овия
# narrative стил. Apostrophes се нормализират в _normalize_text() преди парсинг,
# затова в pattern-ите използваме само ASCII '. Прилагат се по ред — първото
# matching name за всяко expected sub-index wins (deduplication в parse loop).
_SUBINDEX_PATTERNS = (
    # Pattern A: "(The) X Index <verb> Y percent" — verb immediately after Index
    re.compile(
        r"(?:The\s+)?([A-Z][A-Za-z'\s]+?)\s+Index\s+"
        r"(?:registered|registering|reading\s+of)\s+"
        r"(\d+(?:\.\d+)?)\s*(?:percent|%)",
        re.IGNORECASE,
    ),
    # Pattern B: "(The) X Index (Y percent)" — parenthetical (Production case)
    re.compile(
        r"(?:The\s+)?([A-Z][A-Za-z'\s]+?)\s+Index\s+"
        r"\((\d+(?:\.\d+)?)\s*percent\)",
        re.IGNORECASE,
    ),
    # Pattern C: "X Index at Y%" — summary header at top of report (Services)
    re.compile(
        r"([A-Z][A-Za-z'\s]+?)\s+Index\s+at\s+(\d+(?:\.\d+)?)\s*%",
        re.IGNORECASE,
    ),
    # Pattern D: loose — "X Index <description, up to 25 words> verb Y percent".
    # Идва последна; рискова но хваща narrative прози като "The Backlog of Orders
    # Index remained in expansion territory for a third straight month, registering 53 percent".
    re.compile(
        r"(?:The\s+)?([A-Z][A-Za-z'\s]+?)\s+Index\s+"
        r"(?:\S+\s+){1,25}?"
        r"(?:registered|registering|reading\s+of)\s+"
        r"(\d+(?:\.\d+)?)\s*(?:percent|%)",
        re.IGNORECASE,
    ),
)

# Filler думи, които regex captures може погрешно да включи в име на Index
# (заради IGNORECASE + non-greedy expansion в lowercase context).
# Например: "...and the Imports Index registered..." → capture "and the Imports".
# Strip-ваме ги в _strip_filler() преди да сравним с expected_subindices.
_FILLER_PREFIXES = ("and the ", "and a ", "and an ", "the ", "and ", "an ", "a ")


def _strip_filler(name: str) -> str:
    """Премахва leading filler words от captured Index name."""
    name = name.strip()
    # Повтаряме за случаи като "and the X" → first strip "and ", второ "the "
    while True:
        lower = name.lower()
        for filler in _FILLER_PREFIXES:
            if lower.startswith(filler):
                name = name[len(filler):]
                break
        else:
            break
    return name


def _match_to_expected(name_raw: str, expected: set[str]) -> Optional[str]:
    """Опитва да съчетае captured име с очаквано sub-index име.

    Стратегия:
      1. Премахни leading filler (and/the/an/a)
      2. Direct case-insensitive match
      3. Suffix match — пробвай последните N думи (за случаи като
         'April reading of the Production' → 'Production')

    Стъпка 3 е консервативна: матчва само ако цялото expected име е suffix.
    Не разширява до прости substring matches за да избегне false positives
    (напр. captured 'Customers' Inventories' не трябва да matchva 'Inventories').
    Затова пробваме expected-те по дължина DESCENDING (multi-word първо).
    """
    name = _strip_filler(name_raw).strip()
    name_lower = name.lower()

    # Step 1: direct match
    for exp in expected:
        if name_lower == exp.lower():
            return exp

    # Step 2: suffix match — по-дългите expected names първо (избягва частични съвпадения)
    words = name.split()
    for exp in sorted(expected, key=lambda e: -len(e.split())):
        exp_words = exp.split()
        n = len(exp_words)
        if len(words) >= n:
            suffix = " ".join(words[-n:])
            if suffix.lower() == exp.lower():
                return exp
    return None

_MONTH_PATTERN = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\s+ISM"
)


_MONTH_NAME_TO_NUM = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
}


def _month_string_to_iso(month_str: str) -> Optional[str]:
    """'April 2026' → '2026-04-01'. Returns None при невалиден формат."""
    if not month_str:
        return None
    parts = month_str.strip().split()
    if len(parts) != 2:
        return None
    name, year_str = parts
    month = _MONTH_NAME_TO_NUM.get(name)
    if not month:
        return None
    try:
        year = int(year_str)
    except ValueError:
        return None
    return f"{year:04d}-{month:02d}-01"


def _normalize_text(s: str) -> str:
    """Нормализира typographic Unicode варианти към ASCII за consistent regex.

    - Typographic apostrophe U+2019 ('Customers' Inventories') → ASCII '
    - Typographic quotes (curly) → straight
    - Non-breaking space → regular space
    """
    return (
        s.replace("’", "'")
         .replace("‘", "'")
         .replace("“", '"')
         .replace("”", '"')
         .replace(" ", " ")
    )


def _parse_pmi_report(markdown: str, expected_subindices: set[str]) -> dict[str, Any]:
    """Парсва headline + sub-indices от report markdown.

    Returns:
        {
          "headline": float | None,
          "month": str | None,           # напр. "April 2026"
          "subindices": {name: float},   # subset of expected_subindices
          "parse_quality": "ok" | "partial" | "failed",
          "missing_subindices": [str],
        }

    "ok" = headline + >=80% от expected sub-indices
    "partial" = headline OK, но <80% от sub-indices
    "failed" = няма headline
    """
    result: dict[str, Any] = {
        "headline": None,
        "month": None,
        "subindices": {},
        "parse_quality": "failed",
        "missing_subindices": [],
    }

    # Нормализиране — typographic apostrophes/quotes/nbsp към ASCII еквиваленти,
    # за да работи regex matching и string comparison consistently.
    markdown = _normalize_text(markdown)

    # Month
    m = _MONTH_PATTERN.search(markdown)
    if m:
        result["month"] = f"{m.group(1)} {m.group(2)}"

    # Headline
    for pat in _HEADLINE_PATTERNS:
        m = pat.search(markdown)
        if m:
            val = float(m.group(1))
            if 0 <= val <= 100:
                result["headline"] = val
                break

    # Sub-indices — multiple pattern pass (pattern A първо, после B за остатъка)
    # Filter to expected names, валидирай range, deduplicate (първото matching wins).
    found: dict[str, float] = {}
    for pattern in _SUBINDEX_PATTERNS:
        for match in pattern.finditer(markdown):
            name_raw = match.group(1)
            val = float(match.group(2))
            if not (0 <= val <= 100):
                continue
            matched = _match_to_expected(name_raw, expected_subindices)
            if matched and matched not in found:
                found[matched] = val
    result["subindices"] = found
    result["missing_subindices"] = sorted(expected_subindices - found.keys())

    # Quality assessment
    if result["headline"] is None:
        result["parse_quality"] = "failed"
    elif len(found) / len(expected_subindices) >= 0.80:
        result["parse_quality"] = "ok"
    else:
        result["parse_quality"] = "partial"

    return result


# ============================================================
# ISMAdapter
# ============================================================

class ISMAdapter:
    """ISM PMI scraper с persistent cache.

    Подобно на FredAdapter — но индексирано по indicator name, не series_key,
    защото ISM е semi-structured scrape, не clean API.
    """

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
    # Cache I/O
    # ─────────────────────────────────────────────────────

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        if not self.cache_path.exists():
            return {}
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"ISM cache load failed ({e}); стартирам с празен кеш.")
            return {}

        # Migration: legacy shape е flat (headline/subindices/url_fetched в root).
        # Новата shape ги слага под `current`, добавя `history` за Bloomberg backfill.
        # In-memory migration; следващ save() записва новата shape.
        migrated: dict[str, dict[str, Any]] = {}
        for key, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            if "current" in entry or "history" in entry:
                # Вече новата shape — само осигури че history съществува.
                entry.setdefault("history", {})
                entry.setdefault("history_source", None)
                entry.setdefault("history_imported", None)
                migrated[key] = entry
            else:
                # Legacy → wrap.
                legacy_fields = {
                    k: v for k, v in entry.items()
                    if k not in ("indicator",)
                }
                migrated[key] = {
                    "indicator": entry.get("indicator", key),
                    "current": legacy_fields,
                    "history": {},
                    "history_source": None,
                    "history_imported": None,
                }
        return migrated

    def save_cache(self) -> None:
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2, default=str, ensure_ascii=False)
        except OSError as e:
            logger.error(f"ISM cache save failed: {e}")

    # ─────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────

    def fetch_manufacturing(self, force: bool = False) -> dict[str, Any]:
        """Fetch latest Manufacturing PMI. Returns cache entry dict."""
        return self._fetch_indicator(
            "manufacturing_pmi",
            link_key="manufacturing",
            expected_subindices=MANUFACTURING_SUBINDICES,
            force=force,
        )

    def fetch_services(self, force: bool = False) -> dict[str, Any]:
        """Fetch latest Services PMI. Returns cache entry dict."""
        return self._fetch_indicator(
            "services_pmi",
            link_key="services",
            expected_subindices=SERVICES_SUBINDICES,
            force=force,
        )

    def fetch_all(self, force: bool = False) -> dict[str, dict[str, Any]]:
        """Fetch both manufacturing + services. Saves cache веднъж в края."""
        self._fetch_failures = []
        results = {
            "manufacturing_pmi": self.fetch_manufacturing(force=force),
            "services_pmi": self.fetch_services(force=force),
        }
        self.save_cache()
        return results

    def get_cache_status(self) -> dict[str, dict[str, Any]]:
        """Status snapshot за всички cached indicators (за Data Status Screen)."""
        out: dict[str, dict[str, Any]] = {}
        for key, entry in self._cache.items():
            current = entry.get("current") or {}
            out[key] = {
                "is_cached": True,
                "last_fetched": current.get("last_fetched"),
                "month_covered": current.get("month"),
                "headline": current.get("headline"),
                "parse_quality": current.get("parse_quality"),
                "n_subindices": len(current.get("subindices", {})),
                "n_history_observations": len(entry.get("history", {})),
                "history_source": entry.get("history_source"),
            }
        return out

    # ─────────────────────────────────────────────────────
    # History management (за Bloomberg backfill importer)
    # ─────────────────────────────────────────────────────

    def add_history_observations(
        self,
        cache_key: str,
        observations: dict[str, float],
        source_label: str = "bloomberg_csv",
    ) -> int:
        """Merge-ва нови historical observations в `history` на indicator.

        Args:
            cache_key: indicator key (напр. "manufacturing_pmi")
            observations: {iso_date_str: value} — date във формат YYYY-MM-DD
            source_label: етикет за audit trail (по default "bloomberg_csv")

        Returns:
            Брой нови или updated observations (existing key with different
            value count-ва като updated).

        Cache shape остава history-aware дори ако още няма current scrape
        (entry се създава ако липсва).
        """
        if cache_key not in self._cache:
            self._cache[cache_key] = {
                "indicator": cache_key,
                "current": {},
                "history": {},
                "history_source": None,
                "history_imported": None,
            }
        entry = self._cache[cache_key]
        history = entry.setdefault("history", {})
        changes = 0
        for date_str, value in observations.items():
            try:
                fval = float(value)
            except (TypeError, ValueError):
                logger.warning(f"{cache_key}: skipping invalid value at {date_str}: {value!r}")
                continue
            if not (0 <= fval <= 1000):  # sanity range (loose — different indicators имат различни scales)
                logger.warning(f"{cache_key}: skipping out-of-range value at {date_str}: {fval}")
                continue
            if history.get(date_str) != fval:
                history[date_str] = fval
                changes += 1
        entry["history_source"] = source_label
        entry["history_imported"] = datetime.now().isoformat()
        return changes

    def last_fetch_failures(self) -> list[str]:
        return list(self._fetch_failures)

    def invalidate(self, indicator: str) -> None:
        self._cache.pop(indicator, None)

    def invalidate_all(self) -> None:
        self._cache.clear()

    # ─────────────────────────────────────────────────────
    # Internal — двустъпков fetch с retry
    # ─────────────────────────────────────────────────────

    def _fetch_indicator(
        self,
        cache_key: str,
        link_key: str,
        expected_subindices: set[str],
        force: bool,
    ) -> dict[str, Any]:
        """Двустъпков fetch: index → report URL → report page → parse → cache."""
        if not force and self._is_cache_fresh(cache_key):
            logger.info(f"{cache_key}: cache fresh, skip refetch")
            return self._cache[cache_key]

        # Step 1: scrape index, find report URL
        try:
            index_md = self._scrape_with_retry(ISM_INDEX_URL)
        except FirecrawlError as e:
            logger.error(f"{cache_key}: index fetch failed — {e}")
            self._fetch_failures.append(cache_key)
            return self._cache.get(cache_key, {})

        links = _extract_report_links(index_md)
        report_url = links.get(link_key)
        if not report_url:
            logger.error(
                f"{cache_key}: '{link_key}' link not found on ISM index — "
                f"structure may have changed. Available links: {list(links.keys())}"
            )
            self._fetch_failures.append(cache_key)
            return self._cache.get(cache_key, {})

        # Step 2: scrape report page
        try:
            report_md = self._scrape_with_retry(report_url)
        except FirecrawlError as e:
            logger.error(f"{cache_key}: report fetch failed — {e}")
            self._fetch_failures.append(cache_key)
            return self._cache.get(cache_key, {})

        # Step 3: parse
        parsed = _parse_pmi_report(report_md, expected_subindices)
        if parsed["parse_quality"] == "failed":
            logger.error(
                f"{cache_key}: parse failed (no headline) on {report_url}. "
                f"Dumping raw markdown to debug file."
            )
            self._dump_debug_markdown(cache_key, report_md)
            self._fetch_failures.append(cache_key)
            return self._cache.get(cache_key, {})

        if parsed["parse_quality"] == "partial":
            logger.warning(
                f"{cache_key}: partial parse — headline OK ({parsed['headline']}) "
                f"но липсват sub-indices: {parsed['missing_subindices']}. "
                f"Кеширам каквото имам."
            )

        # Step 4: cache — пиши в `current`, запази съществуващото `history`
        existing = self._cache.get(cache_key, {})
        current_entry = {
            "url_fetched": report_url,
            "last_fetched": datetime.now().isoformat(),
            "month": parsed["month"],
            "headline": parsed["headline"],
            "subindices": parsed["subindices"],
            "parse_quality": parsed["parse_quality"],
            "missing_subindices": parsed["missing_subindices"],
        }
        self._cache[cache_key] = {
            "indicator": cache_key,
            "current": current_entry,
            "history": existing.get("history", {}),
            "history_source": existing.get("history_source"),
            "history_imported": existing.get("history_imported"),
        }
        # Bonus: ако headline е валиден И month е парснат — auto-добави към history
        # (дата = първи ден на месеца, нормализирана). Това дава incremental
        # история без backfill, при regular --fetch-ism runs.
        if parsed["headline"] is not None and parsed["month"]:
            iso_date = _month_string_to_iso(parsed["month"])
            if iso_date:
                self._cache[cache_key]["history"][iso_date] = parsed["headline"]
        return self._cache[cache_key]

    def _scrape_with_retry(self, url: str) -> str:
        """Firecrawl scrape с retry на transient грешки."""
        if not self.api_key or not self.api_key.strip():
            raise FirecrawlError(
                "\n"
                "════════════════════════════════════════════════════════════\n"
                "  ❌ FIRECRAWL_API_KEY липсва или е празен\n"
                "════════════════════════════════════════════════════════════\n"
                "  Без ключ ISM scrape не може да работи.\n"
                "\n"
                "  Решение:\n"
                "    1. Регистрирай се: https://www.firecrawl.dev/signup\n"
                "    2. Вземи key: https://www.firecrawl.dev/app/api-keys\n"
                "    3. Сложи в .env: FIRECRAWL_API_KEY=твоят_ключ\n"
                "════════════════════════════════════════════════════════════",
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
                    logger.warning(
                        f"Firecrawl transient error, retry {attempt + 1}/{max_retries} "
                        f"след {wait}s — {e}"
                    )
                    if wait > 0:
                        time.sleep(wait)
                else:
                    logger.error(
                        f"Firecrawl изчерпан retry budget ({max_retries} опита) — {e}"
                    )

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
        """При parse failure — пиши raw markdown за ръчна инспекция."""
        debug_dir = self.cache_path.parent / "ism_debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        debug_path = debug_dir / f"{cache_key}_{ts}.md"
        try:
            debug_path.write_text(markdown, encoding="utf-8")
            logger.info(f"Debug markdown dumped to {debug_path}")
        except OSError as e:
            logger.warning(f"Failed to dump debug markdown: {e}")
