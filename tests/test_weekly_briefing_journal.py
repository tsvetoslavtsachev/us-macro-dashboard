"""
tests/test_weekly_briefing_journal.py
=====================================
Тестове за "Свързани бележки" journal секция в briefing-а.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from export.weekly_briefing import generate_weekly_briefing
from scripts._utils import JournalEntry


def _mk_entry(
    title: str,
    topic: str = "credit",
    status: str = "finding",
    entry_date: date = date(2026, 4, 18),
    tags: list[str] | None = None,
) -> JournalEntry:
    return JournalEntry(
        path=Path(f"journal/{topic}/{entry_date.isoformat()}_x.md"),
        date=entry_date,
        topic=topic,
        title=title,
        tags=tags or ["test"],
        status=status,
    )


class TestJournalSectionOptional:

    def test_no_journal_omits_section(self, tmp_path):
        out = tmp_path / "briefing.html"
        generate_weekly_briefing(
            snapshot={},
            output_path=str(out),
            today=date(2026, 4, 18),
            state_dir=None,
            persist_state=False,
            journal_entries=None,
        )
        html = out.read_text(encoding="utf-8")
        assert "Свързани бележки" not in html
        assert '<section class="brief-section journal-section">' not in html

    def test_empty_list_omits_section(self, tmp_path):
        out = tmp_path / "briefing.html"
        generate_weekly_briefing(
            snapshot={},
            output_path=str(out),
            today=date(2026, 4, 18),
            state_dir=None,
            persist_state=False,
            journal_entries=[],
        )
        html = out.read_text(encoding="utf-8")
        assert '<section class="brief-section journal-section">' not in html

    def test_entries_render_section(self, tmp_path):
        entries = [
            _mk_entry("HY спредове без VIX confirmation", topic="credit",
                      tags=["hy_oas", "divergence"]),
            _mk_entry("Sahm rule почти пробит", topic="labor",
                      status="hypothesis", tags=["sahm"]),
        ]
        out = tmp_path / "briefing.html"
        generate_weekly_briefing(
            snapshot={},
            output_path=str(out),
            today=date(2026, 4, 18),
            state_dir=None,
            persist_state=False,
            journal_entries=entries,
        )
        html = out.read_text(encoding="utf-8")
        assert "Свързани бележки" in html
        assert '<section class="brief-section journal-section">' in html
        assert "HY спредове без VIX confirmation" in html
        assert "Sahm rule почти пробит" in html

    def test_entry_metadata_rendered(self, tmp_path):
        entries = [_mk_entry("Credit stress", topic="credit", status="finding",
                             tags=["hy_oas", "ig_spread"])]
        out = tmp_path / "briefing.html"
        generate_weekly_briefing(
            snapshot={},
            output_path=str(out),
            today=date(2026, 4, 18),
            state_dir=None,
            persist_state=False,
            journal_entries=entries,
        )
        html = out.read_text(encoding="utf-8")
        # Дата
        assert "2026-04-18" in html
        # Topic label (БГ)
        assert "Кредит" in html
        # Status label
        assert "Извод" in html
        # Тагове
        assert "hy_oas" in html
        assert "ig_spread" in html

    def test_status_class_applied(self, tmp_path):
        entries = [
            _mk_entry("a", status="open_question"),
            _mk_entry("b", status="finding"),
        ]
        out = tmp_path / "briefing.html"
        generate_weekly_briefing(
            snapshot={},
            output_path=str(out),
            today=date(2026, 4, 18),
            state_dir=None,
            persist_state=False,
            journal_entries=entries,
        )
        html = out.read_text(encoding="utf-8")
        assert "journal-status-open_question" in html
        assert "journal-status-finding" in html

    def test_link_is_relative_to_output_dir(self, tmp_path):
        entries = [_mk_entry("Test", topic="credit")]
        out = tmp_path / "briefing.html"
        generate_weekly_briefing(
            snapshot={},
            output_path=str(out),
            today=date(2026, 4, 18),
            state_dir=None,
            persist_state=False,
            journal_entries=entries,
        )
        html = out.read_text(encoding="utf-8")
        # Linkа е на ../journal/...
        assert 'href="../journal/credit/' in html


class TestBackwardsCompat:

    def test_existing_signature_still_works(self, tmp_path):
        """Без journal_entries kwarg — работи както преди."""
        out = tmp_path / "briefing.html"
        result = generate_weekly_briefing(
            snapshot={},
            output_path=str(out),
            today=date(2026, 4, 18),
            state_dir=None,
            persist_state=False,
        )
        assert Path(result).exists()
        html = out.read_text(encoding="utf-8")
        assert "Executive Summary" in html
        assert "Cross-Lens" in html
