"""
econ_v2 — Module 03: Growth & Activity
========================================
16 FRED серии → 2 composite scores

Scores:
  • Activity Pulse  (0=Recession, 100=Boom)
  • Leading Signal  (0=Contraction coming, 100=Expansion ahead)

Режими: EXPANSION → SOLID GROWTH → SLUGGISH → CONTRACTION → RECESSION
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.scorer import score_series, composite_score, build_sparkline, build_historical_context
from config import HISTORY_START

# ─── FRED серии ──────────────────────────────────────────────────────────────

SERIES = {
    # Activity (current)
    "INDPRO":   {"label": "Industrial Production (YoY%)", "invert": False},
    "RSXFS":    {"label": "Retail Sales ex-food (YoY%)", "invert": False},
    "DPCERA3M086SBEA": {"label": "Real PCE (YoY%)", "invert": False},
    "TOTALSA":  {"label": "Auto Sales (000s units)", "invert": False},

    # Leading / Forward-looking
    "T10Y3M":   {"label": "10Y-3M Yield Curve (%)", "invert": False},
    "T10Y2Y":   {"label": "10Y-2Y Yield Curve (%)", "invert": False},
    "CFNAI":    {"label": "Chicago Fed Activity Index", "invert": False},
    "PERMIT":   {"label": "Building Permits (000s)", "invert": False},
    "UMCSENT":  {"label": "U Mich Consumer Sentiment", "invert": False},
}

# Composite weights
ACTIVITY_SERIES   = ["INDPRO", "RSXFS", "DPCERA3M086SBEA", "TOTALSA"]
ACTIVITY_WEIGHTS  = [0.35,     0.30,    0.25,               0.10]

LEADING_SERIES    = ["T10Y3M", "T10Y2Y", "CFNAI", "PERMIT", "UMCSENT"]
LEADING_WEIGHTS   = [0.25,     0.20,     0.25,      0.15,     0.15]

# Режими
REGIMES = [
    (75, "EXPANSION",    "#00c853"),
    (60, "SOLID GROWTH", "#69f0ae"),
    (45, "SLUGGISH",     "#ffd600"),
    (30, "CONTRACTION",  "#ff6d00"),
    (0,  "RECESSION",    "#d50000"),
]

# Серии, за които изчисляваме YoY (level серии)
LEVEL_SERIES = {"INDPRO", "RSXFS", "DPCERA3M086SBEA", "TOTALSA", "PERMIT"}


def run(client) -> dict:
    print("  [Growth] Fetching data...")

    raw = {}
    for sid in SERIES:
        try:
            raw[sid] = client.get(sid, start="1970-01-01")
        except Exception as e:
            print(f"    ⚠ Could not fetch {sid}: {e}")

    scores = {}
    for sid, meta in SERIES.items():
        if sid in raw:
            series = _transform(sid, raw[sid])
            scores[sid] = score_series(
                series,
                history_start=HISTORY_START,
                invert=meta["invert"],
                name=meta["label"],
            )

    activity = _composite(scores, ACTIVITY_SERIES, ACTIVITY_WEIGHTS)
    leading  = _composite(scores, LEADING_SERIES, LEADING_WEIGHTS)

    # Composite = 60% activity + 40% leading
    composite = round(0.60 * activity + 0.40 * leading, 1)
    regime_label, regime_color = _get_regime(composite)

    sparklines = {}
    for sid in ["INDPRO", "RSXFS", "T10Y3M", "CFNAI", "UMCSENT"]:
        if sid in raw:
            s = _transform(sid, raw[sid])
            sparklines[sid] = build_sparkline(s, months=36)

    hist_context = {}
    if "T10Y3M" in raw:
        hist_context["T10Y3M"] = build_historical_context(
            raw["T10Y3M"], float(raw["T10Y3M"].iloc[-1])
        )

    return {
        "module": "growth",
        "label": "Growth & Activity",
        "icon": "📈",
        "scores": {
            "activity_pulse": {"score": activity, "label": "Activity Pulse"},
            "leading_signal": {"score": leading,  "label": "Leading Signal"},
        },
        "composite": composite,
        "regime": regime_label,
        "regime_color": regime_color,
        "indicators": scores,
        "sparklines": sparklines,
        "historical_context": hist_context,
        "key_readings": _key_readings(scores, raw),
    }


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _transform(sid: str, series):
    if sid in LEVEL_SERIES:
        pct = series.pct_change(12) * 100
        return pct.dropna()
    return series


def _composite(scores: dict, series_list: list, weights: list) -> float:
    vals = [scores[s]["score"] for s in series_list if s in scores]
    wts  = [weights[i] for i, s in enumerate(series_list) if s in scores]
    if not vals:
        return 50.0
    return round(sum(v * w for v, w in zip(vals, wts)) / sum(wts), 1)


def _get_regime(score: float) -> tuple:
    for threshold, label, color in REGIMES:
        if score >= threshold:
            return label, color
    return "RECESSION", "#d50000"


def _key_readings(scores: dict, raw: dict) -> list:
    result = []
    for sid in ["INDPRO", "RSXFS", "T10Y3M", "T10Y2Y", "CFNAI", "UMCSENT"]:
        if sid in scores:
            s = scores[sid]
            result.append({
                "id": sid,
                "label": s["name"],
                "value": s["current_value"],
                "date": s["last_date"],
                "yoy": s["yoy_change"],
                "percentile": s["percentile"],
                "score": s["score"],
            })
    return result
