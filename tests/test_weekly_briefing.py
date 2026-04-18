"""
tests/test_weekly_briefing.py
=============================
Тестове за export/weekly_briefing.py.

Покриваме:
  - Generation без crash при empty snapshot
  - Generation с реалистичен snapshot
  - Файлът се записва и пътят се връща
  - Self-contained HTML (no external URLs)
  - Всички 4 lens секции присъстват
  - 5 cross-lens pairs listed
  - Български labels в HTML
  - Revision-prone caveats се появяват
  - Anomalies top-n respected
  - HTML валиден (съдържа <html>, <body>, </html>)
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

from export.weekly_briefing import (  # noqa: E402
    generate_weekly_briefing,
    LENS_ORDER,
    LENS_LABEL_BG,
)
from catalog.series import SERIES_CATALOG  # noqa: E402


# ============================================================
# HELPERS
# ============================================================

def monthly(values: list[float], end: str = "2026-03-01") -> pd.Series:
    idx = pd.date_range(end=end, periods=len(values), freq="MS")
    return pd.Series(values, index=idx)


def trend_up(n: int = 60) -> pd.Series:
    return monthly(list(np.linspace(2.0, 5.0, n)))


def spike_up(n: int = 60, base: float = 2.0, spike: float = 10.0) -> pd.Series:
    vals = [base + 0.01 * np.sin(i * 0.3) for i in range(n - 3)]
    vals.extend([spike, spike + 0.3, spike + 0.7])
    return monthly(vals)


def flat(n: int = 60) -> pd.Series:
    return monthly([3.0 + 0.01 * np.sin(i * 0.3) for i in range(n)])


@pytest.fixture
def tmp_output(tmp_path) -> Path:
    return tmp_path / "briefing.html"


@pytest.fixture(autouse=True)
def _seed():
    np.random.seed(42)


# ============================================================
# TEST — basic generation
# ============================================================

class TestGeneration:
    def test_empty_snapshot_generates_valid_html(self, tmp_output):
        path = generate_weekly_briefing({}, str(tmp_output))
        assert Path(path).exists()
        content = Path(path).read_text(encoding="utf-8")
        assert content.startswith("<!doctype html>")
        assert "</html>" in content
        assert "<body>" in content

    def test_realistic_snapshot_generates_html(self, tmp_output):
        snapshot = {k: trend_up() for k in SERIES_CATALOG.keys()}
        path = generate_weekly_briefing(snapshot, str(tmp_output))
        assert Path(path).exists()
        content = Path(path).read_text(encoding="utf-8")
        assert len(content) > 5000  # нетривиален HTML
        assert "<!doctype html>" in content

    def test_returned_path_is_absolute(self, tmp_output):
        path = generate_weekly_briefing({}, str(tmp_output))
        assert Path(path).is_absolute()


# ============================================================
# TEST — structure
# ============================================================

class TestStructure:
    def test_all_four_lens_sections_present(self, tmp_output):
        snapshot = {k: trend_up() for k in SERIES_CATALOG.keys()}
        path = generate_weekly_briefing(snapshot, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        for lens in LENS_ORDER:
            # всяка lens секция има data-lens="..." marker
            assert f'data-lens="{lens}"' in content, f"Missing lens section: {lens}"
            # И български label се появява
            assert LENS_LABEL_BG[lens] in content

    def test_cross_lens_pairs_section_present(self, tmp_output):
        snapshot = {k: trend_up() for k in SERIES_CATALOG.keys()}
        path = generate_weekly_briefing(snapshot, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        assert "Cross-Lens Divergence" in content
        # 5 pair cards (unique id-та от CROSS_LENS_PAIRS)
        pair_cards = content.count("pair-card")
        assert pair_cards >= 5

    def test_non_consensus_section_present(self, tmp_output):
        path = generate_weekly_briefing({}, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        assert "Non-Consensus" in content

    def test_anomalies_section_present(self, tmp_output):
        path = generate_weekly_briefing({}, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        assert "Top Anomalies" in content

    def test_footer_with_methodology_present(self, tmp_output):
        path = generate_weekly_briefing({}, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        assert "Методология" in content
        assert "Caveat" in content


# ============================================================
# TEST — self-containment
# ============================================================

class TestSelfContainment:
    def test_no_external_urls(self, tmp_output):
        """Никакви CDN/http(s) references — briefing трябва да се отваря offline."""
        snapshot = {k: trend_up() for k in SERIES_CATALOG.keys()}
        path = generate_weekly_briefing(snapshot, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        # Allow-list: никакво http:// или https:// не трябва да има
        assert "http://" not in content
        assert "https://" not in content

    def test_no_script_tags(self, tmp_output):
        """Без JS — briefing е чист static."""
        path = generate_weekly_briefing({}, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        assert "<script" not in content.lower()

    def test_inline_css_present(self, tmp_output):
        """CSS е inline в <style>."""
        path = generate_weekly_briefing({}, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        assert "<style>" in content


# ============================================================
# TEST — content correctness
# ============================================================

class TestContentCorrectness:
    def test_anomalies_top_n_respected(self, tmp_output):
        """Всички ~71 серии с spike → top_n=3 ограничава списъка."""
        snapshot = {k: spike_up(base=2.0 + i*0.001, spike=10.0 + i*0.1)
                    for i, k in enumerate(SERIES_CATALOG.keys())}
        path = generate_weekly_briefing(snapshot, str(tmp_output), top_anomalies_n=3)
        content = Path(path).read_text(encoding="utf-8")
        # В anomalies секцията — точно 3 реда
        # (hacky проверка — броим <tr class="sig-..."> или redovete в anom-table)
        m = re.search(r'<table class="anom-table">(.*?)</table>', content, re.DOTALL)
        assert m is not None
        anom_html = m.group(1)
        # <tr> в tbody (без header tr)
        tr_count = anom_html.count("<tr>") - anom_html.count('<tr class')  # rough
        # По-устойчиво: броим data rows чрез <tr>\n  <td class="rank">
        ranks = re.findall(r'<td class="rank">\d+</td>', anom_html)
        assert len(ranks) == 3

    def test_as_of_present_in_header(self, tmp_output):
        """as_of датата се появява в header-а."""
        snapshot = {k: trend_up() for k in SERIES_CATALOG.keys()}
        path = generate_weekly_briefing(
            snapshot, str(tmp_output), today=date(2026, 4, 18)
        )
        content = Path(path).read_text(encoding="utf-8")
        # today се появява като 2026-04-18
        assert "2026-04-18" in content
        # as_of е 2026-03-01 според monthly fixture
        assert "2026-03-01" in content

    def test_revision_caveat_for_revision_prone(self, tmp_output):
        """Ако серия с revision_prone=True излезе в anomalies, caveat-ът се появява."""
        # Намираме revision_prone серия
        rev_keys = [k for k, v in SERIES_CATALOG.items() if v.get("revision_prone")]
        if not rev_keys:
            pytest.skip("Няма revision_prone серия в каталога")
        target = rev_keys[0]
        snapshot = {target: spike_up()}
        # Добавяме flat за останалите peer-и, за да не крашва breadth
        for k in SERIES_CATALOG.keys():
            if k != target:
                snapshot[k] = flat()
        path = generate_weekly_briefing(snapshot, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        # revision-mark class (или sup символ) трябва да присъства някъде
        assert "revision-mark" in content or "†" in content

    def test_bulgarian_labels_present(self, tmp_output):
        """Български език в UI labels."""
        path = generate_weekly_briefing({}, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        assert "Седмичен Briefing" in content
        assert "серии" in content
        assert "аномалии" in content


# ============================================================
# TEST — hover tooltips (pure-CSS, on series codes)
# ============================================================

class TestTooltips:
    def test_series_ref_wrapper_present(self, tmp_output):
        """При anomalies и breadth extremes се появяват series-ref обвивки."""
        snapshot = {k: spike_up(base=2.0 + i*0.001, spike=10.0 + i*0.1)
                    for i, k in enumerate(list(SERIES_CATALOG.keys())[:20])}
        path = generate_weekly_briefing(snapshot, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        # Поне в няколко места — anom feed + breadth table + lens blocks
        assert content.count('class="series-ref') >= 10

    def test_tooltip_structural_classes_present(self, tmp_output):
        """CSS класовете на tooltip-а се появяват в HTML."""
        snapshot = {k: spike_up() for k in list(SERIES_CATALOG.keys())[:10]}
        path = generate_weekly_briefing(snapshot, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        assert 'class="tooltip"' in content
        assert 'tooltip-title' in content
        assert 'tooltip-id' in content
        assert 'tooltip-meta' in content
        assert 'Леща:' in content  # label
        assert 'Peer:' in content

    def test_tooltip_contains_name_bg_for_known_series(self, tmp_output):
        """UNRATE има name_bg 'Безработица (headline, U-3)' — появява се в tooltip-а."""
        snapshot = {"UNRATE": spike_up()}
        # Добавяме flat за останалите peer-и за да не break-не breadth-а
        for k in SERIES_CATALOG.keys():
            if k != "UNRATE":
                snapshot[k] = flat()
        path = generate_weekly_briefing(snapshot, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        assert "Безработица (headline, U-3)" in content

    def test_tooltip_is_css_only_no_script(self, tmp_output):
        """Tooltip имплементацията е CSS-only — без JS."""
        snapshot = {k: trend_up() for k in list(SERIES_CATALOG.keys())[:10]}
        path = generate_weekly_briefing(snapshot, str(tmp_output))
        content = Path(path).read_text(encoding="utf-8")
        assert "<script" not in content.lower()
        # И CSS hover правилото присъства
        assert ".series-ref:hover .tooltip" in content

    def test_unknown_series_key_renders_without_tooltip(self):
        """Series-ref helper-ът не crash-ва при unknown ключ и не слага tooltip."""
        from export.weekly_briefing import _render_series_ref
        html_out = _render_series_ref("UNKNOWN_XYZ_123")
        assert "UNKNOWN_XYZ_123" in html_out
        assert "tooltip" not in html_out  # без tooltip panel
        assert "series-ref-unknown" in html_out
