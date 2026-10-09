"""Сензор за застинал локален кеш (ЕВРО1, 09.10.2026; близнак на европейския).

data/fred_cache.json е в .gitignore: workflow-ите опресняват FRED само в
облака, а тук кешът се опреснява единствено с локален `run.py`. От 08.07 до
09.10.2026 стоя тихо три месеца. Този модул казва на глас колко са
стари, по последния `last_fetched` във всеки файл (резерв: датата на файла).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

API_CACHES = ("fred",)
MAX_AGE_DAYS = 14  # две пропуснати седмици


def _parse(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def cache_ages(data_dir: Path, now: Optional[datetime] = None) -> dict[str, Optional[float]]:
    """{източник: дни от последното опресняване}; None, ако файлът липсва или не се чете."""
    now = now or datetime.now()
    out: dict[str, Optional[float]] = {}
    for src in API_CACHES:
        path = Path(data_dir) / f"{src}_cache.json"
        if not path.exists():
            out[src] = None
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            out[src] = None
            continue
        stamps = [
            _parse(v.get("last_fetched"))
            for v in (data.values() if isinstance(data, dict) else [])
            if isinstance(v, dict)
        ]
        stamps = [s for s in stamps if s]
        last = max(stamps) if stamps else datetime.fromtimestamp(path.stat().st_mtime)
        out[src] = (now - last).total_seconds() / 86400.0
    return out


def stale_caches(
    data_dir: Path, max_age_days: float = MAX_AGE_DAYS, now: Optional[datetime] = None,
) -> dict[str, Optional[float]]:
    """Само източниците, които липсват или са по-стари от max_age_days."""
    return {
        src: age for src, age in cache_ages(data_dir, now).items()
        if age is None or age > max_age_days
    }


def format_warning(stale: dict[str, Optional[float]], max_age_days: float = MAX_AGE_DAYS) -> str:
    if not stale:
        return ""
    parts = [f"{src} {'липсва' if age is None else f'{age:.0f} дни'}" for src, age in stale.items()]
    return (
        f"⚠ ЗАСТИНАЛ КЕШ (над {max_age_days:g} дни): " + " · ".join(parts)
        + "\n  Пусни: python run.py --refresh-only"
    )
