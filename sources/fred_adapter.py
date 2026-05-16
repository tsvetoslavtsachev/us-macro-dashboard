"""
sources/fred_adapter.py
=======================
FRED data source adapter с adaptive TTL cache.

Отговорности:
  - Fetch-ва серии от FRED API (fredapi package)
  - Кешира в JSON с per-series metadata (last_fetched, last_observation)
  - Определя cache TTL по release_schedule от catalog meta
  - Дава cache status info за Data Status Screen

Не знае за analysis слоя — работи само с series_id и catalog meta.
"""
from __future__ import annotations

import json
import logging
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ============================================================
# CONFIG
# ============================================================

CACHE_TTL_DAYS = {
    "weekly":     3,
    "monthly":   10,
    "quarterly": 30,
    "annually":  90,
}

DEFAULT_CACHE_PATH = "data/fred_cache.json"

# ── Retry config за FRED 5xx transient errors ────────────────
# 3 retry-та с прогресивни delays — общо 22s максимум.
# По-устойчиво на kratкосрочни FRED API outages.
DEFAULT_RETRY_BACKOFF = [2, 5, 15]  # секунди между опитите

# Permanent = bad request / bad ID → fail fast, без retry
PERMANENT_ERROR_MARKERS = (
    "Bad Request",
    "does not exist",
    "Not Found",
    " 400",
    " 404",
)

# Transient = backend или мрежов проблем → retry
TRANSIENT_ERROR_MARKERS = (
    " 500",
    " 502",
    " 503",
    " 504",
    "Internal Server Error",
    "Bad Gateway",
    "Service Unavailable",
    "Gateway Timeout",
    "Connection reset",
    "Connection aborted",
    "timed out",
    "timeout",
)


def _classify_fetch_error(err: Exception) -> str:
    """Класифицира FRED грешка като 'transient' (retry) или 'permanent' (fail fast).

    Приоритет:
      1. HTTP status code (ако exception-ът го експозира): 5xx→transient, 4xx→permanent
      2. String markers в съобщението
      3. Unknown → 'transient' (консервативно: retry е евтин, strict fail е скъп)
    """
    code = getattr(err, "code", None) or getattr(err, "status", None)
    if isinstance(code, int):
        if 500 <= code < 600:
            return "transient"
        if 400 <= code < 500:
            return "permanent"

    msg = str(err)
    for marker in PERMANENT_ERROR_MARKERS:
        if marker in msg:
            return "permanent"
    for marker in TRANSIENT_ERROR_MARKERS:
        if marker in msg:
            return "transient"
    return "transient"


# ============================================================
# Tolerant JSON parser (за повреден cache tail)
# ============================================================

def _tolerant_parse_cache(raw: str) -> dict[str, dict[str, Any]]:
    """Парсва cache JSON серия-по-серия; спира при първата счупена.

    Cache файлът е {"KEY1": {...}, "KEY2": {...}, ...}. При crash по време
    на save, последната серия може да е truncated. Strict json.load() тогава
    фейлва и губим ВСИЧКО валидно. Това е non-destructive fallback: парсва
    key-value по key-value с JSONDecoder.raw_decode и ранен exit на грешка.

    Returns: dict с всички серии, успешно парснати преди грешката.
    Не хвърля — връща {} ако даже началото е счупено.
    """
    n = len(raw)
    i = 0
    while i < n and raw[i] in " \t\n\r":
        i += 1
    if i >= n or raw[i] != "{":
        return {}
    i += 1  # след '{'

    out: dict[str, dict[str, Any]] = {}
    decoder = json.JSONDecoder()

    while i < n:
        while i < n and raw[i] in " \t\n\r,":
            i += 1
        if i >= n or raw[i] == "}":
            break
        if raw[i] != '"':
            break  # неочакван token → спираме tolerantно
        try:
            key, i = decoder.raw_decode(raw, i)
        except json.JSONDecodeError:
            break
        while i < n and raw[i] in " \t\n\r":
            i += 1
        if i >= n or raw[i] != ":":
            break
        i += 1
        while i < n and raw[i] in " \t\n\r":
            i += 1
        try:
            value, i = decoder.raw_decode(raw, i)
        except json.JSONDecodeError:
            break
        if isinstance(value, dict):
            out[key] = value
    return out


# ============================================================
# FredAdapter
# ============================================================

class FredAdapter:
    """FRED data adapter с persistent cache."""

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
        self._fred_client = None  # lazy init
        # Injectable за tests (avoid real sleep); None → production defaults
        self.retry_backoff = (
            list(retry_backoff) if retry_backoff is not None
            else list(DEFAULT_RETRY_BACKOFF)
        )
        # Tracker за последния fetch_many call — кои серии са fail-нали
        # (всички retries изчерпани → fall-back към cache).
        # Reset-ва се в началото на всеки fetch_many.
        self._fetch_failures: list[str] = []

    # ─────────────────────────────────────────────────────
    # Cache I/O
    # ─────────────────────────────────────────────────────

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        if not self.cache_path.exists():
            return {}
        # Първи опит — strict JSON парсинг (fast path, 99% от случаите).
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except OSError as e:
            logger.warning(f"Cache load failed ({e}); стартирам с празен кеш.")
            return {}
        except json.JSONDecodeError as e:
            # Tolerant fallback — парсваме серия-по-серия, спираме при първата
            # счупена, запазваме всичко предишно. Това предпазва целия кеш от
            # случайно truncation (напр. crash по време на save).
            logger.warning(
                f"Cache JSON corrupt ({e}); опитвам tolerant парсинг за "
                f"да запазя валидните серии..."
            )
            try:
                raw = self.cache_path.read_text(encoding="utf-8")
                recovered = _tolerant_parse_cache(raw)
                logger.warning(
                    f"Tolerant парсинг успя: възстановени {len(recovered)} серии "
                    f"(следващ save() ще презапише файла като валиден JSON)."
                )
                return recovered
            except Exception as e2:
                logger.warning(f"Tolerant парсинг също фейлна ({e2}); празен кеш.")
                return {}

    def save_cache(self) -> None:
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2, default=str)
        except OSError as e:
            logger.error(f"Cache save failed: {e}")

    # ─────────────────────────────────────────────────────
    # FRED client (lazy)
    # ─────────────────────────────────────────────────────

    def _get_fred(self):
        if self._fred_client is None:
            if not self.api_key or not self.api_key.strip():
                raise RuntimeError(
                    "\n"
                    "════════════════════════════════════════════════════════════\n"
                    "  ❌ FRED_API_KEY липсва или е празен\n"
                    "════════════════════════════════════════════════════════════\n"
                    "  Без ключ FRED fetch ще fail-не тихо и кешът ще остане стар.\n"
                    "\n"
                    "  Решение:\n"
                    "    1. Създай .env в корена на проекта (виж .env.example)\n"
                    "    2. Сложи: FRED_API_KEY=твоят_ключ\n"
                    "    3. Регистрация: https://fred.stlouisfed.org/docs/api/api_key.html\n"
                    "════════════════════════════════════════════════════════════"
                )
            try:
                from fredapi import Fred
            except ImportError:
                raise ImportError(
                    "Липсва fredapi. Инсталирай: pip install fredapi"
                )
            self._fred_client = Fred(api_key=self.api_key)
        return self._fred_client

    # ─────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────

    def fetch(
        self,
        series_key: str,
        fred_id: str,
        release_schedule: str,
        force: bool = False,
    ) -> pd.Series:
        """Взима серия — от кеша или от FRED, според TTL.

        Args:
            series_key: Вътрешен ключ на серията (за кеширане).
            fred_id: Реален FRED API идентификатор.
            release_schedule: "weekly" | "monthly" | "quarterly" | "annually"
            force: Игнорира TTL и форсира refetch.

        Returns:
            pd.Series с DatetimeIndex. Може да е празна при грешка.
        """
        if not force and self._is_cache_fresh(series_key, release_schedule):
            return self._series_from_cache(series_key)

        try:
            data = self._fetch_with_retry(series_key, fred_id)
            if data is None or (hasattr(data, "empty") and data.empty):
                warnings.warn(f"{series_key} ({fred_id}): empty response from FRED")
                self._fetch_failures.append(series_key)
                return self._series_from_cache(series_key)

            # Store in cache
            series = pd.Series(data)
            series.index = pd.to_datetime(series.index)
            self._store_in_cache(series_key, fred_id, series)
            return series

        except Exception as e:
            logger.error(f"{series_key} ({fred_id}): fetch failed — {e}")
            self._fetch_failures.append(series_key)
            # Fall back to cache if available
            return self._series_from_cache(series_key)

    # ─────────────────────────────────────────────────────
    # Retry layer — защита срещу transient FRED 5xx errors
    # ─────────────────────────────────────────────────────

    def _fetch_with_retry(self, series_key: str, fred_id: str):
        """Изпълнява fred.get_series(fred_id) с retry на transient грешки.

        - На 5xx / timeout → sleep + retry (до len(self.retry_backoff) пъти)
        - На 4xx / bad ID → fail fast, raise веднага
        - На unknown error → третира като transient (консервативно)

        Logging политика:
        - Success on first try → тихо.
        - Success after retries → INFO ред със сума ("успех след N retry-та").
        - Final failure → batched WARNING-и за всеки failed attempt + ERROR
          за изчерпан budget. (Не се принтват retry-и докато се надяваме на success.)

        Raises последната грешка ако всички опити се изчерпат.
        """
        fred = self._get_fred()
        max_retries = len(self.retry_backoff)
        last_err: Optional[Exception] = None
        retry_log: list[str] = []  # buffer — flush само при final failure

        for attempt in range(max_retries + 1):
            try:
                result = fred.get_series(fred_id)
                if retry_log:
                    logger.info(
                        f"{series_key} ({fred_id}): успех след "
                        f"{len(retry_log)} retry-та"
                    )
                return result
            except Exception as e:
                last_err = e
                classification = _classify_fetch_error(e)
                if classification == "permanent":
                    logger.error(
                        f"{series_key} ({fred_id}): permanent error, no retry — {e}"
                    )
                    raise
                if attempt < max_retries:
                    wait = self.retry_backoff[attempt]
                    retry_log.append(
                        f"transient error, retry {attempt + 1}/{max_retries} "
                        f"след {wait}s — {e}"
                    )
                    if wait > 0:
                        time.sleep(wait)
                else:
                    # Изчерпан budget — flush buffered warnings + final error
                    for msg in retry_log:
                        logger.warning(f"{series_key} ({fred_id}): {msg}")
                    logger.error(
                        f"{series_key} ({fred_id}): изчерпан retry budget "
                        f"({max_retries} опита) — {e}"
                    )

        # Защитен fallback — при валидна логика не трябва да стигаме до тук
        assert last_err is not None
        raise last_err

    def fetch_many(
        self,
        series_specs: list[dict[str, Any]],
        force: bool = False,
    ) -> dict[str, pd.Series]:
        """Batch fetch. series_specs е list от {key, fred_id, release_schedule}.

        Връща dict {series_key: pd.Series}. След извикването,
        `last_fetch_failures()` връща ключовете, чиито fetch е fail-нал
        (и които са върнали cache fallback).
        """
        # Reset failure tracker at start of each batch
        self._fetch_failures = []
        results: dict[str, pd.Series] = {}
        for spec in series_specs:
            key = spec["key"]
            fred_id = spec["fred_id"]
            schedule = spec.get("release_schedule", "monthly")
            results[key] = self.fetch(key, fred_id, schedule, force=force)
        self.save_cache()
        total = len(series_specs)
        n_failed = len(self._fetch_failures)
        if total > 0 and n_failed / total >= 0.30:
            print(
                "\n"
                "════════════════════════════════════════════════════════════\n"
                f"  ⚠️  ВНИМАНИЕ: {n_failed}/{total} серии fail-наха при fetch\n"
                "════════════════════════════════════════════════════════════\n"
                "  Резултатите идват от стария кеш — НЕ са актуални.\n"
                "  Провери: FRED ключ, мрежа, FRED API статус.\n"
                f"  Failed keys: {', '.join(self._fetch_failures[:10])}"
                + (f" (+{n_failed - 10} още)" if n_failed > 10 else "") + "\n"
                "════════════════════════════════════════════════════════════"
            )
        return results

    # ─────────────────────────────────────────────────────
    # Cache logic
    # ─────────────────────────────────────────────────────

    def last_fetch_failures(self) -> list[str]:
        """Връща list от series_key-та, чийто fetch е fail-нал в последния
        `fetch_many` (всички retries изчерпани → fall-back към cache).

        Empty list ако всичко е минало успешно или fetch_many още не е извикван.
        """
        return list(self._fetch_failures)

    def find_stale_specs(self, specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """От подаден списък FRED specs връща само тези, чийто кеш е stale (TTL изтекъл).

        Used by run.py --briefing flow за auto-refresh без --refresh флаг.
        """
        return [
            s for s in specs
            if not self._is_cache_fresh(s["key"], s.get("release_schedule", "monthly"))
        ]

    def _is_cache_fresh(self, series_key: str, release_schedule: str) -> bool:
        entry = self._cache.get(series_key)
        if entry is None:
            return False
        last_fetched_str = entry.get("last_fetched")
        if not last_fetched_str:
            return False
        try:
            last_fetched = datetime.fromisoformat(last_fetched_str)
        except ValueError:
            return False
        ttl = CACHE_TTL_DAYS.get(release_schedule, 10)
        age = datetime.now() - last_fetched
        return age < timedelta(days=ttl)

    def _store_in_cache(self, series_key: str, fred_id: str, series: pd.Series) -> None:
        if series.empty:
            return
        # Store as dict of ISO date strings → float
        data_dict = {
            idx.strftime("%Y-%m-%d"): float(val)
            for idx, val in series.dropna().items()
        }
        last_obs = series.dropna().index.max()
        self._cache[series_key] = {
            "fred_id": fred_id,
            "last_fetched": datetime.now().isoformat(),
            "last_observation": last_obs.strftime("%Y-%m-%d") if last_obs is not None else None,
            "n_observations": len(data_dict),
            "data": data_dict,
        }

    def _series_from_cache(self, series_key: str) -> pd.Series:
        entry = self._cache.get(series_key)
        if entry is None or not entry.get("data"):
            return pd.Series(dtype=float)
        data = entry["data"]
        s = pd.Series(data)
        s.index = pd.to_datetime(s.index)
        s = s.sort_index()
        return s

    # ─────────────────────────────────────────────────────
    # Status / introspection (за Data Status Screen)
    # ─────────────────────────────────────────────────────

    def get_cache_status(self, series_key: str) -> dict[str, Any]:
        """Връща {last_fetched, last_observation, n_observations, is_cached}."""
        entry = self._cache.get(series_key)
        if entry is None:
            return {
                "is_cached": False,
                "last_fetched": None,
                "last_observation": None,
                "n_observations": 0,
            }
        return {
            "is_cached": True,
            "last_fetched": entry.get("last_fetched"),
            "last_observation": entry.get("last_observation"),
            "n_observations": entry.get("n_observations", 0),
        }

    def get_snapshot(self, series_keys) -> dict[str, pd.Series]:
        """Връща {series_key: pd.Series} за всички ключове, които имат данни в cache.

        НЕ прави мрежови fetch — чете само локалния cache. Ключове без данни
        (не в cache или с празна серия) просто се пропускат от резултата.

        Използва се от briefing/explorer path-а, където искаме да работим само
        с това, което вече имаме локално (без да висим на мрежата).

        Args:
            series_keys: Iterable от каталожни ключове (обикновено SERIES_CATALOG.keys()).

        Returns:
            dict {key → pd.Series} с DatetimeIndex. Празен ако кеша е празен.
        """
        out: dict[str, pd.Series] = {}
        for key in series_keys:
            s = self._series_from_cache(key)
            if s is not None and not s.empty:
                out[key] = s
        return out

    def invalidate(self, series_key: str) -> None:
        """Изтрива конкретна серия от кеша."""
        self._cache.pop(series_key, None)

    def invalidate_all(self) -> None:
        """Изтрива целия кеш."""
        self._cache.clear()
