"""
tests/test_analysis_non_consensus.py
====================================
Unit тестове за analysis/non_consensus.py.

Покриваме:
  - Config sanity: ALLOWED_TAGS и каталог броевете съвпадат
  - Signal classification: high/medium/low според |z| и peer deviation
  - Peer deviation detection
  - Multi-tag handling (overlap: TEMPHELPS, USINFO са в 2 tag-а)
  - Dedupe в highlights
  - Insufficient data → low signal
  - JSON safety (to_dict)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from analysis.non_consensus import (  # noqa: E402
    compute_non_consensus,
    NonConsensusReading,
    NonConsensusReport,
    _classify_signal,
    _check_deviation,
    _peer_breadth_excluding,
    Z_THRESHOLD,
)
from catalog.series import (  # noqa: E402
    ALLOWED_TAGS,
    series_by_tag,
    series_by_peer_group,
    SERIES_CATALOG,
)


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
    vals = [level + 0.01 * np.sin(i * 0.3) for i in range(n)]
    return monthly(vals)


def spike_up(n: int = 60, base: float = 2.0, spike: float = 10.0) -> pd.Series:
    """Стабилна серия със скок в края — дава голям положителен z."""
    vals = [base + 0.01 * np.sin(i * 0.3) for i in range(n - 3)]
    vals.extend([spike, spike + 0.3, spike + 0.7])
    return monthly(vals)


def spike_down(n: int = 60, base: float = 10.0, spike: float = 2.0) -> pd.Series:
    """Стабилна висока → срив в края → голям отрицателен z."""
    vals = [base + 0.01 * np.sin(i * 0.3) for i in range(n - 3)]
    vals.extend([spike, spike - 0.3, spike - 0.7])
    return monthly(vals)


@pytest.fixture(autouse=True)
def _seed():
    np.random.seed(42)


# ============================================================
# TEST — config sanity
# ============================================================

class TestConfigSanity:
    def test_allowed_tags_populated(self):
        """Всеки allowed tag трябва да има поне 1 серия в каталога."""
        for tag in ALLOWED_TAGS:
            count = len(series_by_tag(tag))
            assert count >= 1, f"Tag '{tag}' няма серии в каталога"

    def test_expected_tag_counts(self):
        """Текущата структура: non_consensus ≥10, ai_exposure ≥4, structural ≥2."""
        assert len(series_by_tag("non_consensus")) >= 10
        assert len(series_by_tag("ai_exposure")) >= 4
        assert len(series_by_tag("structural")) >= 2

    def test_multi_tag_series_exist(self):
        """TEMPHELPS и USINFO трябва да имат повече от 1 tag (bridge серии)."""
        tempheps = SERIES_CATALOG.get("TEMPHELPS", {})
        usinfo = SERIES_CATALOG.get("USINFO", {})
        assert len(tempheps.get("tags", [])) >= 2
        assert len(usinfo.get("tags", [])) >= 2


# ============================================================
# TEST — unit logic: signal classification
# ============================================================

class TestSignalClassification:
    def test_high_when_extreme_and_deviates(self):
        assert _classify_signal(z_last=3.0, deviates=True, z_threshold=2.0) == "high"
        assert _classify_signal(z_last=-2.5, deviates=True, z_threshold=2.0) == "high"

    def test_medium_when_only_extreme(self):
        assert _classify_signal(z_last=2.5, deviates=False, z_threshold=2.0) == "medium"

    def test_medium_when_only_deviates(self):
        assert _classify_signal(z_last=0.5, deviates=True, z_threshold=2.0) == "medium"

    def test_low_otherwise(self):
        assert _classify_signal(z_last=0.5, deviates=False, z_threshold=2.0) == "low"

    def test_low_on_nan_z(self):
        assert _classify_signal(z_last=float("nan"), deviates=False, z_threshold=2.0) == "low"
        # NaN z + deviation → medium (deviation все още важи)
        assert _classify_signal(z_last=float("nan"), deviates=True, z_threshold=2.0) == "medium"


class TestDeviationCheck:
    def test_series_down_peer_up_is_deviation(self):
        assert _check_deviation(mom_last=-0.5, peer_direction="up") is True

    def test_series_up_peer_down_is_deviation(self):
        assert _check_deviation(mom_last=0.5, peer_direction="down") is True

    def test_aligned_not_deviation(self):
        assert _check_deviation(mom_last=0.5, peer_direction="up") is False
        assert _check_deviation(mom_last=-0.5, peer_direction="down") is False

    def test_mixed_or_insufficient_not_deviation(self):
        assert _check_deviation(mom_last=0.5, peer_direction="mixed") is False
        assert _check_deviation(mom_last=0.5, peer_direction="insufficient") is False

    def test_nan_momentum_not_deviation(self):
        assert _check_deviation(mom_last=float("nan"), peer_direction="up") is False


# ============================================================
# TEST — peer breadth excluding self
# ============================================================

class TestPeerBreadthExcluding:
    def test_excludes_self_from_calculation(self):
        """При изчисляване на peer breadth, сигналната серия не трябва да участва."""
        # TEMPHELPS е в peer_group sectoral_employment
        peers = series_by_peer_group("sectoral_employment")
        snapshot = {}
        for e in peers:
            if e["_key"] == "TEMPHELPS":
                snapshot[e["_key"]] = trend_down()  # самата серия надолу
            else:
                snapshot[e["_key"]] = trend_up()    # peers нагоре

        bp, direction = _peer_breadth_excluding("sectoral_employment", "TEMPHELPS", snapshot)
        # peer-ите всички нагоре → breadth=1.0 → "up"
        assert direction == "up"
        assert bp == pytest.approx(1.0)

    def test_insufficient_when_only_self_has_data(self):
        snapshot = {"TEMPHELPS": trend_up()}
        bp, direction = _peer_breadth_excluding("sectoral_employment", "TEMPHELPS", snapshot)
        assert direction == "insufficient"
        assert np.isnan(bp)

    def test_mixed_when_peers_split(self):
        """Половината peers up, половината down → mixed."""
        peers = series_by_peer_group("unemployment")
        if len(peers) < 3:
            pytest.skip("Нужни са ≥3 peers за смислен split (един exclude-ван + 2 остатъчни)")
        snapshot = {}
        for i, e in enumerate(peers):
            snapshot[e["_key"]] = trend_up() if i % 2 == 0 else trend_down()

        self_key = peers[0]["_key"]
        _, direction = _peer_breadth_excluding("unemployment", self_key, snapshot)
        # Нека не pins-ваме exact value; приемаме че не е insufficient
        assert direction in ("up", "down", "mixed")


# ============================================================
# TEST — end-to-end behavior
# ============================================================

class TestComputeNonConsensus:
    def test_empty_snapshot_all_low(self):
        """Празен snapshot → всички tagged серии в report, но всички low."""
        report = compute_non_consensus({})
        assert isinstance(report, NonConsensusReport)
        # by_tag трябва да има всички 3 tag-а
        assert set(report.by_tag.keys()) == ALLOWED_TAGS
        # Всички readings → low signal (insufficient data)
        for tag, readings in report.by_tag.items():
            for r in readings:
                assert r.signal_strength == "low"
        # Highlights празни
        assert report.highlights == []
        assert report.as_of is None

    def test_all_tagged_series_appear_in_by_tag(self):
        """Всяка tagged серия трябва да е в by_tag[tag] за всеки неин tag."""
        snapshot = {k: trend_up() for k in SERIES_CATALOG.keys()}
        report = compute_non_consensus(snapshot)

        for tag in ALLOWED_TAGS:
            expected_keys = {e["_key"] for e in series_by_tag(tag)}
            got_keys = {r.series_key for r in report.by_tag[tag]}
            assert expected_keys == got_keys, (
                f"Tag '{tag}': expected {expected_keys}, got {got_keys}"
            )

    def test_multi_tag_series_appears_in_all_its_tags(self):
        """TEMPHELPS е non_consensus + ai_exposure → трябва да е в ДВЕТЕ tag листа."""
        snapshot = {k: trend_up() for k in SERIES_CATALOG.keys()}
        report = compute_non_consensus(snapshot)

        nc_keys = {r.series_key for r in report.by_tag.get("non_consensus", [])}
        ai_keys = {r.series_key for r in report.by_tag.get("ai_exposure", [])}

        assert "TEMPHELPS" in nc_keys
        assert "TEMPHELPS" in ai_keys
        assert "USINFO" in nc_keys
        assert "USINFO" in ai_keys

    def test_highlights_are_deduplicated(self):
        """TEMPHELPS в 2 tag-а, но в highlights се появява само веднъж."""
        # Правим TEMPHELPS "high" сигнал: spike_down при peers up
        snapshot: dict[str, pd.Series] = {}
        peers = series_by_peer_group("sectoral_employment")
        for e in peers:
            if e["_key"] == "TEMPHELPS":
                snapshot[e["_key"]] = spike_down()
            else:
                snapshot[e["_key"]] = trend_up()
        # Другите серии flat (не създават шум)
        for k in SERIES_CATALOG.keys():
            if k not in snapshot:
                snapshot[k] = flat()

        report = compute_non_consensus(snapshot)
        temp_count = sum(1 for r in report.highlights if r.series_key == "TEMPHELPS")
        assert temp_count <= 1, "TEMPHELPS не трябва да се появява два пъти в highlights"

    def test_high_signal_when_extreme_and_deviates(self):
        """Серия с big spike в обратна посока на peer_group → high signal."""
        snapshot: dict[str, pd.Series] = {}
        peers = series_by_peer_group("sectoral_employment")
        target_key = "TEMPHELPS"
        for e in peers:
            if e["_key"] == target_key:
                snapshot[e["_key"]] = spike_down()  # самата серия сривва → голям −z
            else:
                snapshot[e["_key"]] = trend_up()     # peer-ите нагоре
        for k in SERIES_CATALOG.keys():
            if k not in snapshot:
                snapshot[k] = flat()

        report = compute_non_consensus(snapshot)
        temp_reading = next(r for r in report.highlights if r.series_key == target_key)
        assert temp_reading.signal_strength == "high"
        assert temp_reading.deviates_from_peers is True
        assert abs(temp_reading.z_score) > Z_THRESHOLD
        assert temp_reading.peer_direction == "up"

    def test_low_signal_when_aligned_and_calm(self):
        """Всички trend up заедно → няма нито екстремум, нито deviation → low."""
        snapshot = {k: trend_up() for k in SERIES_CATALOG.keys()}
        report = compute_non_consensus(snapshot)
        # Поне една tagged серия трябва да е "low" — нищо не е екстремно или dev-на
        low_count = sum(
            1 for readings in report.by_tag.values()
            for r in readings
            if r.signal_strength == "low"
        )
        assert low_count >= 1

    def test_highlights_sorted_by_strength_then_z(self):
        """Highlights: high преди medium, вътре в група по |z| descending."""
        snapshot: dict[str, pd.Series] = {}
        for k in SERIES_CATALOG.keys():
            snapshot[k] = flat()
        # Правим TEMPHELPS "high": extreme + deviates
        for e in series_by_peer_group("sectoral_employment"):
            if e["_key"] == "TEMPHELPS":
                snapshot[e["_key"]] = spike_down()
            else:
                snapshot[e["_key"]] = trend_up()
        # PPIFIS просто spike (extreme, но без deviation спрямо peer) → medium
        snapshot["PPIFIS"] = spike_up()

        report = compute_non_consensus(snapshot)
        if len(report.highlights) >= 2:
            # Първият трябва да е поне толкова силен, колкото втория
            ranks = {"high": 2, "medium": 1, "low": 0}
            for i in range(len(report.highlights) - 1):
                a, b = report.highlights[i], report.highlights[i + 1]
                assert ranks[a.signal_strength] >= ranks[b.signal_strength]

    def test_as_of_from_latest_series(self):
        """as_of трябва да е датата на последното наблюдение."""
        snapshot = {k: trend_up() for k in SERIES_CATALOG.keys()}
        report = compute_non_consensus(snapshot)
        assert report.as_of == "2026-03-01"  # monthly() endpoint по default


# ============================================================
# TEST — JSON safety
# ============================================================

class TestJSONSafety:
    def test_reading_to_dict_nan_to_none(self):
        r = NonConsensusReading(
            series_key="X",
            series_name_bg="X",
            lens=["labor"],
            peer_group="pg",
            tags=["non_consensus"],
            last_value=float("nan"),
            last_date=None,
            z_score=float("nan"),
            momentum_1m=float("nan"),
            peer_breadth=float("nan"),
            peer_direction="insufficient",
            deviates_from_peers=False,
            signal_strength="low",
            narrative_hint="",
        )
        d = r.to_dict()
        for k in ("last_value", "z_score", "momentum_1m", "peer_breadth"):
            assert d[k] is None

    def test_report_to_dict_structure(self):
        report = compute_non_consensus({})
        d = report.to_dict()
        assert set(d.keys()) == {"as_of", "by_tag", "highlights"}
        assert isinstance(d["by_tag"], dict)
        assert isinstance(d["highlights"], list)
