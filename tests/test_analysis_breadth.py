"""
tests/test_analysis_breadth.py
==============================
Unit тестове за analysis/breadth.py.

Тестваме:
  1. Sanity: lens от ALLOWED_LENSES връща отчет с очакваните peer_groups
  2. All-positive breadth (всички expanding)
  3. All-negative breadth (всички contracting)
  4. Split breadth (mixed)
  5. Extreme members detection (z > 2)
  6. Missing series в snapshot — marked като missing_members
  7. peer_group с < 2 налични серии → direction="insufficient_data"
  8. Празен snapshot → всички peer_groups insufficient_data, as_of=None
  9. Validation на невалиден lens → ValueError
 10. as_of е max(last_date) — не min — защото сериите имат различни schedule-и
 11. to_dict() конвертира NaN → None (JSON-safe)

Философия: тестовете симулират реалистични lens setup-и, но с малък брой
синтетични серии (NOT hitting FRED).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from analysis.breadth import (  # noqa: E402
    compute_lens_breadth,
    PeerGroupBreadth,
    LensBreadthReport,
    BREADTH_EXPANDING_THRESHOLD,
    BREADTH_CONTRACTING_THRESHOLD,
)
from catalog.series import series_by_lens  # noqa: E402


# ============================================================
# HELPERS
# ============================================================

def monthly(values: list[float], end: str = "2026-03-01") -> pd.Series:
    idx = pd.date_range(end=end, periods=len(values), freq="MS")
    return pd.Series(values, index=idx)


def trend_up(n: int = 60) -> pd.Series:
    return monthly(list(np.linspace(2.0, 5.0, n)))


def trend_down(n: int = 60) -> pd.Series:
    return monthly(list(np.linspace(5.0, 2.0, n)))


def flat(n: int = 60, level: float = 3.0) -> pd.Series:
    # Малка сину-вълна → std > 0, но z_last близо до 0
    vals = [level + 0.01 * np.sin(i * 0.3) for i in range(n)]
    return monthly(vals)


def stable_then_spike(n: int = 60, stable: float = 2.0, spike: float = 10.0) -> pd.Series:
    vals = [stable + 0.01 * np.sin(i * 0.3) for i in range(n - 3)]
    vals.extend([spike, spike + 0.3, spike + 0.7])
    return monthly(vals)


def _build_snapshot_for_lens(lens: str, factory) -> dict[str, pd.Series]:
    """Фабрика: за всеки catalog ключ в даден lens, създава серия чрез `factory()`."""
    entries = series_by_lens(lens)
    return {entry["_key"]: factory() for entry in entries}


@pytest.fixture(autouse=True)
def _seed():
    np.random.seed(42)


# ============================================================
# TEST 1 — Sanity
# ============================================================

class TestSanity:
    def test_labor_lens_returns_expected_peer_groups(self):
        snapshot = _build_snapshot_for_lens("labor", trend_up)
        report = compute_lens_breadth("labor", snapshot)

        assert isinstance(report, LensBreadthReport)
        assert report.lens == "labor"
        assert len(report.peer_groups) >= 4  # най-малко claims/unemployment/hours/wage_dynamics

        names = {pg.name for pg in report.peer_groups}
        # Labor лещата след Phase 2.5:
        for expected in ("claims", "unemployment", "hours", "wage_dynamics"):
            assert expected in names, f"Очаквахме peer_group '{expected}' в labor"

    def test_all_four_main_lenses_work(self):
        for lens in ("labor", "growth", "inflation", "liquidity"):
            snapshot = _build_snapshot_for_lens(lens, trend_up)
            report = compute_lens_breadth(lens, snapshot)
            assert report.lens == lens
            assert len(report.peer_groups) >= 1


# ============================================================
# TEST 2-4 — Breadth в различни посоки
# ============================================================

class TestBreadthDirections:
    def test_all_expanding(self):
        snapshot = _build_snapshot_for_lens("labor", trend_up)
        report = compute_lens_breadth("labor", snapshot)

        for pg in report.peer_groups:
            if pg.direction == "insufficient_data":
                continue
            assert pg.breadth_positive == pytest.approx(1.0), (
                f"{pg.name}: очаквахме breadth=1.0 при all trending up, получихме {pg.breadth_positive}"
            )
            assert pg.direction == "expanding"

    def test_all_contracting(self):
        snapshot = _build_snapshot_for_lens("labor", trend_down)
        report = compute_lens_breadth("labor", snapshot)

        for pg in report.peer_groups:
            if pg.direction == "insufficient_data":
                continue
            assert pg.breadth_positive == pytest.approx(0.0)
            assert pg.direction == "contracting"

    def test_split_breadth_mixed(self):
        """Половината up, половината down → breadth ≈ 0.5 → mixed."""
        entries = series_by_lens("inflation")
        snapshot: dict[str, pd.Series] = {}
        # групираме по peer_group и редуваме up/down вътре в групата
        from collections import defaultdict
        by_pg = defaultdict(list)
        for entry in entries:
            by_pg[entry["peer_group"]].append(entry["_key"])

        for keys in by_pg.values():
            for i, k in enumerate(keys):
                snapshot[k] = trend_up() if i % 2 == 0 else trend_down()

        report = compute_lens_breadth("inflation", snapshot)
        # Само 2-членовите peer_groups (wage_dynamics, labor_share) могат да дадат
        # точно breadth=0.5 при split. 3-членовите дават 0.33 или 0.67 → contracting/expanding.
        # Затова очакваме поне 2 mixed (от 2-членовите groups).
        mixed_count = sum(1 for pg in report.peer_groups if pg.direction == "mixed")
        assert mixed_count >= 2, (
            f"Очаквахме поне 2 mixed peer_groups (2-членовите) при split snapshot, "
            f"получихме {mixed_count}"
        )
        # 3-членовите groups пък трябва да са или expanding, или contracting (не mixed)
        non_mixed_three_member = [
            pg for pg in report.peer_groups
            if pg.n_members == 3 and pg.n_available == 3
            and pg.direction in ("expanding", "contracting")
        ]
        assert len(non_mixed_three_member) >= 3, (
            "3-членовите peer_groups трябва да са classified като expanding/contracting"
        )


# ============================================================
# TEST 5 — Extreme members detection
# ============================================================

class TestExtremeMembers:
    def test_extreme_members_flagged(self):
        """При spike-нала серия → тя е в extreme_members, breadth_extreme > 0."""
        entries = series_by_lens("inflation")
        # Първата серия от inflation lens-а spike-ва, останалите стабилни
        snapshot: dict[str, pd.Series] = {}
        first_key = None
        for i, entry in enumerate(entries):
            k = entry["_key"]
            if i == 0:
                first_key = k
                snapshot[k] = stable_then_spike()
            else:
                snapshot[k] = flat()

        report = compute_lens_breadth("inflation", snapshot)

        # Поне един peer_group трябва да има extreme_members
        flagged = any(pg.extreme_members for pg in report.peer_groups)
        assert flagged, "Очаквахме поне една extreme серия след stable_then_spike"

        # Първата серия трябва да е в extreme_members на своя peer_group
        first_peer_group = entries[0]["peer_group"]
        target_pg = next((pg for pg in report.peer_groups if pg.name == first_peer_group), None)
        assert target_pg is not None
        assert first_key in target_pg.extreme_members

    def test_no_extreme_when_all_flat(self):
        snapshot = _build_snapshot_for_lens("labor", flat)
        report = compute_lens_breadth("labor", snapshot)

        for pg in report.peer_groups:
            assert pg.extreme_members == [], (
                f"{pg.name}: не очаквахме extremes при flat snapshot, получихме {pg.extreme_members}"
            )
            if pg.direction != "insufficient_data":
                assert pg.breadth_extreme == pytest.approx(0.0)


# ============================================================
# TEST 6-7 — Missing / insufficient data
# ============================================================

class TestMissingData:
    def test_missing_series_listed_as_missing(self):
        """Ако snapshot е непълен, missing series са в missing_members."""
        entries = series_by_lens("labor")
        # Skip-ваме първата серия нарочно
        snapshot: dict[str, pd.Series] = {
            entry["_key"]: trend_up() for entry in entries[1:]
        }
        skipped_key = entries[0]["_key"]
        skipped_pg = entries[0]["peer_group"]

        report = compute_lens_breadth("labor", snapshot)
        target = next((pg for pg in report.peer_groups if pg.name == skipped_pg), None)
        assert target is not None
        assert skipped_key in target.missing_members

    def test_insufficient_data_when_only_one_series_available(self):
        """peer_group с 1 налична серия → direction='insufficient_data', breadth=NaN."""
        # Намираме peer_group с точно 3 членове (напр. expectations)
        entries = series_by_lens("inflation")
        from collections import defaultdict
        by_pg = defaultdict(list)
        for entry in entries:
            by_pg[entry["peer_group"]].append(entry["_key"])

        # Избираме "expectations" — знаем, че има 3 членове
        target_pg = "expectations"
        target_keys = by_pg.get(target_pg, [])
        assert len(target_keys) >= 2, "Тестът разчита че 'expectations' има ≥2 членове"

        # Даваме данни само за първия
        snapshot = {target_keys[0]: trend_up()}
        # Всички останали peer_groups ще имат insufficient_data също
        report = compute_lens_breadth("inflation", snapshot)
        target = next((pg for pg in report.peer_groups if pg.name == target_pg), None)
        assert target is not None
        assert target.direction == "insufficient_data"
        assert np.isnan(target.breadth_positive)
        assert np.isnan(target.breadth_extreme)
        assert target.n_available == 1

    def test_empty_snapshot_all_insufficient(self):
        report = compute_lens_breadth("labor", snapshot={})
        for pg in report.peer_groups:
            assert pg.direction == "insufficient_data"
            assert pg.n_available == 0
        assert report.as_of is None


# ============================================================
# TEST 8 — Validation
# ============================================================

class TestValidation:
    def test_invalid_lens_raises(self):
        with pytest.raises(ValueError, match="Unknown lens"):
            compute_lens_breadth("not_a_lens", snapshot={})


# ============================================================
# TEST 9 — as_of logic
# ============================================================

class TestAsOf:
    def test_as_of_is_max_last_date(self):
        """Различни схедули → as_of е max(last_date), не min."""
        entries = series_by_lens("labor")
        early = pd.date_range("2020-01-01", periods=24, freq="MS")
        late = pd.date_range("2020-01-01", periods=60, freq="MS")

        snapshot: dict[str, pd.Series] = {}
        for i, entry in enumerate(entries):
            k = entry["_key"]
            idx = early if i % 2 == 0 else late
            snapshot[k] = pd.Series(np.linspace(1, 5, len(idx)), index=idx)

        report = compute_lens_breadth("labor", snapshot)
        # Late завършва по-късно → as_of трябва да е от late
        assert report.as_of == late[-1].strftime("%Y-%m-%d")


# ============================================================
# TEST 10 — JSON safety
# ============================================================

class TestJSONSafety:
    def test_to_dict_converts_nan_to_none(self):
        """NaN в breadth → None в dict, за да не счупи json.dumps."""
        pg = PeerGroupBreadth(
            name="test",
            n_members=3,
            n_available=0,
            breadth_positive=float("nan"),
            breadth_extreme=float("nan"),
            direction="insufficient_data",
        )
        d = pg.to_dict()
        assert d["breadth_positive"] is None
        assert d["breadth_extreme"] is None

    def test_report_to_dict_structure(self):
        snapshot = _build_snapshot_for_lens("labor", trend_up)
        report = compute_lens_breadth("labor", snapshot)
        d = report.to_dict()
        assert set(d.keys()) == {"lens", "as_of", "peer_groups"}
        assert isinstance(d["peer_groups"], list)
        for pg_d in d["peer_groups"]:
            assert set(pg_d.keys()) >= {
                "name", "n_members", "n_available", "breadth_positive",
                "breadth_extreme", "direction", "extreme_members", "missing_members",
            }
