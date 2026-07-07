"""
tests/test_nowcast_wire.py
===========================
П4 контракт: nowcast редовете (GDPNOW/PCENOW) са ingest-нати като КОНТЕКСТНИ
редове — отделен NOWCAST_CATALOG, нула участие в лещи/composite/anomaly.
Офлайн тест (никаква мрежа) — synthetic snapshot.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from catalog.series import SERIES_CATALOG, NOWCAST_CATALOG  # noqa: E402
from analysis.anomaly import compute_anomalies  # noqa: E402
from export.briefing_context import _render_cross_spreads  # noqa: E402


def _synthetic_nowcast_snapshot() -> dict[str, pd.Series]:
    qidx = pd.date_range("2024-01-01", periods=10, freq="QS")
    return {
        "GDPNOW": pd.Series(np.linspace(1.0, 2.5, 10), index=qidx),
        "PCENOW": pd.Series(np.linspace(1.5, 2.0, 10), index=qidx),
    }


class TestNowcastCatalogSeparation:
    """Кардиналното: nowcast-ите НЕ са граждани на SERIES_CATALOG."""

    def test_registry_exists_with_expected_keys(self):
        assert set(NOWCAST_CATALOG.keys()) == {"GDPNOW", "PCENOW"}

    def test_not_in_series_catalog(self):
        for key in NOWCAST_CATALOG:
            assert key not in SERIES_CATALOG, (
                f"{key} е в SERIES_CATALOG — би влязъл в лещите/composite. "
                "П4 мандатът иска контекстни редове САМО."
            )

    def test_no_lens_membership(self):
        """Без lens/peer_group → структурно невъзможно да влезе в breadth."""
        for key, meta in NOWCAST_CATALOG.items():
            assert "lens" not in meta, f"{key}: nowcast с lens поле"
            assert "peer_group" not in meta, f"{key}: nowcast с peer_group"

    def test_nowcast_label_in_hint(self):
        """Всеки ред е етикетиран „nowcast (външен модел ...)" descriptive."""
        for key, meta in NOWCAST_CATALOG.items():
            hint = meta.get("narrative_hint", "")
            assert "nowcast" in hint.lower(), f"{key}: няма nowcast етикет"
            assert "Atlanta Fed" in hint, f"{key}: не сочи външния модел"

    def test_pcenow_is_labeled_growth_not_inflation(self):
        """PCENOW е REAL PCE РАСТЕЖ — грешното четене като инфлация е
        category error (мандат П4)."""
        hint = NOWCAST_CATALOG["PCENOW"]["narrative_hint"]
        assert "НЕ PCE" in hint and "инфлация" in hint


class TestNowcastStaysOutOfAnalytics:
    def test_anomaly_scan_skips_nowcasts(self):
        """compute_anomalies итерира snapshot, но skip-ва не-каталожни ключове —
        nowcast в snapshot НЕ произвежда anomaly reading."""
        snapshot = _synthetic_nowcast_snapshot()
        report = compute_anomalies(snapshot, z_threshold=0.0)
        keys = {a.series_key for a in report.top}
        assert not keys & set(NOWCAST_CATALOG), (
            f"Nowcast ключове в anomaly report: {keys & set(NOWCAST_CATALOG)}"
        )


class TestNowcastContextRendering:
    def test_renders_with_labels(self):
        snapshot = _synthetic_nowcast_snapshot()
        md = _render_cross_spreads(snapshot, date(2026, 7, 7), history_years=10)
        assert "### Nowcasts (външни модели)" in md
        assert "GDPNow" in md and "Atlanta Fed" in md
        assert "PCENow" in md
        assert "НЕ PCE инфлация" in md
        # Липсите се докладват (PCE inflation nowcast / supercore)
        assert "PCE инфлационен nowcast" in md
        assert "PCE Supercore" in md

    def test_renders_honest_absence_without_data(self):
        md = _render_cross_spreads({}, date(2026, 7, 7), history_years=10)
        assert "### Nowcasts (външни модели)" in md
        assert "GDPNOW/PCENOW липсват" in md
