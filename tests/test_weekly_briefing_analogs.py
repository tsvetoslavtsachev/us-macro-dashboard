"""
tests/test_weekly_briefing_analogs.py
======================================
Тестове за Historical Analog секция в briefing-а (Phase 4 Task 4.5).

Проверяват:
  - Ако analog_bundle=None → секцията липсва (backwards compat).
  - Ако bundle се подава → section присъства със всички очаквани елементи.
  - Backwards compat: съществуващите секции не се нарушават.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from analysis.analog_matcher import AnalogResult
from analysis.analog_comparison import DimensionComparison, DimensionDelta
from analysis.analog_pipeline import AnalogBundle
from analysis.forward_path import ForwardOutcomes, HorizonSummary, PerAnalogForward
from analysis.macro_vector import MacroState, STATE_VECTOR_DIMS
from export.weekly_briefing import generate_weekly_briefing


# ============================================================
# FIXTURES
# ============================================================

def _make_minimal_bundle() -> AnalogBundle:
    """Строи минимален но валиден AnalogBundle за рендиране тестове."""
    as_of = pd.Timestamp("2026-03-31")
    raw = {d: 1.0 + i * 0.1 for i, d in enumerate(STATE_VECTOR_DIMS)}
    z = {d: 0.5 - i * 0.1 for i, d in enumerate(STATE_VECTOR_DIMS)}
    current = MacroState(as_of=as_of, raw=raw, z=z)

    # Един analog — 1981-06
    analog_date = pd.Timestamp("1981-06-30")
    analog = AnalogResult(
        date=analog_date,
        similarity=0.87,
        rank=1,
        raw={d: 1.5 + i * 0.1 for i, d in enumerate(STATE_VECTOR_DIMS)},
        z={d: 0.4 - i * 0.08 for i, d in enumerate(STATE_VECTOR_DIMS)},
        episode_label="Volcker disinflation",
    )

    # DimensionComparison ръчно (mirror на compare_dimensions logic)
    deltas = []
    for d in STATE_VECTOR_DIMS:
        cur_z = current.z[d]
        ana_z = analog.z[d]
        deltas.append(DimensionDelta(
            dim=d,
            label_bg={"unrate": "Безработица"}.get(d, d),
            current_raw=current.raw[d],
            analog_raw=analog.raw[d],
            current_z=cur_z,
            analog_z=ana_z,
            z_diff=ana_z - cur_z,
            abs_z_diff=abs(ana_z - cur_z),
            classification="close",
        ))
    comp = DimensionComparison(
        similarities=sorted(deltas, key=lambda d: d.abs_z_diff),
        divergences=[d for d in deltas if d.abs_z_diff > 1.0],
    )

    # Forward outcomes — един analog, два horizon-а
    per = PerAnalogForward(
        analog_date=analog_date,
        episode_label="Volcker disinflation",
        values={"unrate": {6: 7.5, 12: 8.3}, "core_cpi_yoy": {6: 11.0, 12: 9.5}},
        deltas={"unrate": {6: 0.5, 12: 1.3}, "core_cpi_yoy": {6: -0.5, 12: -2.0}},
    )
    aggregates = [
        HorizonSummary(dim="unrate", horizon_months=6, n=1,
                       median_value=7.5, min_value=7.5, max_value=7.5,
                       median_delta=0.5, min_delta=0.5, max_delta=0.5),
        HorizonSummary(dim="unrate", horizon_months=12, n=1,
                       median_value=8.3, min_value=8.3, max_value=8.3,
                       median_delta=1.3, min_delta=1.3, max_delta=1.3),
        HorizonSummary(dim="core_cpi_yoy", horizon_months=6, n=1,
                       median_value=11.0, min_value=11.0, max_value=11.0,
                       median_delta=-0.5, min_delta=-0.5, max_delta=-0.5),
        HorizonSummary(dim="core_cpi_yoy", horizon_months=12, n=1,
                       median_value=9.5, min_value=9.5, max_value=9.5,
                       median_delta=-2.0, min_delta=-2.0, max_delta=-2.0),
    ]
    fwd = ForwardOutcomes(
        per_analog=[per],
        aggregates=aggregates,
        horizons=[6, 12],
        dims=["unrate", "core_cpi_yoy"],
    )

    # history_df / history_z — placeholder, не се ползват в render-а
    empty_df = pd.DataFrame()
    return AnalogBundle(
        current_state=current,
        history_df=empty_df,
        history_z=empty_df,
        analogs=[analog],
        comparisons=[comp],
        forward=fwd,
    )


# ============================================================
# TESTS
# ============================================================

class TestAnalogSectionOptional:

    def test_no_bundle_omits_analog_section(self, tmp_path):
        out = tmp_path / "briefing.html"
        generate_weekly_briefing(
            snapshot={},
            output_path=str(out),
            today=date(2026, 4, 18),
            state_dir=None,
            persist_state=False,
            analog_bundle=None,
        )
        html = out.read_text(encoding="utf-8")
        assert "Исторически аналог" not in html
        # CSS клас може да остане в <style>, но секция-елемент не трябва да се рендирa
        assert '<section class="brief-section analog-section">' not in html

    def test_with_bundle_includes_analog_section(self, tmp_path):
        out = tmp_path / "briefing.html"
        bundle = _make_minimal_bundle()
        generate_weekly_briefing(
            snapshot={},
            output_path=str(out),
            today=date(2026, 4, 18),
            state_dir=None,
            persist_state=False,
            analog_bundle=bundle,
        )
        html = out.read_text(encoding="utf-8")
        assert "Исторически аналог" in html
        assert "analog-section" in html

    def test_analog_card_contains_date_and_episode(self, tmp_path):
        out = tmp_path / "briefing.html"
        bundle = _make_minimal_bundle()
        generate_weekly_briefing(
            snapshot={},
            output_path=str(out),
            today=date(2026, 4, 18),
            state_dir=None,
            persist_state=False,
            analog_bundle=bundle,
        )
        html = out.read_text(encoding="utf-8")
        # Дата на analog-а
        assert "1981-06" in html
        # Episode label
        assert "Volcker disinflation" in html
        # Similarity стойност
        assert "0.870" in html

    def test_current_state_strip_shows_values(self, tmp_path):
        out = tmp_path / "briefing.html"
        bundle = _make_minimal_bundle()
        generate_weekly_briefing(
            snapshot={},
            output_path=str(out),
            today=date(2026, 4, 18),
            state_dir=None,
            persist_state=False,
            analog_bundle=bundle,
        )
        html = out.read_text(encoding="utf-8")
        # as_of в strip
        assert "2026-03" in html
        # всичките 8 dim labels от DIM_LABELS_BG
        assert "Безработица" in html
        assert "Core CPI YoY" in html

    def test_caveat_banner_present(self, tmp_path):
        out = tmp_path / "briefing.html"
        bundle = _make_minimal_bundle()
        generate_weekly_briefing(
            snapshot={},
            output_path=str(out),
            today=date(2026, 4, 18),
            state_dir=None,
            persist_state=False,
            analog_bundle=bundle,
        )
        html = out.read_text(encoding="utf-8")
        assert "Аналог ≠ прогноза" in html
        assert "analog-caveat" in html

    def test_forward_outcomes_table_present(self, tmp_path):
        out = tmp_path / "briefing.html"
        bundle = _make_minimal_bundle()
        generate_weekly_briefing(
            snapshot={},
            output_path=str(out),
            today=date(2026, 4, 18),
            state_dir=None,
            persist_state=False,
            analog_bundle=bundle,
        )
        html = out.read_text(encoding="utf-8")
        # Per-analog forward
        assert "analog-forward" in html
        # Aggregate block
        assert "analog-aggregate" in html
        assert "медиана" in html

    def test_strength_class_applied(self, tmp_path):
        out = tmp_path / "briefing.html"
        bundle = _make_minimal_bundle()  # similarity 0.87 → "good"
        generate_weekly_briefing(
            snapshot={},
            output_path=str(out),
            today=date(2026, 4, 18),
            state_dir=None,
            persist_state=False,
            analog_bundle=bundle,
        )
        html = out.read_text(encoding="utf-8")
        assert "analog-strength-good" in html

    def test_empty_analogs_list_renders_nothing(self, tmp_path):
        """AnalogBundle с празен analogs list → sectionnel е празен string."""
        as_of = pd.Timestamp("2026-03-31")
        raw = {d: 1.0 for d in STATE_VECTOR_DIMS}
        z = {d: 0.0 for d in STATE_VECTOR_DIMS}
        current = MacroState(as_of=as_of, raw=raw, z=z)
        bundle = AnalogBundle(
            current_state=current,
            history_df=pd.DataFrame(),
            history_z=pd.DataFrame(),
            analogs=[],
            comparisons=[],
            forward=ForwardOutcomes(per_analog=[], aggregates=[], horizons=[], dims=[]),
        )
        out = tmp_path / "briefing.html"
        generate_weekly_briefing(
            snapshot={},
            output_path=str(out),
            today=date(2026, 4, 18),
            state_dir=None,
            persist_state=False,
            analog_bundle=bundle,
        )
        html = out.read_text(encoding="utf-8")
        # Празен analogs → _render_analogs връща "", няма секция-елемент
        assert '<section class="brief-section analog-section">' not in html
        assert "Исторически аналог" not in html


class TestBackwardsCompat:

    def test_existing_signature_still_works(self, tmp_path):
        """Без analog_bundle kwarg — трябва да работи както преди."""
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
        # Стандартни секции все още присъстват
        assert "Executive Summary" in html
        assert "Cross-Lens" in html
