"""
tests/test_build_latest.py
==========================
Offline тестове за AI-consumption manifest builder-а (Фаза 4 / C3).
`build_manifest` е чиста функция върху macro_state dict — без файлове, без мрежа.

Заключва хармонизираната manifest схема (region · as_of · composite · regime ·
lenses · top_anomalies · links) и composite логиката (stored > mean fallback;
None scores се skip-ват).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from export.build_latest import build_manifest


def _state(lenses, anomalies=None, composite=None):
    es = {"regime_key": "test_regime", "regime_label_bg": "Тест режим"}
    if composite is not None:
        es["composite_score"] = composite
    return {
        "region": "US",
        "as_of_date": "2026-05-30",
        "generated_at": "2026-05-30T09:00:00Z",
        "executive_summary": es,
        "lenses": lenses,
        "top_anomalies": anomalies or [],
        "cross_lens_divergences": [],
    }


def test_composite_mean_fallback():
    """Без stored composite → mean на numeric lens scores."""
    m = build_manifest(_state({
        "labor": {"score": 60.0, "direction": "expanding"},
        "growth": {"score": 40.0, "direction": "mixed"},
    }))
    assert m["composite_score"] == 50.0


def test_composite_skips_none_scores():
    """None-score лещи се изключват от composite, но остават в lenses списъка."""
    m = build_manifest(_state({
        "labor": {"score": None, "direction": "insufficient_data"},
        "growth": {"score": 30.0, "direction": "contracting"},
    }))
    assert m["composite_score"] == 30.0
    assert len(m["lenses"]) == 2  # None лещата пак се изброява


def test_stored_composite_preferred():
    """Stored composite_score (China = претеглен) бие mean fallback-а."""
    m = build_manifest(_state(
        {"labor": {"score": 60.0, "direction": "expanding"},
         "growth": {"score": 40.0, "direction": "mixed"}},
        composite=30.4,
    ))
    assert m["composite_score"] == 30.4  # НЕ 50.0


def test_anomaly_lens_list_flattened():
    """lens като list (US/China anomaly) → първи елемент в manifest."""
    m = build_manifest(_state(
        {"labor": {"score": 50.0, "direction": "mixed"}},
        anomalies=[{"series_id": "X", "name_bg": "Х", "lens": ["labor", "growth"],
                    "z_score": 2.5, "direction": "up"}],
    ))
    assert m["top_anomalies"][0]["lens"] == "labor"


def test_schema_contract():
    """Хармонизираните задължителни полета присъстват."""
    m = build_manifest(_state({"labor": {"score": 50.0, "direction": "mixed"}}))
    for key in ("schema_version", "region", "as_of_date", "generated_at",
                "composite_score", "regime", "lenses", "top_anomalies",
                "counts", "links"):
        assert key in m, f"липсва {key}"
    assert m["regime"]["key"] == "test_regime"
    assert set(m["links"]) >= {"context_md", "data_json", "series_json"}
    assert m["lenses"][0]["label_bg"]  # винаги непразен (stored или fallback)
