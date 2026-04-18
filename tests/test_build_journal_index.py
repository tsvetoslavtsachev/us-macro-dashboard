"""
tests/test_build_journal_index.py
==================================
Тестове за scripts/build_journal_index.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from scripts._utils import save_journal_entry  # noqa: E402
from scripts.build_journal_index import build_index  # noqa: E402


class TestBuildIndex:

    def test_empty_journal_has_placeholder(self, tmp_path):
        md = build_index(journal_dir=tmp_path)
        assert "Research Journal" in md
        assert "Няма записи" in md

    def test_populated_index_has_toc(self, tmp_path):
        save_journal_entry(topic="credit", title="Test 1", body="b",
                           entry_date=date(2026, 4, 18), journal_dir=tmp_path)
        save_journal_entry(topic="labor", title="Test 2", body="b",
                           entry_date=date(2026, 4, 15), journal_dir=tmp_path)
        md = build_index(journal_dir=tmp_path)
        # Съдържание table
        assert "## Съдържание" in md
        # Topic sections
        assert "## Кредит" in md
        assert "## Трудов пазар" in md
        # Stats
        assert "2 записа" in md

    def test_entries_in_topic_section(self, tmp_path):
        save_journal_entry(topic="credit", title="HY widening", body="b",
                           tags=["hy_oas"], status="finding",
                           entry_date=date(2026, 4, 18), journal_dir=tmp_path)
        md = build_index(journal_dir=tmp_path)
        assert "HY widening" in md
        assert "2026-04-18" in md
        assert "`hy_oas`" in md
        assert "Извод" in md  # статус label

    def test_entries_sorted_descending_per_topic(self, tmp_path):
        save_journal_entry(topic="credit", title="Older", body="b",
                           entry_date=date(2026, 2, 1), journal_dir=tmp_path)
        save_journal_entry(topic="credit", title="Newer", body="b",
                           entry_date=date(2026, 4, 1), journal_dir=tmp_path)
        md = build_index(journal_dir=tmp_path)
        # Newer трябва да се появи преди Older в markdown-а
        assert md.index("Newer") < md.index("Older")

    def test_pipe_in_title_escaped(self, tmp_path):
        """Заглавия със | не трябва да чупят markdown tabelite."""
        save_journal_entry(topic="credit", title="A | B analysis", body="b",
                           entry_date=date(2026, 4, 18), journal_dir=tmp_path)
        md = build_index(journal_dir=tmp_path)
        # Pipe-а трябва да е ескейпнат
        assert "A \\| B analysis" in md

    def test_status_stats_accurate(self, tmp_path):
        save_journal_entry(topic="credit", title="a", body="b", status="open_question",
                           entry_date=date(2026, 4, 18), journal_dir=tmp_path)
        save_journal_entry(topic="credit", title="c", body="b", status="open_question",
                           entry_date=date(2026, 4, 17), journal_dir=tmp_path)
        save_journal_entry(topic="labor", title="d", body="b", status="finding",
                           entry_date=date(2026, 4, 16), journal_dir=tmp_path)
        md = build_index(journal_dir=tmp_path)
        assert "3 записа" in md
        assert "2 отворени въпроса" in md
        assert "1 извода" in md
