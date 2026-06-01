"""
build_latest.py
===============
AI-consumption layer (Фаза 4 / C3) — сглобява стабилен `latest/` пакет за
machine-readable достъп от AI на ФИКСИРАН URL (без да гадае датата).

Пише в `output/latest/`:

  context.md      — LLM-friendly markdown (копие на най-свежия briefing_context)
  data.json       — пълният аналитичен слой (копие на output/api/macro_state.json)
  series.json     — времеви редове за графики (копие на output/api/series_data.json)
  manifest.json   — ХАРМОНИЗИРАН slim contract (~2 KB): region, as_of, composite,
                    regime, per-lens scores, top anomalies, links.
                    Същата схема за US · EU · China (BG ще я следва по TEMPLATE.md).

Това е POST-PROCESSOR: чете вече генерираните артефакти, не преизчислява pipeline-а.
Затова в CI трябва да върви СЛЕД `export_api.py` (macro_state + series_data) и
`run.py --export-context` (briefing_context_*.md).

Употреба:
  python export/build_latest.py            # сглоби от output/api + най-свеж context
  python export/build_latest.py --check     # само провери че входните файлове ги има
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── path setup ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Windows cp1252 stdout guard (Кирилица в принтовете крашва иначе)
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# LENS_LABEL_BG е авторитетният източник за US/EU. China няма executive.py —
# там етикетите идват от macro_state (lens["label_bg"]), затова импортът е optional.
try:
    from analysis.executive import LENS_LABEL_BG
except Exception:
    LENS_LABEL_BG = {}

# ── константи ───────────────────────────────────────────────────────────────
SCHEMA_VERSION = "1.0"
REGION = "US"
API_DIR = BASE_DIR / "output" / "api"
OUTPUT_DIR = BASE_DIR / "output"
LATEST_DIR = OUTPUT_DIR / "latest"

MACRO_STATE = API_DIR / "macro_state.json"
SERIES_DATA = API_DIR / "series_data.json"

TOP_ANOMALIES_N = 5


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _newest_context_md() -> Path | None:
    """Най-свежият briefing_context_*.md по дата във файловото име (fallback: mtime)."""
    candidates = sorted(OUTPUT_DIR.glob("briefing_context_*.md"))
    if not candidates:
        return None
    # имената са briefing_context_YYYY-MM-DD.md → лексикографски = хронологичен ред
    return candidates[-1]


def _composite_from_lenses(lenses: dict) -> float | None:
    """Composite = mean на per-lens score-овете (skip None/NaN). Огледало на
    quick_briefing._composite_score (mean breadth_agg × 100)."""
    vals = [
        l["score"]
        for l in lenses.values()
        if isinstance(l.get("score"), (int, float))
    ]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 1)


def build_manifest(macro_state: dict) -> dict:
    """Slim, хармонизиран AI-entry-point от пълния macro_state."""
    lenses = macro_state.get("lenses", {})
    exec_sum = macro_state.get("executive_summary", {})
    anomalies = macro_state.get("top_anomalies", []) or []
    divergences = macro_state.get("cross_lens_divergences", []) or []

    lens_rows = []
    for key, l in lenses.items():
        lens_rows.append(
            {
                "key": key,
                # label_bg от macro_state (China) или от executive.py (US/EU)
                "label_bg": l.get("label_bg") or LENS_LABEL_BG.get(key, key),
                "score": l.get("score"),
                "direction": l.get("direction"),
            }
        )

    top = []
    for a in anomalies[:TOP_ANOMALIES_N]:
        lens = a.get("lens")
        if isinstance(lens, list):
            lens = lens[0] if lens else None
        top.append(
            {
                "series_id": a.get("series_id"),
                "name_bg": a.get("name_bg"),
                "lens": lens,
                "z_score": a.get("z_score"),
                "direction": a.get("direction"),
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "region": macro_state.get("region", REGION),
        "as_of_date": macro_state.get("as_of_date"),
        "generated_at": _utc_now_iso(),
        "data_generated_at": macro_state.get("generated_at"),
        # Авторитетен composite от pipeline-а (China = претеглен по MODULE_WEIGHTS),
        # fallback към mean(lens scores) за US/EU (огледало на _composite_score).
        "composite_score": exec_sum.get("composite_score")
        if isinstance(exec_sum.get("composite_score"), (int, float))
        else _composite_from_lenses(lenses),
        "regime": {
            "key": exec_sum.get("regime_key"),
            "label_bg": exec_sum.get("regime_label_bg"),
        },
        "lenses": lens_rows,
        "top_anomalies": top,
        "counts": {
            "lenses": len(lens_rows),
            "anomalies": len(anomalies),
            "divergences": len(divergences),
        },
        "links": {
            "context_md": "context.md",
            "data_json": "data.json",
            "series_json": "series.json",
            "dashboard": "../index.html",
        },
    }


def _check_inputs() -> list[str]:
    """Връща списък с липсващи входни файлове (за --check / fail-fast)."""
    missing = []
    if not MACRO_STATE.exists():
        missing.append(str(MACRO_STATE.relative_to(BASE_DIR)))
    if not SERIES_DATA.exists():
        missing.append(str(SERIES_DATA.relative_to(BASE_DIR)))
    if _newest_context_md() is None:
        missing.append("output/briefing_context_*.md")
    return missing


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Сглоби latest/ AI-consumption пакет.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Само провери че входните артефакти съществуват (CI guard).",
    )
    args = parser.parse_args(argv)

    missing = _check_inputs()
    if missing:
        print("⚠ Липсват входни артефакти за latest/ пакета:")
        for m in missing:
            print(f"   - {m}")
        print("\n   Изпълни първо: python export_api.py  +  python run.py --export-context")
        return 1
    if args.check:
        print("✅ Всички входни артефакти налични.")
        return 0

    LATEST_DIR.mkdir(parents=True, exist_ok=True)

    # 1) data.json ← macro_state.json
    macro_state = json.loads(MACRO_STATE.read_text(encoding="utf-8"))
    (LATEST_DIR / "data.json").write_text(
        json.dumps(macro_state, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 2) series.json ← series_data.json (straight copy)
    shutil.copyfile(SERIES_DATA, LATEST_DIR / "series.json")

    # 3) context.md ← най-свежият briefing_context_*.md
    ctx = _newest_context_md()
    shutil.copyfile(ctx, LATEST_DIR / "context.md")  # type: ignore[arg-type]

    # 4) manifest.json (slim, хармонизиран)
    manifest = build_manifest(macro_state)
    (LATEST_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"✅ latest/ пакет сглобен в: {LATEST_DIR}")
    print(f"   region={manifest['region']}  as_of={manifest['as_of_date']}  "
          f"composite={manifest['composite_score']}  "
          f"regime={manifest['regime']['key']}")
    print(f"   lenses={manifest['counts']['lenses']}  "
          f"anomalies={manifest['counts']['anomalies']}  "
          f"divergences={manifest['counts']['divergences']}")
    print(f"   context.md ← {ctx.name}")  # type: ignore[union-attr]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
