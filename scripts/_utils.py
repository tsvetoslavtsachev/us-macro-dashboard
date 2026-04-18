"""
scripts/_utils.py
=================
Convenience layer за research desk ad hoc анализи.

Тук са boilerplate-а за:
  - Зареждане на FRED cache / briefing snapshot
  - Работа с journal entries (load/save, filter по topic/status/date)
  - Създаване на нови sandbox скриптове с template

НЕ е публичен API. Сигнатурите могат да се променят без notice.

Типичен pattern за sandbox script:

    from pathlib import Path
    import sys
    BASE = Path(__file__).resolve().parent.parent.parent  # econ_v2/
    sys.path.insert(0, str(BASE))
    from scripts._utils import load_briefing_snapshot, save_journal_entry

    snap = load_briefing_snapshot()
    hy = snap["HY_OAS"]
    vix = snap["VIX"]
    # … твоя анализ …
    save_journal_entry(
        topic="credit",
        title="HY спредове без VIX confirmation",
        body="...",
        tags=["hy_oas", "regime_transition"],
        status="finding",
    )
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

# ============================================================
# PATHS
# ============================================================

# scripts/ е в econ_v2/; BASE_DIR = econ_v2/
BASE_DIR = Path(__file__).resolve().parent.parent
JOURNAL_DIR = BASE_DIR / "journal"
SCRIPTS_DIR = BASE_DIR / "scripts"
SANDBOX_DIR = SCRIPTS_DIR / "sandbox"
OUTPUT_DIR = BASE_DIR / "output"

VALID_TOPICS = ["labor", "inflation", "credit", "growth", "analogs", "regime", "methodology"]
VALID_STATUSES = ["open_question", "hypothesis", "finding", "decision"]


# ============================================================
# JOURNAL ENTRY
# ============================================================

@dataclass
class JournalEntry:
    """Структуриран вид на journal запис."""
    path: Path
    date: date
    topic: str
    title: str
    tags: list[str] = field(default_factory=list)
    related_briefing: Optional[str] = None
    related_scripts: list[str] = field(default_factory=list)
    status: str = "open_question"
    body: str = ""

    @property
    def relative_path(self) -> str:
        """Път спрямо econ_v2/ (за линкване в briefing)."""
        try:
            return str(self.path.relative_to(BASE_DIR))
        except ValueError:
            return str(self.path)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Парсва YAML frontmatter от markdown file.

    Формат: файлът започва с '---', следва YAML, след това '---', после body.
    Ако няма frontmatter — връща ({}, text).
    """
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    body = m.group(2)
    return fm, body


def _coerce_date(value) -> Optional[date]:
    """Прави int/str/date → date. None ако не става."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def load_journal_entry(path: Path) -> Optional[JournalEntry]:
    """Чете един .md file и го парсва като JournalEntry.

    Пропуска _template.md и файлове без валиден frontmatter (date + topic).
    Връща None ако файлът е невалиден (не се crashва — просто skip).
    """
    if path.name.startswith("_") or path.name == "README.md":
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    fm, body = _parse_frontmatter(text)
    if not fm:
        return None

    entry_date = _coerce_date(fm.get("date"))
    topic = fm.get("topic")
    if entry_date is None or topic not in VALID_TOPICS:
        return None

    return JournalEntry(
        path=path,
        date=entry_date,
        topic=topic,
        title=str(fm.get("title", path.stem)),
        tags=list(fm.get("tags") or []),
        related_briefing=fm.get("related_briefing"),
        related_scripts=list(fm.get("related_scripts") or []),
        status=fm.get("status", "open_question") if fm.get("status") in VALID_STATUSES else "open_question",
        body=body.strip(),
    )


def load_journal_entries(
    topic: Optional[str] = None,
    status: Optional[str] = None,
    tags_any: Optional[list[str]] = None,
    since: Optional[date] = None,
    journal_dir: Optional[Path] = None,
) -> list[JournalEntry]:
    """Зарежда всички journal entries с optional филтри.

    Args:
        topic: Точно един topic (labor/credit/...) или None за всички.
        status: Точно един статус или None.
        tags_any: Връща entry-та, които имат ПОНЕ един от тези тагове.
        since: Включва само entry-та с date >= since.
        journal_dir: Override на default path (полезно за тестове).

    Returns:
        Списък сортиран по date descending (най-новите първи).
    """
    jdir = journal_dir or JOURNAL_DIR
    if not jdir.exists():
        return []

    entries: list[JournalEntry] = []
    for md in jdir.rglob("*.md"):
        entry = load_journal_entry(md)
        if entry is None:
            continue
        if topic is not None and entry.topic != topic:
            continue
        if status is not None and entry.status != status:
            continue
        if tags_any is not None and not (set(tags_any) & set(entry.tags)):
            continue
        if since is not None and entry.date < since:
            continue
        entries.append(entry)

    entries.sort(key=lambda e: e.date, reverse=True)
    return entries


def save_journal_entry(
    topic: str,
    title: str,
    body: str,
    tags: Optional[list[str]] = None,
    status: str = "open_question",
    related_briefing: Optional[str] = None,
    related_scripts: Optional[list[str]] = None,
    entry_date: Optional[date] = None,
    journal_dir: Optional[Path] = None,
) -> Path:
    """Записва нов journal entry. Връща пътя до записания файл.

    Filename е {date}_{slugified_title}.md. Ако файлът вече съществува —
    добавя се -2, -3 ... суфикс за да не презапишем.
    """
    if topic not in VALID_TOPICS:
        raise ValueError(f"Unknown topic: {topic!r}. Valid: {VALID_TOPICS}")
    if status not in VALID_STATUSES:
        raise ValueError(f"Unknown status: {status!r}. Valid: {VALID_STATUSES}")

    jdir = (journal_dir or JOURNAL_DIR) / topic
    jdir.mkdir(parents=True, exist_ok=True)

    entry_date = entry_date or date.today()
    slug = _slugify(title)
    base_name = f"{entry_date.isoformat()}_{slug}"
    path = jdir / f"{base_name}.md"
    n = 2
    while path.exists():
        path = jdir / f"{base_name}-{n}.md"
        n += 1

    frontmatter = {
        "date": entry_date.isoformat(),
        "topic": topic,
        "title": title,
        "tags": tags or [],
        "related_briefing": related_briefing,
        "related_scripts": related_scripts or [],
        "status": status,
    }
    fm_yaml = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
    path.write_text(f"---\n{fm_yaml}\n---\n\n{body.strip()}\n", encoding="utf-8")
    return path


_SLUG_CLEAN = re.compile(r"[^\w\s-]", re.UNICODE)
_SLUG_SPACES = re.compile(r"[-\s]+")


def _slugify(text: str, max_len: int = 60) -> str:
    """Много проста slugification, Unicode-safe (работи с кирилица)."""
    text = _SLUG_CLEAN.sub("", text.strip().lower())
    text = _SLUG_SPACES.sub("-", text)
    return text[:max_len].strip("-") or "untitled"


# ============================================================
# DATA LOADERS
# ============================================================

def load_briefing_snapshot(base_dir: Optional[Path] = None) -> dict[str, pd.Series]:
    """Зарежда последния FRED snapshot от cache-а.

    Lazy import на FredAdapter — за да няма import overhead при чисти journal
    операции (например build_journal_index).
    """
    from sources.fred_adapter import FredAdapter
    from catalog.series import SERIES_CATALOG

    adapter = FredAdapter(api_key="x", base_dir=base_dir or BASE_DIR)
    return adapter.get_snapshot(SERIES_CATALOG.keys())


def load_analog_series(base_dir: Optional[Path] = None) -> dict[str, pd.Series]:
    """Зарежда ANALOG_* серии от cache (deep-history за analog engine)."""
    from sources.fred_adapter import FredAdapter
    from analysis.macro_vector import ANALOG_FETCH_SPEC

    adapter = FredAdapter(api_key="x", base_dir=base_dir or BASE_DIR)
    out = {}
    for spec in ANALOG_FETCH_SPEC:
        out[spec["key"]] = adapter._series_from_cache(spec["key"])
    return out


def latest_briefing_path(output_dir: Optional[Path] = None) -> Optional[Path]:
    """Пътя до най-скорошния briefing_YYYY-MM-DD.html в output/."""
    odir = output_dir or OUTPUT_DIR
    if not odir.exists():
        return None
    candidates = sorted(odir.glob("briefing_*.html"))
    return candidates[-1] if candidates else None


def load_current_briefing_html(output_dir: Optional[Path] = None) -> Optional[str]:
    """Текста на последния briefing (ако има такъв)."""
    p = latest_briefing_path(output_dir)
    if p is None:
        return None
    return p.read_text(encoding="utf-8")


# ============================================================
# SANDBOX SCRIPT SCAFFOLDING
# ============================================================

_SANDBOX_TEMPLATE = '''"""
sandbox/{filename}
==================
Ad hoc анализ — {title}

Създаден: {date}
Свързан journal запис: (попълни ръчно след save_journal_entry)
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent  # econ_v2/
sys.path.insert(0, str(BASE))

import pandas as pd
import numpy as np

from scripts._utils import (
    load_briefing_snapshot,
    load_analog_series,
    save_journal_entry,
)


# ============================================================
# 1. ВЪПРОС
# ============================================================
# Какво питаме? Защо е интересно? Какво очакваме да видим?
# Един параграф — ще отиде като body на journal entry-то.

QUESTION = """
{title}

TODO: опиши въпроса в 2-4 изречения.
"""


# ============================================================
# 2. ДАННИ
# ============================================================
# Зарежда серии от cache. Ако серия не е в snapshot-а — виж
# catalog/series.py за регистрираните ticker-и.

def load_data() -> dict:
    snap = load_briefing_snapshot()
    # TODO: извади конкретните серии, от които имаш нужда
    # hy = snap["HY_OAS"]
    # vix = snap["VIX"]
    return {{"snapshot": snap}}


# ============================================================
# 3. АНАЛИЗ
# ============================================================
# Тук живее логиката — z-scores, rolling stats, correlations, etc.
# Връщай dict със стойностите, които после ще форматираш в Извода.

def analyze(data: dict) -> dict:
    # TODO: твоят анализ
    return {{}}


# ============================================================
# 4. ИЗВОД
# ============================================================
# Форматирай в markdown body (ще стане journal entry ако struva).

def format_finding(result: dict) -> str:
    # TODO: напиши извода като markdown
    return f\"\"\"
## Въпрос

{{QUESTION.strip()}}

## Данни

TODO

## Анализ

TODO

## Извод

TODO
\"\"\".strip()


def main() -> None:
    data = load_data()
    result = analyze(data)
    finding = format_finding(result)
    print(finding)

    # Ако анализът е стойностен — разкомeнтирай и запиши в journal.
    # Ако не струва — остави sandbox-а като scratch и не пиши entry.
    #
    # save_journal_entry(
    #     topic="credit",          # labor/inflation/credit/growth/analogs/regime/methodology
    #     title="{title}",
    #     body=finding,
    #     tags=[],
    #     status="open_question",  # open_question / hypothesis / finding / decision
    #     related_scripts=[Path(__file__).name],
    # )


if __name__ == "__main__":
    main()
'''


def new_sandbox_script(title: str, sandbox_dir: Optional[Path] = None) -> Path:
    """Създава нов sandbox script с template. Връща пътя.

    Filename format: YYYY-MM-DD_slug.py
    """
    sdir = sandbox_dir or SANDBOX_DIR
    sdir.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    slug = _slugify(title)
    base = f"{today}_{slug}"
    path = sdir / f"{base}.py"
    n = 2
    while path.exists():
        path = sdir / f"{base}-{n}.py"
        n += 1

    path.write_text(
        _SANDBOX_TEMPLATE.format(filename=path.name, title=title, date=today),
        encoding="utf-8",
    )
    return path
