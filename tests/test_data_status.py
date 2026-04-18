"""
Tests за export/data_status.py
==============================
Проверяваме classification, row building и HTML generation с mock data.
"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from export.data_status import (
    classify_status,
    _build_row,
    render_html,
    generate_data_status,
    EXPECTED_LAG_DAYS,
    KNOWN_DELAYS,
)


# ============================================================
# classify_status
# ============================================================

def test_classify_updated_today():
    today = date(2026, 4, 17)
    status, days, exp = classify_status("weekly", "2026-04-17", today=today)
    assert status == "updated_today"
    assert days == 0


def test_classify_fresh_monthly():
    today = date(2026, 4, 17)
    # 3 weeks lag is fine for monthly (expected 45 days)
    status, days, exp = classify_status("monthly", "2026-03-25", today=today)
    assert status == "fresh"
    assert days == 23


def test_classify_delayed_weekly_outside_window():
    today = date(2026, 4, 17)
    # 26 days lag on weekly series (expected 14) → delayed (> 14 but < 28)
    # 2026-03-22 e ИЗВЪН KNOWN_DELAYS window (ends 2026-03-15)
    status, days, exp = classify_status("weekly", "2026-03-22", today=today)
    assert status == "delayed"
    assert days == 26


def test_classify_stale_monthly():
    today = date(2026, 4, 17)
    # 200 days lag → stale (>> 45×2)
    status, days, exp = classify_status("monthly", "2025-09-30", today=today)
    # Но 2025-09-30 е преди KNOWN_DELAYS (2025-10-01) → stale, не explained
    assert status == "stale"


def test_classify_delayed_explained_shutdown():
    today = date(2026, 4, 17)
    # Last obs 2025-11-01 е в admin shutdown window → delayed_explained
    status, days, exp = classify_status("monthly", "2025-11-01", today=today)
    assert status == "delayed_explained"
    assert "shutdown" in exp.lower() or "admin" in exp.lower()


def test_classify_no_data():
    status, days, exp = classify_status("monthly", None)
    assert status == "no_data"
    assert days == -1


def test_classify_invalid_date():
    status, days, exp = classify_status("monthly", "not-a-date")
    assert status == "no_data"


def test_classify_weekly_fresh():
    today = date(2026, 4, 17)
    status, days, exp = classify_status("weekly", "2026-04-10", today=today)
    assert status == "fresh"
    assert days == 7


# ============================================================
# _build_row
# ============================================================

def test_build_row_fresh_fred():
    today = date(2026, 4, 17)
    meta = {
        "source": "fred",
        "id": "UNRATE",
        "name_bg": "Безработица",
        "name_en": "Unemployment Rate",
        "lens": ["labor"],
        "peer_group": "unemployment",
        "tags": [],
        "release_schedule": "monthly",
        "typical_release": "first_friday",
        "revision_prone": False,
    }
    cache_status = {
        "is_cached": True,
        "last_fetched": "2026-04-17T08:00:00",
        "last_observation": "2026-03-25",  # 23 дни behind, под 45 → fresh
        "n_observations": 200,
    }
    row = _build_row("UNRATE", meta, cache_status, today)
    assert row["status"] == "fresh"
    assert row["key"] == "UNRATE"
    assert row["lens"] == "labor"
    assert row["fred_id"] == "UNRATE"


def test_build_row_pending():
    today = date(2026, 4, 17)
    meta = {
        "source": "pending",
        "id": "FRBATLWGT",
        "name_bg": "Atlanta Fed Wage Tracker",
        "name_en": "Atlanta Fed Wage Growth Tracker",
        "lens": ["labor"],
        "peer_group": "wage_dynamics",
        "tags": [],
        "release_schedule": "monthly",
        "typical_release": "mid_month",
        "revision_prone": False,
    }
    cache_status = {"is_cached": False, "last_observation": None, "n_observations": 0}
    row = _build_row("FRBATLWGT", meta, cache_status, today)
    assert row["status"] == "pending"


def test_build_row_no_cache():
    today = date(2026, 4, 17)
    meta = {
        "source": "fred",
        "id": "UNRATE",
        "name_bg": "X",
        "name_en": "X",
        "lens": ["labor"],
        "peer_group": "unemployment",
        "tags": [],
        "release_schedule": "monthly",
        "typical_release": "",
        "revision_prone": False,
    }
    cache_status = {"is_cached": False, "last_observation": None, "n_observations": 0}
    row = _build_row("UNRATE", meta, cache_status, today)
    assert row["status"] == "no_data"


# ============================================================
# render_html — smoke
# ============================================================

def test_render_html_basic():
    today = date(2026, 4, 17)
    rows = [
        {
            "key": "UNRATE",
            "fred_id": "UNRATE",
            "source": "fred",
            "name_bg": "Безработица",
            "name_en": "Unemployment Rate",
            "lens": "labor",
            "peer_group": "unemployment",
            "tags": ["non_consensus"],
            "release_schedule": "monthly",
            "typical_release": "first_friday",
            "last_observation": "2026-03-01",
            "last_fetched": "2026-04-17T08:00:00",
            "n_obs": 200,
            "status": "fresh",
            "days_behind": 47,
            "explanation": "",
            "revision_prone": True,
            "narrative_hint": "",
        },
        {
            "key": "NAPMPMI",
            "fred_id": "NAPMPMI",
            "source": "pending",
            "name_bg": "ISM PMI",
            "name_en": "ISM Manufacturing PMI",
            "lens": "growth",
            "peer_group": "surveys",
            "tags": [],
            "release_schedule": "monthly",
            "typical_release": "first_bday",
            "last_observation": "—",
            "last_fetched": "—",
            "n_obs": 0,
            "status": "pending",
            "days_behind": -1,
            "explanation": "Pending integration.",
            "revision_prone": False,
            "narrative_hint": "",
        },
    ]
    html = render_html(rows, today=today)
    # Sanity checks
    assert "<!DOCTYPE html>" in html
    assert "Data Status Screen" in html
    assert "UNRATE" in html
    assert "NAPMPMI" in html
    assert "labor" in html
    assert "growth" in html
    # No unfilled format placeholders
    assert "{counts[" not in html
    assert "{today" not in html
    assert "{rows_html" not in html
    # Summary cards must exist
    assert "Общо серии" in html
    # Filter dropdowns must exist
    assert "filter-lens" in html
    assert "filter-status" in html


def test_render_html_empty():
    today = date(2026, 4, 17)
    html = render_html([], today=today)
    assert "<!DOCTYPE html>" in html
    # Summary still renders with zeros
    assert ">0<" in html or "0</" in html


# ============================================================
# generate_data_status — integration with mock adapter
# ============================================================

class MockAdapter:
    def __init__(self, cache_map):
        self._cache = cache_map

    def get_cache_status(self, series_key):
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


def test_generate_data_status_with_mock_catalog(tmp_path):
    today = date(2026, 4, 17)

    catalog = {
        "UNRATE": {
            "source": "fred",
            "id": "UNRATE",
            "name_bg": "Безработица",
            "name_en": "Unemployment Rate",
            "lens": ["labor"],
            "peer_group": "unemployment",
            "tags": [],
            "release_schedule": "monthly",
            "typical_release": "first_friday",
            "revision_prone": False,
        },
        "ICSA": {
            "source": "fred",
            "id": "ICSA",
            "name_bg": "Заявки за помощи (weekly)",
            "name_en": "Initial Claims",
            "lens": ["labor"],
            "peer_group": "claims",
            "tags": ["non_consensus"],
            "release_schedule": "weekly",
            "typical_release": "thursday",
            "revision_prone": False,
        },
        "NAPMPMI": {
            "source": "pending",
            "id": "NAPMPMI",
            "name_bg": "ISM PMI",
            "name_en": "ISM Manufacturing PMI",
            "lens": ["growth"],
            "peer_group": "surveys",
            "tags": [],
            "release_schedule": "monthly",
            "typical_release": "first_bday",
            "revision_prone": False,
        },
    }

    adapter = MockAdapter({
        "UNRATE": {"last_fetched": "2026-04-17T08:00:00", "last_observation": "2026-03-01", "n_observations": 200},
        "ICSA":   {"last_fetched": "2026-04-17T08:05:00", "last_observation": "2026-04-12", "n_observations": 500},
    })

    out_path = generate_data_status(adapter, catalog, tmp_path, today=today)
    assert out_path.exists()
    assert out_path.suffix == ".html"
    content = out_path.read_text(encoding="utf-8")
    assert "UNRATE" in content
    assert "ICSA" in content
    assert "NAPMPMI" in content
    # NAPMPMI трябва да е pending
    assert "status-pending" in content
    # UNRATE е fresh
    assert "status-fresh" in content
