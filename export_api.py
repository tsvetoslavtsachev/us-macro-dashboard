"""
export_api.py
=============
Генерира два статични JSON файла за уеб дашборда:

  output/api/macro_state.json   — аналитичен слой (режими, аномалии, дивергенции)
  output/api/series_data.json   — времеви редове за графиките (последните N години)

Използва СЪЩИЯ pipeline като weekly_briefing.py — без нови изчисления,
само сериализира вече изчислените резултати в JSON формат.

Употреба:
  python export_api.py                  # от cache (без мрежа)
  python export_api.py --refresh        # force-fetch от FRED преди export
  python export_api.py --years 10       # последните 10 години в series_data
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

# ── path setup ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from config import FRED_API_KEY, HISTORY_START
from catalog.series import SERIES_CATALOG
from sources.fred_adapter import FredAdapter
from core.scorer import score_series
from core.display import change_kind, compute_change, fmt_change, fmt_value
from analysis.breadth import compute_lens_breadth
from analysis.divergence import compute_cross_lens_divergence, compute_intra_lens_divergence
from analysis.anomaly import compute_anomalies
from analysis.non_consensus import compute_non_consensus
from analysis.executive import compute_executive_summary, REGIME_LABELS_BG, REGIME_CSS_CLASS

# ── константи ───────────────────────────────────────────────────────────────
OUTPUT_DIR = BASE_DIR / "output" / "api"
LENSES = ["labor", "growth", "inflation", "liquidity"]

# Кои серии да включим в series_data.json (ключови за графиките)
# Избрани по важност за всяка леща
CHART_SERIES = {
    "labor": [
        "UNRATE", "U6RATE", "PAYEMS", "ICSA", "JTSJOL",
        "JTSQUR", "JTSLDL", "EMRATIO", "CIVPART", "AHE",
    ],
    "inflation": [
        "CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE",
        "PPIFIS", "CPI_SHELTER", "CPI_SERVICES", "CPI_GOODS",
        "BREAKEVEN_10Y", "MICH_INFL_1Y",
    ],
    "growth": [
        "INDPRO", "RSAFS", "UMCSENT", "CFNAIMA3",
        "PHILLY_FED", "PSAVERT",
    ],
    "liquidity": [
        "FED_FUNDS", "UST_2Y", "UST_10Y", "YC_10Y2Y",
        "HY_OAS", "IG_OAS", "NFCI", "M2", "CC_DELINQUENCY",
    ],
    "housing": [
        "PERMIT", "HOUST",
    ],
}

# Всички chart серии в един flat set
ALL_CHART_SERIES = {s for series_list in CHART_SERIES.values() for s in series_list}

# ── JSON helpers ─────────────────────────────────────────────────────────────
def _clean(val: Any) -> Any:
    """Конвертира NaN/inf/Timestamp към JSON-safe типове."""
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        v = float(val)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(val, (np.bool_,)):
        return bool(val)
    if isinstance(val, pd.Timestamp):
        return str(val.date())
    return val


def _clean_dict(d: dict) -> dict:
    """Рекурсивно почиства речник от NaN/inf."""
    result = {}
    for k, v in d.items():
        if isinstance(v, dict):
            result[k] = _clean_dict(v)
        elif isinstance(v, list):
            result[k] = [_clean_dict(i) if isinstance(i, dict) else _clean(i) for i in v]
        else:
            result[k] = _clean(v)
    return result


def _safe_dump(obj: Any, path: Path) -> None:
    """Записва JSON с fallback за non-serializable типове."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
    size_kb = path.stat().st_size / 1024
    print(f"  ✅ {path.name} ({size_kb:.1f} KB)")


# ── macro_state.json builder ─────────────────────────────────────────────────
def build_macro_state(snapshot: dict, today: date) -> dict:
    """
    Изгражда macro_state.json — аналитичният слой.
    Структура:
      region, as_of_date, generated_at,
      executive_summary { composite_score, regime, narrative },
      lenses { labor/inflation/growth/liquidity: { score, regime, direction, ... } },
      top_anomalies [ ... ],
      cross_lens_divergences [ ... ],
      intra_lens_divergences { lens: [ ... ] }
    """
    print("  🧮 Изчислявам lens breadth...")
    lens_reports = {
        lens: compute_lens_breadth(lens, snapshot)
        for lens in LENSES
    }

    print("  🧮 Изчислявам cross-lens divergences...")
    cross_report = compute_cross_lens_divergence(snapshot)

    print("  🧮 Изчислявам anomalies...")
    anomaly_report = compute_anomalies(
        snapshot, z_threshold=2.0, top_n=15, lookback_years=5
    )

    print("  🧮 Изчислявам non-consensus...")
    nc_report = compute_non_consensus(snapshot)

    print("  🧮 Изчислявам executive summary...")
    exec_summary = compute_executive_summary(
        lens_reports=lens_reports,
        cross_report=cross_report,
        anomaly_report=anomaly_report,
        nc_report=nc_report,
    )

    # ── Intra-lens divergences ──────────────────────────────────────────────
    intra_divs = {}
    for lens in LENSES:
        report = compute_intra_lens_divergence(lens, snapshot)
        intra_divs[lens] = [d.to_dict() for d in report.divergences]

    # ── Per-lens summary ────────────────────────────────────────────────────
    lenses_out = {}
    for lens in LENSES:
        br = lens_reports[lens]
        # Намираме LensRegimeRow от executive summary
        exec_row = next(
            (r for r in exec_summary.lens_rows if r.lens == lens), None
        )
        # Изчисляваме score от breadth_agg (0..1 → 0..100)
        # breadth_agg = дял на серии с позитивна тенденция
        breadth_agg = exec_row.breadth_agg if exec_row else None
        if breadth_agg is not None and not (isinstance(breadth_agg, float) and math.isnan(breadth_agg)):
            score = round(breadth_agg * 100, 1)
        else:
            score = None
        direction = exec_row.direction if exec_row else "insufficient_data"
        lenses_out[lens] = {
            "score": _clean(score),
            "direction": direction,
            "breadth_pct": _clean(breadth_agg * 100 if breadth_agg is not None and not (isinstance(breadth_agg, float) and math.isnan(breadth_agg)) else None),
            "anomalies_count": exec_row.anomaly_count if exec_row else 0,
            "new_extreme_count": exec_row.new_extreme_count if exec_row else 0,
            "intra_divergences": intra_divs.get(lens, []),
        }

    # ── Top anomalies ───────────────────────────────────────────────────────
    top_anomalies = []
    for a in anomaly_report.top[:10]:
        meta = SERIES_CATALOG.get(a.series_key, {})
        top_anomalies.append({
            "series_id": a.series_key,
            "name_bg": a.series_name_bg,
            "lens": a.lens,
            "peer_group": a.peer_group,
            "z_score": _clean(a.z_score),
            "direction": a.direction,
            "current_value": _clean(a.last_value),
            "last_date": a.last_date,
            "is_new_extreme": a.is_new_extreme,
            "new_extreme_direction": a.new_extreme_direction,
            "narrative_hint": a.narrative_hint,
        })

    # ── Cross-lens divergences ───────────────────────────────────────────────
    cross_divs = []
    for pair in cross_report.pairs:
        cross_divs.append({
            "pair_id": pair.pair_id,
            "name_bg": pair.name_bg,
            "question_bg": pair.question_bg,
            "state": pair.state,
            "interpretation": pair.interpretation,
            "slot_a_label": pair.slot_a_label,
            "slot_b_label": pair.slot_b_label,
            "breadth_a": _clean(pair.breadth_a),
            "breadth_b": _clean(pair.breadth_b),
        })

    # ── Non-consensus highlights ─────────────────────────────────────────────
    nc_highlights = []
    for r in nc_report.highlights[:8]:
        nc_highlights.append({
            "series_id": r.series_key,
            "name_bg": SERIES_CATALOG.get(r.series_key, {}).get("name_bg", r.series_key),
            "lens": SERIES_CATALOG.get(r.series_key, {}).get("lens", []),
            "signal_strength": r.signal_strength,
            "percentile": _clean(r.percentile),
            "z_score": _clean(r.z_score),
            "direction": r.direction,
        })

    return _clean_dict({
        "region": "US",
        "as_of_date": str(today),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "executive_summary": {
            "regime_key": exec_summary.regime_label,
            "regime_label_bg": exec_summary.regime_label_bg,
            "css_class": exec_summary.regime_css_class,
            "narrative": exec_summary.narrative_bg,
            "supporting_signals": exec_summary.supporting_signals,
            "primary_driver": exec_summary.primary_driver,
        },
        "lenses": lenses_out,
        "top_anomalies": top_anomalies,
        "cross_lens_divergences": cross_divs,
        "non_consensus_highlights": nc_highlights,
    })


# ── series_data.json builder ─────────────────────────────────────────────────
def build_series_data(snapshot: dict, today: date, years: int = 7) -> dict:
    """
    Изгражда series_data.json — времеви редове за графиките.
    Включва само CHART_SERIES, последните `years` години.
    """
    cutoff = pd.Timestamp(today) - pd.DateOffset(years=years)
    series_out = {}

    for series_id in ALL_CHART_SERIES:
        if series_id not in snapshot:
            continue

        raw_series = snapshot[series_id]
        meta = SERIES_CATALOG.get(series_id, {})

        # Филтрираме по времеви прозорец
        filtered = raw_series[raw_series.index >= cutoff].dropna()
        if filtered.empty:
            continue

        # Определяме lens (взимаме първия)
        lens_list = meta.get("lens", [])
        primary_lens = lens_list[0] if lens_list else "other"

        # Последна стойност и промяна
        latest_val = float(filtered.iloc[-1])
        latest_date = str(filtered.index[-1].date())

        # YoY промяна
        kind = change_kind(series_id, meta)
        try:
            changes = compute_change(filtered, kind, periods=12)
            yoy_val = float(changes.iloc[-1]) if not changes.empty and not pd.isna(changes.iloc[-1]) else None
        except Exception:
            yoy_val = None

        # Форматиране на последна стойност
        transform = meta.get("transform", "level")
        is_rate = meta.get("is_rate", False)

        # Данни за графиката — dates и values
        dates = [str(d.date()) for d in filtered.index]
        values = [_clean(v) for v in filtered.values]

        # Score (percentile rank) за текущата стойност
        history = raw_series[raw_series.index >= pd.Timestamp(HISTORY_START)].dropna()
        score_data = score_series(raw_series, history_start=HISTORY_START, name=series_id)

        series_out[series_id] = {
            "meta": {
                "name_bg": meta.get("name_bg", series_id),
                "name_en": meta.get("name_en", series_id),
                "lens": primary_lens,
                "lens_all": lens_list,
                "peer_group": meta.get("peer_group", ""),
                "transform": transform,
                "is_rate": is_rate,
                "change_kind": kind,
                "release_schedule": meta.get("release_schedule", "monthly"),
                "narrative_hint": meta.get("narrative_hint", ""),
            },
            "latest": {
                "date": latest_date,
                "value": _clean(latest_val),
                "yoy_change": _clean(yoy_val),
                "percentile": _clean(score_data.get("percentile")),
                "z_score": _clean(score_data.get("z_score")),
                "score": _clean(score_data.get("score")),
                "regime": score_data.get("regime_label"),
            },
            "chart": {
                "dates": dates,
                "values": values,
            },
        }

    return _clean_dict({
        "region": "US",
        "last_updated": datetime.utcnow().isoformat() + "Z",
        "years_included": years,
        "series_count": len(series_out),
        "series": series_out,
    })


# ── main ─────────────────────────────────────────────────────────────────────
def main(args) -> None:
    today = date.today()

    print("\n" + "═" * 60)
    print("  📦  Export API JSON  —  us-macro-dashboard")
    print("═" * 60)
    print(f"  {datetime.now().strftime('%A, %d %B %Y · %H:%M')}")
    print("═" * 60 + "\n")

    # ── Инициализираме adapter ──────────────────────────────────────────────
    adapter = FredAdapter(api_key=FRED_API_KEY, base_dir=BASE_DIR)

    fred_specs = [
        {
            "key": key,
            "fred_id": meta["id"],
            "release_schedule": meta["release_schedule"],
        }
        for key, meta in SERIES_CATALOG.items()
        if meta.get("source") == "fred"
    ]

    if args.refresh:
        print("🔄 Force-refresh на FRED данни...")
        adapter.fetch_many(fred_specs, force=True)
        failures = adapter.last_fetch_failures()
        print(f"  ✅ {len(fred_specs) - len(failures)}/{len(fred_specs)} серии обновени")
        if failures:
            print(f"  ⚠ Failures: {', '.join(failures)}")
        print()
    else:
        stale = adapter.find_stale_specs(fred_specs)
        if stale:
            print(f"📦 Auto-refresh: {len(stale)} stale серии...")
            adapter.fetch_many(stale, force=False)
            failures = adapter.last_fetch_failures()
            print(f"  ✅ {len(stale) - len(failures)}/{len(stale)} обновени\n")
        else:
            print("📦 Cache fresh — пропускам refresh.\n")

    # ── Snapshot ────────────────────────────────────────────────────────────
    snapshot = adapter.get_snapshot(SERIES_CATALOG.keys())
    print(f"📊 Snapshot: {len(snapshot)}/{len(SERIES_CATALOG)} серии с данни\n")

    if len(snapshot) < 10:
        print("⚠ Твърде малко серии в snapshot — вероятно cache е празен.")
        print("  Стартирай с --refresh за да изтеглиш данни от FRED.\n")
        sys.exit(1)

    # ── Генерираме macro_state.json ─────────────────────────────────────────
    print("📝 Генерирам macro_state.json...")
    macro_state = build_macro_state(snapshot, today)
    _safe_dump(macro_state, OUTPUT_DIR / "macro_state.json")

    # ── Генерираме series_data.json ─────────────────────────────────────────
    print("\n📈 Генерирам series_data.json...")
    series_data = build_series_data(snapshot, today, years=args.years)
    _safe_dump(series_data, OUTPUT_DIR / "series_data.json")

    print(f"\n✅ Done! Файловете са в: {OUTPUT_DIR}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Export macro analysis to JSON API files for web dashboard."
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force-fetch всички FRED серии преди export.",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=7,
        help="Колко години история да включим в series_data.json (default: 7).",
    )
    args = parser.parse_args()
    main(args)
