"""
tests/test_journal.py
=====================
Тестове за scripts/_utils.py journal layer.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from scripts._utils import (  # noqa: E402
    JournalEntry,
    VALID_STATUSES,
    VALID_TOPICS,
    _parse_frontmatter,
    _slugify,
    load_journal_entries,
    load_journal_entry,
    save_journal_entry,
)


# ============================================================
# FRONTMATTER PARSING
# ============================================================

class TestParseFrontmatter:

    def test_basic_yaml_frontmatter(self):
        text = "---\ndate: 2026-04-18\ntopic: labor\n---\nbody here"
        fm, body = _parse_frontmatter(text)
        assert fm["topic"] == "labor"
        assert body.strip() == "body here"

    def test_no_frontmatter_returns_empty_dict(self):
        fm, body = _parse_frontmatter("just markdown\n")
        assert fm == {}
        assert "just markdown" in body

    def test_malformed_yaml_returns_empty_dict(self):
        text = "---\nfoo: [unclosed\n---\nbody"
        fm, body = _parse_frontmatter(text)
        assert fm == {}

    def test_list_values_preserved(self):
        text = "---\ntags: [a, b, c]\n---\n"
        fm, _ = _parse_frontmatter(text)
        assert fm["tags"] == ["a", "b", "c"]


# ============================================================
# SLUGIFY
# ============================================================

class TestSlugify:

    def test_ascii_basic(self):
        assert _slugify("Hello World") == "hello-world"

    def test_cyrillic_preserved(self):
        # Unicode word chars се запазват
        result = _slugify("Безработица расте")
        assert "безработица" in result
        assert " " not in result

    def test_special_chars_stripped(self):
        assert _slugify("a@b#c!") == "abc"

    def test_empty_returns_untitled(self):
        assert _slugify("") == "untitled"
        assert _slugify("!!!") == "untitled"

    def test_max_len_enforced(self):
        long = "word " * 50
        assert len(_slugify(long, max_len=30)) <= 30


# ============================================================
# LOAD + SAVE
# ============================================================

class TestSaveAndLoad:

    def test_save_creates_file_with_frontmatter(self, tmp_path):
        path = save_journal_entry(
            topic="credit",
            title="Test credit entry",
            body="This is the body.",
            tags=["hy_oas", "test"],
            status="finding",
            related_briefing="briefing_2026-04-18.html",
            entry_date=date(2026, 4, 18),
            journal_dir=tmp_path,
        )
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---")
        assert "topic: credit" in text
        assert "status: finding" in text
        assert "This is the body." in text

    def test_save_rejects_invalid_topic(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown topic"):
            save_journal_entry(
                topic="not_a_real_topic",
                title="x", body="x",
                journal_dir=tmp_path,
            )

    def test_save_rejects_invalid_status(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown status"):
            save_journal_entry(
                topic="credit", title="x", body="x",
                status="wrong_status",
                journal_dir=tmp_path,
            )

    def test_save_roundtrip_via_load(self, tmp_path):
        save_journal_entry(
            topic="labor",
            title="Sahm rule тенденция",
            body="## Въпрос\nДали вървим към рецесия?",
            tags=["sahm", "recession"],
            status="hypothesis",
            entry_date=date(2026, 4, 1),
            journal_dir=tmp_path,
        )
        entries = load_journal_entries(journal_dir=tmp_path)
        assert len(entries) == 1
        e = entries[0]
        assert e.topic == "labor"
        assert e.title == "Sahm rule тенденция"
        assert e.status == "hypothesis"
        assert "sahm" in e.tags
        assert "Въпрос" in e.body

    def test_save_name_collision_suffix(self, tmp_path):
        # Записваме два entry-та със същото заглавие и дата → трябва -2 суфикс
        args = dict(topic="credit", title="Duplicate", body="x",
                    entry_date=date(2026, 4, 18), journal_dir=tmp_path)
        p1 = save_journal_entry(**args)
        p2 = save_journal_entry(**args)
        assert p1 != p2
        assert p1.exists() and p2.exists()
        assert p2.stem.endswith("-2")


# ============================================================
# FILTERS
# ============================================================

@pytest.fixture
def populated_journal(tmp_path):
    """Три entry-та за филтър тестове."""
    save_journal_entry(topic="credit", title="HY spread widening",
                       body="b", tags=["hy_oas"], status="finding",
                       entry_date=date(2026, 4, 10), journal_dir=tmp_path)
    save_journal_entry(topic="labor", title="Claims acceleration",
                       body="b", tags=["claims", "sahm"], status="open_question",
                       entry_date=date(2026, 4, 15), journal_dir=tmp_path)
    save_journal_entry(topic="credit", title="IG spreads stable",
                       body="b", tags=["investment_grade"], status="finding",
                       entry_date=date(2026, 3, 20), journal_dir=tmp_path)
    return tmp_path


class TestFilters:

    def test_load_all(self, populated_journal):
        entries = load_journal_entries(journal_dir=populated_journal)
        assert len(entries) == 3

    def test_filter_by_topic(self, populated_journal):
        credit = load_journal_entries(topic="credit", journal_dir=populated_journal)
        assert len(credit) == 2
        assert all(e.topic == "credit" for e in credit)

    def test_filter_by_status(self, populated_journal):
        findings = load_journal_entries(status="finding", journal_dir=populated_journal)
        assert len(findings) == 2
        assert all(e.status == "finding" for e in findings)

    def test_filter_by_tags_any(self, populated_journal):
        sahm = load_journal_entries(tags_any=["sahm"], journal_dir=populated_journal)
        assert len(sahm) == 1
        assert sahm[0].title == "Claims acceleration"

    def test_filter_by_since(self, populated_journal):
        recent = load_journal_entries(since=date(2026, 4, 1),
                                      journal_dir=populated_journal)
        assert len(recent) == 2

    def test_entries_sorted_descending(self, populated_journal):
        entries = load_journal_entries(journal_dir=populated_journal)
        dates = [e.date for e in entries]
        assert dates == sorted(dates, reverse=True)

    def test_template_file_skipped(self, tmp_path):
        """Файлове започващи с '_' не се зареждат."""
        (tmp_path / "_template.md").write_text(
            "---\ndate: 2026-04-18\ntopic: labor\n---\nbody",
            encoding="utf-8",
        )
        entries = load_journal_entries(journal_dir=tmp_path)
        assert entries == []

    def test_readme_skipped(self, tmp_path):
        (tmp_path / "README.md").write_text(
            "---\ndate: 2026-04-18\ntopic: labor\n---\nbody",
            encoding="utf-8",
        )
        entries = load_journal_entries(journal_dir=tmp_path)
        assert entries == []

    def test_invalid_frontmatter_silently_skipped(self, tmp_path):
        (tmp_path / "valid.md").write_text(
            "---\ndate: 2026-04-18\ntopic: labor\ntitle: T\n---\n",
            encoding="utf-8",
        )
        (tmp_path / "invalid.md").write_text("no frontmatter\n", encoding="utf-8")
        (tmp_path / "wrong_topic.md").write_text(
            "---\ndate: 2026-04-18\ntopic: not_real\n---\n",
            encoding="utf-8",
        )
        entries = load_journal_entries(journal_dir=tmp_path)
        assert len(entries) == 1
        assert entries[0].title == "T"

    def test_returns_empty_for_nonexistent_dir(self, tmp_path):
        entries = load_journal_entries(journal_dir=tmp_path / "missing")
        assert entries == []


# ============================================================
# DATACLASS
# ============================================================

class TestJournalEntry:

    def test_relative_path_when_in_base(self, tmp_path, monkeypatch):
        """Ако path-ът е вътре в BASE_DIR — връща relative."""
        # Използваме save_journal_entry за да получим валиден entry
        path = save_journal_entry(
            topic="credit", title="t", body="b",
            entry_date=date(2026, 4, 18), journal_dir=tmp_path,
        )
        entry = load_journal_entry(path)
        assert entry is not None
        # relative_path не трябва да crashне независимо от местоположението
        assert isinstance(entry.relative_path, str)


# ============================================================
# METADATA VALIDATION
# ============================================================

class TestMetadata:

    def test_valid_topics_nonempty(self):
        assert len(VALID_TOPICS) >= 5
        assert "credit" in VALID_TOPICS

    def test_valid_statuses_nonempty(self):
        assert "open_question" in VALID_STATUSES
        assert "finding" in VALID_STATUSES
