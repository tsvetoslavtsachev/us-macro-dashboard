"""
scripts/build_journal_index.py
==============================
Сканира journal/ и строи README.md — таблица с всички запис, групирани
по topic, сортирани по date descending. Не ползва темплейти — чист
markdown output.

Usage:
    python scripts/build_journal_index.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from scripts._utils import (  # noqa: E402
    JOURNAL_DIR,
    VALID_TOPICS,
    JournalEntry,
    load_journal_entries,
)


TOPIC_LABELS_BG = {
    "labor":       "Трудов пазар",
    "inflation":   "Инфлация",
    "credit":      "Кредит",
    "growth":      "Растеж",
    "analogs":     "Исторически аналози",
    "regime":      "Режими",
    "methodology": "Методология",
}

STATUS_LABELS_BG = {
    "open_question": "❓ Отворен въпрос",
    "hypothesis":    "🧪 Хипотеза",
    "finding":       "✓ Извод",
    "decision":      "◆ Решение",
}


def build_index(journal_dir: Path = JOURNAL_DIR) -> str:
    """Връща markdown текст на индекса."""
    entries = load_journal_entries(journal_dir=journal_dir)
    by_topic: dict[str, list[JournalEntry]] = defaultdict(list)
    for e in entries:
        by_topic[e.topic].append(e)

    lines: list[str] = []
    lines.append("# Research Journal")
    lines.append("")
    lines.append("Структурирани записи от анализа. Всеки файл е markdown с ")
    lines.append("YAML frontmatter. Индексът е автоматично генериран — ")
    lines.append("не редактирай директно. Регенерирай с:")
    lines.append("")
    lines.append("```")
    lines.append("python scripts/build_journal_index.py")
    lines.append("```")
    lines.append("")

    # Summary stats
    total = len(entries)
    open_qs = sum(1 for e in entries if e.status == "open_question")
    findings = sum(1 for e in entries if e.status == "finding")
    lines.append(f"**Статистика:** {total} записа · "
                 f"{open_qs} отворени въпроса · {findings} извода")
    lines.append("")

    if total == 0:
        lines.append("*Няма записи. Създай първия с шаблона в `journal/_template.md` "
                     "или чрез `scripts._utils.save_journal_entry(...)`.*")
        lines.append("")
        return "\n".join(lines)

    # Table of contents
    lines.append("## Съдържание")
    lines.append("")
    for topic in VALID_TOPICS:
        count = len(by_topic.get(topic, []))
        if count == 0:
            continue
        label = TOPIC_LABELS_BG.get(topic, topic)
        anchor = topic.replace("_", "-")
        lines.append(f"- [{label}](#{anchor}) ({count})")
    lines.append("")

    # Per-topic sections
    for topic in VALID_TOPICS:
        topic_entries = by_topic.get(topic, [])
        if not topic_entries:
            continue
        label = TOPIC_LABELS_BG.get(topic, topic)
        lines.append(f"## {label}")
        lines.append("")
        lines.append("| Дата | Заглавие | Статус | Тагове |")
        lines.append("|------|----------|--------|--------|")
        for e in topic_entries:
            rel = e.relative_path.replace("\\", "/")
            # markdown-safe заглавие
            safe_title = e.title.replace("|", "\\|")
            status_label = STATUS_LABELS_BG.get(e.status, e.status)
            tags_str = ", ".join(f"`{t}`" for t in e.tags) if e.tags else "—"
            lines.append(f"| {e.date.isoformat()} | [{safe_title}]({rel}) | "
                         f"{status_label} | {tags_str} |")
        lines.append("")

    return "\n".join(lines)


def write_index(journal_dir: Path = JOURNAL_DIR) -> Path:
    """Build + write README.md. Връща пътя."""
    out = journal_dir / "README.md"
    out.write_text(build_index(journal_dir), encoding="utf-8")
    return out


if __name__ == "__main__":
    path = write_index()
    print(f"✅ Журнал индекс записан: {path.relative_to(BASE)}")
