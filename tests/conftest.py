"""
tests/conftest.py — тестова хигиена (P3-fix-B, REVIEW-03).

generate_weekly_briefing() по подразбиране persist-ва WoW state в data/state/
(git-следена директория). Тестовете, които го викат без изричен state_dir,
презаписваха data/state/briefing_2026-04-18.json В САМОТО РЕПО — невидимо,
докато презаписваното съдържание съвпадаше байт-по-байт, и мръсно работно
дърво при първата семантична промяна (хванато при P3-fix-B т.0.1).

Тук пренасочваме и записа, и четенето на briefing state към tmp директория
за целия suite. Тестове, които изрично подават state_dir (test_delta),
не са засегнати — те не минават през weekly_briefing namespace-а.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))


@pytest.fixture(autouse=True)
def _redirect_briefing_state(monkeypatch, tmp_path):
    import export.weekly_briefing as wb
    from analysis.delta import load_latest_state, save_state

    state_dir = str(tmp_path / "briefing_state")

    def _tmp_save(snapshot, state_dir_ignored=None, **kwargs):
        return save_state(snapshot, state_dir=state_dir)

    def _tmp_load(state_dir_ignored=None, **kwargs):
        kwargs.pop("state_dir", None)
        return load_latest_state(state_dir=state_dir, **kwargs)

    monkeypatch.setattr(wb, "save_state", _tmp_save)
    monkeypatch.setattr(wb, "load_latest_state", _tmp_load)

    # P3-fix-C (D1): „индикиран/потвърден" вратата чете последния ПУБЛИКУВАН
    # macro_state.json (реален repo файл) — за херметичност тестовете винаги
    # виждат None (= indicated). Тестове за confirmed подават previous_regime_key
    # изрично на compute_executive_summary.
    import importlib

    for mod_name in ("export_api", "export.quick_briefing", "export.weekly_briefing"):
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        if hasattr(mod, "load_previous_published_regime"):
            monkeypatch.setattr(
                mod, "load_previous_published_regime", lambda *a, **k: None
            )
