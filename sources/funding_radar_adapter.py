"""
sources/funding_radar_adapter.py
================================
Health-aware HTTP consumer за Treasury Funding Radar `funding_state.json`.

Радарът е отделно standalone репо (Зона 1 сетиво — leading funding-стрес),
публикуван no-auth на GitHub Pages. Тук НЕ преизчисляваме нищо — само
консумираме готовия composite + verdict + per-lamp статус и го показваме
честно. Stale / dead source / fetch fail → казваме го; НИКОГА silent zero.

Контракт (vrm-state модел, schema_version=1):
  {
    "schema_version": 1,
    "as_of": "<ISO datetime>",        # напр. 2026-06-22T18:54:14+00:00
    "composite_score": 0.0,           # 0–10
    "verdict": "<BG присъда>",
    "lamp_status": {"1": "green", ..., "5": "green"},
    "any_dead_source": false
  }

Дизайн:
  - urllib (stdlib) — нула външни зависимости, мач с репо конвенцията.
    Пазим standalone принципа: HTTP fetch на публикувания JSON, не крос-репо
    файлов достъп.
  - identity guard: валидираме schema_version + всички задължителни полета;
    при разминаване ВДИГАМЕ FundingStateError (не coerce-ваме) — ако радарът
    смени контракта, гърмим шумно вместо да рендираме боклук.
  - cache-first fallback: при fetch fail четем последния кеш и маркираме
    degraded; при липсващ кеш → available=False (state=None, никога 0).
  - staleness: age = today − as_of (дни); > STALE_AFTER_DAYS → stale флаг.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

FUNDING_STATE_URL = (
    "https://tsvetoslavtsachev.github.io/treasury-funding-radar/data/funding_state.json"
)
CACHE_FILENAME = "funding_state_cache.json"
REQUEST_TIMEOUT_SECONDS = 15
EXPECTED_SCHEMA_VERSION = 1
# Радарът се обновява делнично (CI 12:30 UTC). >4 календарни дни от as_of
# покрива дълъг уикенд + един пропуснат ден и пак е подозрително.
STALE_AFTER_DAYS = 4

REQUIRED_KEYS = (
    "schema_version", "as_of", "composite_score",
    "verdict", "lamp_status", "any_dead_source",
)
LAMP_KEYS = ("1", "2", "3", "4", "5")

# ─── Per-lamp семантика (единствен източник за двата рендера: briefing_context
#     .md секция + weekly HTML карта). Етикетите са структурни имена по
#     документацията на радара — funding_state дава само цвят на лампа 1–5. ───
FUNDING_LAMP_LABELS = {
    "1": "Банково репо (H.8)",
    "2": "Fed водопровод (резерви · RRP · SRF)",
    "3": "Цена на парите (SOFR − IORB)",
    "4": "Аукциони (bid-to-cover · PD дял)",
    "5": "Ливъридж (репо обем · CFTC позиции)",
}
# цвят → (emoji, BG дума) за текстов рендер
FUNDING_LAMP_COLOR_BG = {
    "green":  ("🟢", "спокойно"),
    "amber":  ("🟡", "напрежение"),
    "yellow": ("🟡", "напрежение"),
    "red":    ("🔴", "стрес"),
}
# цвят → hex (GitHub-dark палитра на dashboard-а) за HTML рендер
FUNDING_LAMP_COLOR_HEX = {
    "green":  "#3fb950",
    "amber":  "#d29922",
    "yellow": "#d29922",
    "red":    "#f85149",
}


def worst_lamp_color(lamp_status: dict) -> str:
    """Най-тежкият цвят сред лампите (red > amber > green) — за headline цвят.

    Извлечено от собствените лампи на радара, НЕ от изобретен числов праг.
    """
    colors = {str(v).lower() for v in (lamp_status or {}).values()}
    if "red" in colors:
        return "red"
    if "amber" in colors or "yellow" in colors:
        return "amber"
    if "green" in colors:
        return "green"
    return "unknown"


class FundingStateError(Exception):
    """funding_state не отговаря на очаквания контракт (identity guard)."""


# ============================================================
# Fetch / validate / cache (ниско ниво)
# ============================================================

def _fetch_remote(
    url: str = FUNDING_STATE_URL,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> dict:
    """GET на публикувания JSON. Вдига при HTTP / URL / parse грешка."""
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "us-macro-dashboard/funding-consumer",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def _validate(payload: object) -> dict:
    """Identity guard. Връща payload-а ако е валиден; иначе FundingStateError."""
    if not isinstance(payload, dict):
        raise FundingStateError(
            f"очаквах JSON обект, получих {type(payload).__name__}"
        )
    missing = [k for k in REQUIRED_KEYS if k not in payload]
    if missing:
        raise FundingStateError(f"липсващи полета: {missing}")

    sv = payload.get("schema_version")
    if sv != EXPECTED_SCHEMA_VERSION:
        raise FundingStateError(
            f"schema_version={sv!r}, очаквах {EXPECTED_SCHEMA_VERSION} — "
            "контрактът се е сменил, не рендирам сляпо"
        )
    if not isinstance(payload.get("composite_score"), (int, float)):
        raise FundingStateError("composite_score не е число")
    if not isinstance(payload.get("verdict"), str):
        raise FundingStateError("verdict не е низ")
    if not isinstance(payload.get("any_dead_source"), bool):
        raise FundingStateError("any_dead_source не е bool")

    lamps = payload.get("lamp_status")
    if not isinstance(lamps, dict):
        raise FundingStateError("lamp_status не е обект")
    missing_lamps = [k for k in LAMP_KEYS if k not in lamps]
    if missing_lamps:
        raise FundingStateError(f"lamp_status липсват лампи: {missing_lamps}")
    return payload


def _as_of_date(payload: dict) -> Optional[date]:
    """Парсва as_of (ISO datetime ИЛИ date) до date. None при невалиден."""
    raw = payload.get("as_of")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None


def _write_cache(path: Path, payload: dict, fetched_at: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"fetched_at": fetched_at, "payload": payload},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as e:  # кешът е удобство, не критичен път
        logger.warning("funding_state кеш не може да се запише: %s", e)


def _read_cache(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("funding_state кеш не може да се прочете: %s", e)
        return None


# ============================================================
# View builders
# ============================================================

def _build_view(payload: dict, source: str, today: date,
                fetched_at: Optional[str]) -> dict:
    as_of = _as_of_date(payload)
    age_days = (today - as_of).days if as_of is not None else None
    stale = age_days is not None and age_days > STALE_AFTER_DAYS
    dead = bool(payload.get("any_dead_source"))

    notes: list[str] = []
    if source == "cache":
        notes.append("fetch fail → последен кеш")
    if stale and age_days is not None:
        notes.append(f"остарял ({age_days}д от as_of)")
    if dead:
        notes.append("радарът докладва мъртъв източник")

    return {
        "available": True,
        "source": source,                       # "live" | "cache"
        "fetched_at": fetched_at,
        "as_of": payload.get("as_of"),
        "age_days": age_days,
        "stale": stale,
        "any_dead_source": dead,
        "health_note": "; ".join(notes) if notes else "свеж",
        "state": payload,
    }


def _unavailable_view(reason: str) -> dict:
    return {
        "available": False,
        "source": "none",
        "fetched_at": None,
        "as_of": None,
        "age_days": None,
        "stale": False,
        "any_dead_source": False,
        "health_note": reason,
        "state": None,
    }


# ============================================================
# Public API
# ============================================================

def load_funding_state(
    base_dir: str | Path,
    *,
    today: Optional[date] = None,
    refresh: bool = True,
    url: str = FUNDING_STATE_URL,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> dict:
    """Зарежда funding_state като health-aware view.

    Връща dict с ключове:
      available (bool) · source ("live"|"cache"|"none") · fetched_at ·
      as_of · age_days · stale (bool) · any_dead_source (bool) ·
      health_note (str) · state (валидиран payload | None).

    Никога не вдига — мрежов/схемен проблем се рамкира честно във view-то,
    за да не чупи briefing pipeline-а (мач с external_loader философията).
    """
    if today is None:
        today = date.today()
    cache_path = Path(base_dir) / "data" / CACHE_FILENAME

    if refresh:
        try:
            payload = _validate(_fetch_remote(url, timeout))
            fetched_at = datetime.now(timezone.utc).isoformat()
            _write_cache(cache_path, payload, fetched_at)
            return _build_view(payload, "live", today, fetched_at)
        except FundingStateError as e:
            # Схемата на живо е счупена → не сляпо рендиране; пробвай кеша
            # (може да е валиден стар контракт), иначе → недостъпен.
            logger.warning("funding_state схема невалидна на живо: %s", e)
        except (urllib.error.URLError, urllib.error.HTTPError,
                TimeoutError, OSError, ValueError) as e:
            logger.warning("funding_state fetch fail: %s", e)

    cached = _read_cache(cache_path)
    if cached is not None:
        try:
            payload = _validate(cached.get("payload", {}))
        except FundingStateError as e:
            logger.warning("кешираният funding_state е невалиден: %s", e)
            return _unavailable_view(f"кеш невалиден ({e})")
        return _build_view(payload, "cache", today, cached.get("fetched_at"))

    return _unavailable_view("радарът е недостъпен (няма fetch, няма кеш)")
