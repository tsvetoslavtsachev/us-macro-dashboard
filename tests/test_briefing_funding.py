"""
tests/test_briefing_funding.py
==============================
Тестове за Treasury Funding Radar consumer-а:
  - sources/funding_radar_adapter.py  (fetch · identity guard · cache · health)
  - export/briefing_context._render_funding_radar  (честно рендиране)

Всичко офлайн / детерминистично — `_fetch_remote` се мокне, нула мрежа.
Принципи под тест: identity guard (schema), no silent zero, staleness,
any_dead_source, cache fallback.
"""
from __future__ import annotations

import sys
import urllib.error
from datetime import date
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import sources.funding_radar_adapter as fra
from sources.funding_radar_adapter import (
    FundingStateError,
    _validate,
    load_funding_state,
    worst_lamp_color,
)
from export.briefing_context import _render_funding_radar
from export.weekly_briefing import _render_funding_card


VALID_PAYLOAD = {
    "schema_version": 1,
    "as_of": "2026-06-22T18:54:14+00:00",
    "composite_score": 0.0,
    "verdict": "Спокойно финансиране",
    "lamp_status": {"1": "green", "2": "green", "3": "green", "4": "green", "5": "green"},
    "any_dead_source": False,
}

TODAY = date(2026, 6, 22)


# ============================================================
# identity guard (_validate)
# ============================================================

class TestValidate:
    def test_accepts_valid(self):
        assert _validate(dict(VALID_PAYLOAD)) == VALID_PAYLOAD

    def test_rejects_wrong_schema_version(self):
        bad = dict(VALID_PAYLOAD, schema_version=2)
        with pytest.raises(FundingStateError, match="schema_version"):
            _validate(bad)

    def test_rejects_missing_key(self):
        bad = {k: v for k, v in VALID_PAYLOAD.items() if k != "verdict"}
        with pytest.raises(FundingStateError, match="липсващи полета"):
            _validate(bad)

    def test_rejects_missing_lamp(self):
        bad = dict(VALID_PAYLOAD, lamp_status={"1": "green", "2": "green"})
        with pytest.raises(FundingStateError, match="липсват лампи"):
            _validate(bad)

    def test_rejects_non_numeric_score(self):
        bad = dict(VALID_PAYLOAD, composite_score="0.0")
        with pytest.raises(FundingStateError, match="composite_score"):
            _validate(bad)

    def test_rejects_non_dict(self):
        with pytest.raises(FundingStateError):
            _validate(["not", "a", "dict"])


# ============================================================
# load_funding_state (orchestrator)
# ============================================================

class TestLoad:
    def test_live_success(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fra, "_fetch_remote", lambda *a, **k: dict(VALID_PAYLOAD))
        view = load_funding_state(tmp_path, today=TODAY, refresh=True)
        assert view["available"] is True
        assert view["source"] == "live"
        assert view["stale"] is False
        assert view["state"]["composite_score"] == 0.0
        # кешът е записан
        assert (tmp_path / "data" / fra.CACHE_FILENAME).exists()

    def test_fetch_fail_falls_back_to_cache(self, tmp_path, monkeypatch):
        # 1) успешен live → пише кеш
        monkeypatch.setattr(fra, "_fetch_remote", lambda *a, **k: dict(VALID_PAYLOAD))
        load_funding_state(tmp_path, today=TODAY, refresh=True)
        # 2) fetch гръмва → пада на кеша
        def boom(*a, **k):
            raise urllib.error.URLError("down")
        monkeypatch.setattr(fra, "_fetch_remote", boom)
        view = load_funding_state(tmp_path, today=TODAY, refresh=True)
        assert view["available"] is True
        assert view["source"] == "cache"
        assert "fetch fail" in view["health_note"]

    def test_no_cache_no_fetch_is_unavailable_not_zero(self, tmp_path, monkeypatch):
        def boom(*a, **k):
            raise urllib.error.URLError("down")
        monkeypatch.setattr(fra, "_fetch_remote", boom)
        view = load_funding_state(tmp_path, today=TODAY, refresh=True)
        assert view["available"] is False
        assert view["state"] is None  # no silent zero — няма измислено число

    def test_staleness_flag(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fra, "_fetch_remote", lambda *a, **k: dict(VALID_PAYLOAD))
        future = date(2026, 7, 5)  # 13 дни след as_of
        view = load_funding_state(tmp_path, today=future, refresh=True)
        assert view["stale"] is True
        assert view["age_days"] == 13

    def test_invalid_live_schema_without_cache_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fra, "_fetch_remote",
                            lambda *a, **k: dict(VALID_PAYLOAD, schema_version=99))
        view = load_funding_state(tmp_path, today=TODAY, refresh=True)
        assert view["available"] is False
        assert view["state"] is None


# ============================================================
# _render_funding_radar (честно рендиране)
# ============================================================

def _view(**over):
    base = {
        "available": True, "source": "live", "fetched_at": None,
        "as_of": VALID_PAYLOAD["as_of"], "age_days": 0, "stale": False,
        "any_dead_source": False, "health_note": "свеж",
        "state": dict(VALID_PAYLOAD),
    }
    base.update(over)
    return base


class TestRender:
    def test_available_shows_composite_verdict_all_lamps(self):
        md = _render_funding_radar(_view(), TODAY)
        assert "Стабилност на финансирането" in md
        assert "0.0 / 10" in md
        assert "Спокойно финансиране" in md
        # всичките 5 лампи присъстват
        for k in ("1", "2", "3", "4", "5"):
            assert f"| {k} |" in md
        assert "🟢" in md

    def test_unavailable_is_honest_not_zero(self):
        md = _render_funding_radar(_view(available=False, state=None,
                                         health_note="няма fetch, няма кеш"), TODAY)
        assert "недостъпен" in md
        assert "не 0" in md
        assert "0.0 / 10" not in md  # НЕ измисля композит

    def test_none_view_is_honest(self):
        md = _render_funding_radar(None, TODAY)
        assert "недостъпен" in md
        assert "0.0 / 10" not in md

    def test_stale_flag_surfaces(self):
        md = _render_funding_radar(_view(stale=True, age_days=9), TODAY)
        assert "остарял" in md

    def test_dead_source_flag_surfaces(self):
        st = dict(VALID_PAYLOAD, any_dead_source=True)
        md = _render_funding_radar(_view(any_dead_source=True, state=st), TODAY)
        assert "мъртъв източник" in md

    def test_cache_source_flag_surfaces(self):
        md = _render_funding_radar(_view(source="cache"), TODAY)
        assert "кеширан" in md

    def test_red_lamp_renders_stress(self):
        st = dict(VALID_PAYLOAD,
                  lamp_status={"1": "green", "2": "red", "3": "amber",
                               "4": "green", "5": "green"},
                  composite_score=4.0, verdict="Повишено напрежение")
        md = _render_funding_radar(_view(state=st), TODAY)
        assert "🔴" in md and "стрес" in md
        assert "🟡" in md and "напрежение" in md
        assert "4.0 / 10" in md


# ============================================================
# worst_lamp_color (headline цвят — от радара, не изобретен праг)
# ============================================================

class TestWorstColor:
    def test_all_green(self):
        assert worst_lamp_color({"1": "green", "2": "green"}) == "green"

    def test_amber_beats_green(self):
        assert worst_lamp_color({"1": "green", "2": "amber"}) == "amber"

    def test_red_beats_all(self):
        assert worst_lamp_color({"1": "green", "2": "amber", "3": "red"}) == "red"

    def test_empty_is_unknown(self):
        assert worst_lamp_color({}) == "unknown"


# ============================================================
# _render_funding_card (визуална HTML карта)
# ============================================================

class TestHtmlCard:
    def test_available_renders_composite_and_lamps(self):
        h = _render_funding_card(_view(), TODAY)
        assert "Стабилност на финансирането" in h
        assert "score-circle" in h          # композитният кръг
        assert ">0.0<" in h or "0.0</span>" in h
        assert "Спокойно финансиране" in h
        for label in ("Банково репо", "Fed водопровод", "Цена на парите",
                      "Аукциони", "Ливъридж"):
            assert label in h
        assert "#3fb950" in h               # зелен headline (всички лампи green)

    def test_unavailable_is_honest_not_zero(self):
        h = _render_funding_card(_view(available=False, state=None,
                                       health_note="няма fetch"), TODAY)
        assert "недостъпен" in h
        assert "не 0" in h
        assert "score-circle" not in h      # няма измислен композит

    def test_none_view_honest(self):
        h = _render_funding_card(None, TODAY)
        assert "недостъпен" in h
        assert "score-circle" not in h

    def test_red_headline_color(self):
        st = dict(VALID_PAYLOAD,
                  lamp_status={"1": "red", "2": "green", "3": "green",
                               "4": "green", "5": "green"},
                  composite_score=7.0, verdict="Засилен стрес")
        h = _render_funding_card(_view(state=st), TODAY)
        assert "#f85149" in h               # червен headline
        assert "7.0" in h

    def test_stale_banner_surfaces(self):
        h = _render_funding_card(_view(stale=True, age_days=9), TODAY)
        assert "остарял" in h

    def test_valid_html_structure(self):
        h = _render_funding_card(_view(), TODAY)
        assert h.count("<section") == 1
        assert "</section>" in h
        assert "<table" in h and "</table>" in h
