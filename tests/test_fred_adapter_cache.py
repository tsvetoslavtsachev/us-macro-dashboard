"""
tests/test_fred_adapter_cache.py
=================================
Тестове за cache-layer на FredAdapter:

  - get_snapshot() — публичен helper за briefing/explorer path-а
  - _tolerant_parse_cache() — fallback при повреден cache tail
  - _load_cache() — използва tolerant fallback при JSONDecodeError

Не правим реални мрежови заявки.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from sources.fred_adapter import FredAdapter, _tolerant_parse_cache  # noqa: E402


# ============================================================
# HELPERS
# ============================================================

def _write_cache(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "data" / "fred_cache.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _valid_entry(dates_values: dict[str, float], fred_id: str = "TEST") -> dict:
    return {
        "fred_id": fred_id,
        "last_fetched": "2026-04-18T10:00:00",
        "last_observation": max(dates_values.keys()) if dates_values else None,
        "n_observations": len(dates_values),
        "data": dates_values,
    }


# ============================================================
# get_snapshot
# ============================================================

class TestGetSnapshot:

    def test_returns_cached_series_as_dict(self, tmp_path):
        _write_cache(tmp_path, json.dumps({
            "UNRATE": _valid_entry({"2026-01-01": 4.0, "2026-02-01": 4.1}),
            "CPIAUCSL": _valid_entry({"2026-01-01": 310.0, "2026-02-01": 311.5}),
        }))
        adapter = FredAdapter(api_key="x", base_dir=tmp_path)
        snap = adapter.get_snapshot(["UNRATE", "CPIAUCSL"])
        assert set(snap.keys()) == {"UNRATE", "CPIAUCSL"}
        assert snap["UNRATE"].iloc[-1] == 4.1
        assert snap["CPIAUCSL"].iloc[-1] == 311.5

    def test_skips_keys_not_in_cache(self, tmp_path):
        _write_cache(tmp_path, json.dumps({
            "UNRATE": _valid_entry({"2026-01-01": 4.0}),
        }))
        adapter = FredAdapter(api_key="x", base_dir=tmp_path)
        snap = adapter.get_snapshot(["UNRATE", "NONEXISTENT", "ALSO_MISSING"])
        assert set(snap.keys()) == {"UNRATE"}

    def test_skips_empty_series(self, tmp_path):
        _write_cache(tmp_path, json.dumps({
            "UNRATE": _valid_entry({"2026-01-01": 4.0}),
            "EMPTY": _valid_entry({}),  # празни данни
        }))
        adapter = FredAdapter(api_key="x", base_dir=tmp_path)
        snap = adapter.get_snapshot(["UNRATE", "EMPTY"])
        assert set(snap.keys()) == {"UNRATE"}

    def test_empty_cache_returns_empty_dict(self, tmp_path):
        _write_cache(tmp_path, "{}")
        adapter = FredAdapter(api_key="x", base_dir=tmp_path)
        assert adapter.get_snapshot(["UNRATE"]) == {}

    def test_returned_series_is_sorted_by_date(self, tmp_path):
        _write_cache(tmp_path, json.dumps({
            "UNRATE": _valid_entry({
                "2026-02-01": 4.1,
                "2026-01-01": 4.0,
                "2026-03-01": 4.2,
            }),
        }))
        adapter = FredAdapter(api_key="x", base_dir=tmp_path)
        snap = adapter.get_snapshot(["UNRATE"])
        values = list(snap["UNRATE"].values)
        assert values == [4.0, 4.1, 4.2]

    def test_accepts_any_iterable(self, tmp_path):
        _write_cache(tmp_path, json.dumps({
            "A": _valid_entry({"2026-01-01": 1.0}),
            "B": _valid_entry({"2026-01-01": 2.0}),
        }))
        adapter = FredAdapter(api_key="x", base_dir=tmp_path)
        # tuple
        assert set(adapter.get_snapshot(("A", "B")).keys()) == {"A", "B"}
        # generator
        assert set(adapter.get_snapshot(k for k in ["A", "B"]).keys()) == {"A", "B"}


# ============================================================
# _tolerant_parse_cache
# ============================================================

class TestTolerantParse:

    def test_valid_json_parses_same_as_strict(self):
        raw = json.dumps({
            "A": {"fred_id": "A", "data": {"2026-01-01": 1.0}},
            "B": {"fred_id": "B", "data": {"2026-01-01": 2.0}},
        })
        out = _tolerant_parse_cache(raw)
        assert set(out.keys()) == {"A", "B"}

    def test_truncated_tail_returns_valid_prefix(self):
        # Валидни A и B, после почваме C но режем по средата на data
        raw = (
            '{\n'
            '  "A": {"fred_id": "A", "data": {"2026-01-01": 1.0}},\n'
            '  "B": {"fred_id": "B", "data": {"2026-01-01": 2.0}},\n'
            '  "C": {"fred_id": "C", "data": {\n'
            '    "2026-01-01": 3.0,\n'   # липсва затваряща скоба надолу
        )
        out = _tolerant_parse_cache(raw)
        assert set(out.keys()) == {"A", "B"}
        assert out["A"]["fred_id"] == "A"
        assert out["B"]["fred_id"] == "B"

    def test_malformed_start_returns_empty(self):
        assert _tolerant_parse_cache("not a json at all") == {}
        assert _tolerant_parse_cache("") == {}
        assert _tolerant_parse_cache("[1, 2, 3]") == {}  # array не обект

    def test_empty_object(self):
        assert _tolerant_parse_cache("{}") == {}
        assert _tolerant_parse_cache("   {}  ") == {}

    def test_trailing_comma_is_tolerated(self):
        raw = (
            '{\n'
            '  "A": {"fred_id": "A", "data": {"2026-01-01": 1.0}},\n'
            '}'
        )
        out = _tolerant_parse_cache(raw)
        assert set(out.keys()) == {"A"}

    def test_non_object_value_is_skipped(self):
        # Ако value не е dict, не го добавяме (пазим invariant)
        raw = (
            '{\n'
            '  "A": {"fred_id": "A", "data": {"2026-01-01": 1.0}},\n'
            '  "B": "not an object",\n'
            '  "C": {"fred_id": "C", "data": {"2026-01-01": 3.0}}\n'
            '}'
        )
        out = _tolerant_parse_cache(raw)
        # A и C минават; B е string (скипва се)
        assert "A" in out and "C" in out
        assert "B" not in out


# ============================================================
# _load_cache fallback
# ============================================================

class TestLoadCacheFallback:

    def test_corrupt_tail_triggers_tolerant_recovery(self, tmp_path):
        """Ключов сценарий: truncated tail ⇒ strict load fails ⇒ tolerant recovers валидния prefix."""
        raw = (
            '{\n'
            '  "A": {"fred_id": "A", "last_fetched": "2026-04-18T10:00:00", '
            '"last_observation": "2026-01-01", "n_observations": 1, '
            '"data": {"2026-01-01": 1.0}},\n'
            '  "B": {"fred_id": "B", "last_fetched": "2026-04-18T10:00:00", '
            '"last_observation": "2026-01-01", "n_observations": 1, '
            '"data": {"2026-01-01": 2.0}},\n'
            '  "C": {"fred_id": "C", "data": {"2026-01-01": 3.0,\n'  # truncated
        )
        _write_cache(tmp_path, raw)
        adapter = FredAdapter(api_key="x", base_dir=tmp_path)
        # Възстановени: A и B (не и C, което беше truncated)
        snap = adapter.get_snapshot(["A", "B", "C"])
        assert set(snap.keys()) == {"A", "B"}

    def test_completely_malformed_falls_back_to_empty(self, tmp_path):
        _write_cache(tmp_path, "this is not json at all")
        adapter = FredAdapter(api_key="x", base_dir=tmp_path)
        assert adapter.get_snapshot(["A"]) == {}

    def test_valid_json_does_not_trigger_tolerant_path(self, tmp_path):
        _write_cache(tmp_path, json.dumps({
            "A": _valid_entry({"2026-01-01": 1.0}),
        }))
        adapter = FredAdapter(api_key="x", base_dir=tmp_path)
        assert "A" in adapter.get_snapshot(["A"])

    def test_missing_file_returns_empty(self, tmp_path):
        # Без cache файл изобщо
        adapter = FredAdapter(api_key="x", base_dir=tmp_path)
        assert adapter.get_snapshot(["A"]) == {}
