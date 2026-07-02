"""
tests/test_regime_confidence.py
================================
P3-fix-C (D1, решение на Цветослав 03.07): „потвърден" се ЗАСЛУЖАВА —
режим, видян за първи път, е „индикиран"; ≥2 поредни ПУБЛИКУВАНИ снимки
в същия режим → „потвърден". Плюс пин на декларативното credit-stress
правило (D2 рефактор — поведенчески идентичен за US).
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "tests"))  # за fixture импорта от test_executive

from analysis.executive import (  # noqa: E402
    CREDIT_STRESS_RULES,
    REGIME_LABELS_BG,
    REGIME_LABELS_BG_INDICATED,
    compute_executive_summary,
    resolve_regime_label_bg,
)
from test_executive import (  # noqa: E402
    make_anomaly_report,
    make_cross_report,
    make_lens_reports,
    make_nc_report,
)


def _compute(prev=None):
    cross = make_cross_report({"stagflation_test": "both_up"})
    lens_reports = make_lens_reports({
        "labor": [("wage_dynamics", "expanding", 0.8)],
    })
    return compute_executive_summary(
        cross, lens_reports, make_anomaly_report(), make_nc_report(),
        previous_regime_key=prev,
    )


class TestConfidenceGate:
    def test_no_previous_is_indicated(self):
        snap = _compute(prev=None)
        assert snap.regime_confidence == "indicated"
        assert snap.regime_label_bg == "Стагфлация (индикирана)"

    def test_same_previous_is_confirmed(self):
        snap = _compute(prev="stagflation_confirmed")
        assert snap.regime_confidence == "confirmed"
        assert snap.regime_label_bg == "Стагфлация (потвърдена)"

    def test_different_previous_is_indicated(self):
        snap = _compute(prev="soft_landing")
        assert snap.regime_confidence == "indicated"
        assert snap.regime_label_bg == "Стагфлация (индикирана)"

    def test_confidence_flows_to_dict(self):
        d = _compute(prev="stagflation_confirmed").to_dict()
        assert d["regime_confidence"] == "confirmed"

    def test_transition_has_no_label_variants(self):
        assert resolve_regime_label_bg("transition", "indicated") == "Преходно / смесено"
        assert resolve_regime_label_bg("transition", "confirmed") == "Преходно / смесено"

    def test_all_regimes_have_indicated_variants(self):
        assert set(REGIME_LABELS_BG_INDICATED) == set(REGIME_LABELS_BG)
        for key, base in REGIME_LABELS_BG.items():
            confirmed = resolve_regime_label_bg(key, "confirmed")
            indicated = resolve_regime_label_bg(key, "indicated")
            # confirmed = установените (днешните) клиентски форми
            assert confirmed == base
            if key != "transition":
                assert "индикиран" in indicated, f"{key}: {indicated}"


class TestCreditStressRulesPin:
    def test_us_rules_declarative_pin(self):
        """D2 рефакторът е поведенчески идентичен за US — правилото пиннато."""
        assert CREDIT_STRESS_RULES == (
            ("credit_policy_transmission", ("a_up_b_down",)),
        )
