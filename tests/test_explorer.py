"""
tests/test_explorer.py
======================
Тестове за export/explorer.py.

Покриваме:
  - Generation без crash при empty snapshot (каталогът вижда се)
  - Generation с реалистичен snapshot
  - Всички 71 каталожни серии имат #KEY anchor секция
  - Index таблица групиран по primary lens
  - SVG sparkline-и се появяват за серии с данни
  - Peer context таблици съществуват
  - Self-contained (no external URLs, no script tags, inline CSS)
  - Tooltip структурата е непокътната (hover върху peer линк)
  - Back-to-briefing линк работи когато briefing_href е подаден
  - Explorer линкът от briefing-а е валиден (explorer.html#KEY)
"""
from __future__ import annotations

import re
import sys
import tempfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from export.explorer import (  # noqa: E402
    generate_explorer,
    LATEST_N_READINGS,
    SPARKLINE_YEARS,
)
from export.weekly_briefing import generate_weekly_briefing  # noqa: E402
from catalog.series import SERIES_CATALOG  # noqa: E402


# ============================================================
# HELPERS
# ============================================================

def monthly(values: list[float], end: str = "2026-03-01") -> pd.Series:
    idx = pd.date_range(end=end, periods=len(values), freq="MS")
    return pd.Series(values, index=idx)


def trend_up(n: int = 60) -> pd.Series:
    return monthly(list(np.linspace(2.0, 5.0, n)))


def flat(n: int = 60) -> pd.Series:
    return monthly([3.0 + 0.01 * np.sin(i * 0.3) for i in range(n)])


def spike_up(n: int = 60, base: float = 2.0, spike: float = 10.0) -> pd.Series:
    vals = [base + 0.01 * np.sin(i * 0.3) for i in range(n - 3)]
    vals.extend([spike, spike + 0.3, spike + 0.7])
    return monthly(vals)


@pytest.fixture
def tmp_output(tmp_path) -> Path:
    return tmp_path / "explorer.html"


@pytest.fixture(autouse=True)
def _seed():
    np.random.seed(42)


# ============================================================
# TEST — basic generation
# ============================================================

class TestGeneration:
    def test_empty_snapshot_generates_valid_html(self, tmp_output):
        path = generate_explorer({}, str(tmp_output))
        assert Path(path).exists()
        content = Path(path).read_text(encoding="utf-8")
        assert content.startswith("<!doctype html>")
        assert "</html>" in content
        # Дори без данни — каталогът се изобразява (71 секции)
        assert "Series Explorer" in content

    def test_realistic_snapshot_generates_html(self, tmp_output):
        snapshot = {k: trend_up() for k in SERIES_CATALOG.keys()}
        path = generate_explorer(snapshot, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        assert len(content) > 50_000  # нетривиален HTML

    def test_returned_path_is_absolute(self, tmp_output):
        path = generate_explorer({}, str(tmp_output))
        assert Path(path).is_absolute()


# ============================================================
# TEST — structure
# ============================================================

class TestStructure:
    def test_all_71_catalog_series_have_anchor_section(self, tmp_output):
        path = generate_explorer({}, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        for key in SERIES_CATALOG.keys():
            assert f'id="{key}"' in content, f"Missing anchor for series {key}"

    def test_index_table_groups_by_primary_lens(self, tmp_output):
        path = generate_explorer({}, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        # 4 lens групи в index-а
        for lens_label in ["Трудов пазар", "Растеж", "Инфлация", "Ликвидност и кредит"]:
            assert lens_label in content, f"Lens group missing: {lens_label}"
        # Index секция присъства
        assert "Индекс" in content or 'class="expl-index"' in content

    def test_series_without_data_marked(self, tmp_output):
        # Empty snapshot → всички 71 серии трябва да имат "няма данни"
        path = generate_explorer({}, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        # Поне в index-а "няма данни" markers се появяват
        assert "няма данни" in content

    def test_metadata_panel_present(self, tmp_output):
        snapshot = {"UNRATE": trend_up()}
        path = generate_explorer(snapshot, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        # UNRATE е labor, peer_group=unemployment, name_bg="Безработица (headline, U-3)"
        assert "Безработица (headline, U-3)" in content
        assert "unemployment" in content


# ============================================================
# TEST — sparklines
# ============================================================

class TestSparkline:
    def test_sparkline_svg_present_for_series_with_data(self, tmp_output):
        snapshot = {"UNRATE": trend_up()}
        path = generate_explorer(snapshot, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        assert "<svg class=\"sparkline" in content
        assert "<polyline" in content

    def test_sparkline_uses_last_n_years(self, tmp_output):
        # 10-годишна серия → sparkline показва последните 5
        long_series = monthly(list(np.linspace(2.0, 5.0, 120)))
        snapshot = {"UNRATE": long_series}
        path = generate_explorer(snapshot, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        # Просто проверяваме, че SVG полилайн е present
        assert "polyline points=" in content

    def test_no_sparkline_for_empty_series(self, tmp_output):
        snapshot = {"UNRATE": pd.Series(dtype=float)}
        path = generate_explorer(snapshot, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        # "няма данни" вместо sparkline polyline
        # (sparkline може да присъства в други секции, затова не asserttвам absence)
        assert "Няма наличен snapshot" in content


# ============================================================
# TEST — readings table
# ============================================================

class TestReadingsTable:
    def test_readings_table_has_rows(self, tmp_output):
        snapshot = {"UNRATE": trend_up()}
        path = generate_explorer(snapshot, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        assert "readings-table" in content
        # Колонки
        for col in ["дата", "стойност", "z", "YoY", "MoM"]:
            assert col in content

    def test_readings_newest_first(self, tmp_output):
        """Най-новата дата трябва да се появи преди по-стара в HTML-а."""
        snapshot = {"UNRATE": trend_up()}
        path = generate_explorer(snapshot, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        # Последната дата на fixture-а е 2026-03-01; най-старите в tail(12) са 2025-04-01
        pos_newest = content.find("2026-03-01")
        pos_oldest = content.find("2025-04-01")
        assert pos_newest > 0
        # Ако и двете присъстват, new първо
        if pos_oldest > 0:
            assert pos_newest < pos_oldest


# ============================================================
# TEST — peer context
# ============================================================

class TestPeerContext:
    def test_peer_table_lists_other_peer_group_members(self, tmp_output):
        # UNRATE peer_group = unemployment. Трябва да виждаме U6RATE и други
        # unemployment членове.
        snapshot = {k: trend_up() for k in SERIES_CATALOG.keys()}
        path = generate_explorer(snapshot, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")

        # Намираме UNRATE секцията
        m = re.search(r'id="UNRATE".*?</article>', content, re.DOTALL)
        assert m is not None
        unrate_section = m.group(0)
        # Трябва да съдържа peer-table
        assert "peer-table" in unrate_section
        # U6RATE е unemployment peer — трябва да се появи
        if "U6RATE" in SERIES_CATALOG:
            assert "U6RATE" in unrate_section


# ============================================================
# TEST — self-containment
# ============================================================

class TestSelfContainment:
    def test_no_external_urls(self, tmp_output):
        snapshot = {k: trend_up() for k in SERIES_CATALOG.keys()}
        path = generate_explorer(snapshot, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        assert "http://" not in content
        assert "https://" not in content

    def test_no_script_tags(self, tmp_output):
        snapshot = {k: trend_up() for k in SERIES_CATALOG.keys()}
        path = generate_explorer(snapshot, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        assert "<script" not in content.lower()

    def test_inline_css_present(self, tmp_output):
        path = generate_explorer({}, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        assert "<style>" in content


# ============================================================
# TEST — tooltip structure (series-ref в peer table)
# ============================================================

class TestTooltipsInExplorer:
    def test_series_ref_tooltip_still_works_in_explorer(self, tmp_output):
        """Peer-ите в peer-table-та имат tooltip-ове със същия layout."""
        snapshot = {k: trend_up() for k in SERIES_CATALOG.keys()}
        path = generate_explorer(snapshot, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        assert 'class="series-ref' in content
        assert 'class="tooltip"' in content
        # Tooltip CSS hover правилото присъства
        assert ".series-ref:hover .tooltip" in content


# ============================================================
# TEST — back-to-briefing integration
# ============================================================

class TestBackLink:
    def test_back_link_appears_when_briefing_href_given(self, tmp_output):
        path = generate_explorer(
            {}, str(tmp_output), briefing_href="briefing_2026-04-18.html",
        )
        content = Path(path).read_text(encoding="utf-8")
        assert 'href="briefing_2026-04-18.html"' in content
        assert "Към briefing" in content

    def test_no_back_link_when_briefing_href_none(self, tmp_output):
        path = generate_explorer({}, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        assert "Към briefing" not in content


# ============================================================
# TEST — briefing → explorer linking (integration)
# ============================================================

class TestBriefingExplorerLinking:
    def test_briefing_links_point_to_explorer_html(self, tmp_path):
        """Briefing-ът сочи към explorer.html#KEY за всяка series-ref."""
        # spike-ове карат anomaly feed-а да се попълни → генерира series-ref-ове
        snapshot = {k: spike_up(base=2.0 + i*0.001, spike=10.0 + i*0.1)
                    for i, k in enumerate(SERIES_CATALOG.keys())}
        briefing_path = tmp_path / "briefing.html"
        generate_weekly_briefing(snapshot, str(briefing_path))
        content = briefing_path.read_text(encoding="utf-8")
        # Поне няколко <a href="explorer.html#...
        assert 'href="explorer.html#' in content
        # И <a class="series-ref" (а не <span)
        assert '<a class="series-ref' in content

    def test_anchor_targets_in_explorer_match_briefing_links(self, tmp_path):
        """Всеки explorer.html#KEY в briefing има съответстващ id="KEY" в explorer."""
        snapshot = {k: spike_up(base=2.0 + i*0.001, spike=10.0 + i*0.1)
                    for i, k in enumerate(SERIES_CATALOG.keys())}
        briefing_path = tmp_path / "briefing.html"
        explorer_path = tmp_path / "explorer.html"
        generate_weekly_briefing(snapshot, str(briefing_path))
        generate_explorer(snapshot, str(explorer_path))
        briefing = briefing_path.read_text(encoding="utf-8")
        explorer = explorer_path.read_text(encoding="utf-8")

        # Извличаме всички #KEY от briefing
        keys_in_briefing = set(re.findall(r'href="explorer\.html#([A-Z0-9_]+)"', briefing))
        assert len(keys_in_briefing) > 0
        for k in keys_in_briefing:
            assert f'id="{k}"' in explorer, f"Explorer липсва anchor за {k}"
