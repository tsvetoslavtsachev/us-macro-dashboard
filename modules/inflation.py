"""
econ_v2 — Module 01: Inflation & Prices
=========================================
18 FRED серии → 3 composite scores

Scores:
  • Inflation Pulse   (0=Deflationary, 100=Runaway)
  • Expectations      (0=Anchored, 100=Unanchored)
  • Stickiness Index  (0=Transitory, 100=Structural)

Режими: DEFLATIONARY → SUBDUED → ON TARGET → ELEVATED → HOT → RUNAWAY
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.scorer import score_series, composite_score, build_sparkline, build_historical_context
from config import HISTORY_START

# ─── FRED серии ──────────────────────────────────────────────────────────────

SERIES = {
    # Inflation Pulse
    "CPILFESL":           {"label": "Core CPI YoY (%)", "invert": False},
    "PCEPILFE":           {"label": "Core PCE YoY (%)", "invert": False},
    "CORESTICKM159SFRBATL": {"label": "Sticky Core CPI (%)", "invert": False},
    "CPIAUCSL":           {"label": "Headline CPI YoY (%)", "invert": False},
    "PPIACO":             {"label": "PPI All Commodities", "invert": False},

    # Expectations
    "T5YIE":   {"label": "5Y Breakeven Inflation (%)", "invert": False},
    "T10YIE":  {"label": "10Y Breakeven Inflation (%)", "invert": False},
    "MICH":    {"label": "U Mich Inflation Exp. (%)", "invert": False},

    # Stickiness / Structural
    "MEDCPIM158SFRBCLE": {"label": "Median CPI (%)", "invert": False},
}

# Режими — центрирани около Fed target от 2%
REGIMES = [
    (90, "RUNAWAY",      "#7b0000"),
    (75, "HOT",          "#d50000"),
    (60, "ELEVATED",     "#ff6d00"),
    (40, "ON TARGET",    "#00c853"),
    (25, "SUBDUED",      "#69f0ae"),
    (0,  "DEFLATIONARY", "#0091ea"),
]

# Composite weights
PULSE_SERIES   = ["CPILFESL", "PCEPILFE", "CORESTICKM159SFRBATL", "CPIAUCSL", "PPIACO"]
PULSE_WEIGHTS  = [0.30,        0.25,        0.20,                   0.15,       0.10]

EXPECT_SERIES  = ["T5YIE", "T10YIE", "MICH"]
EXPECT_WEIGHTS = [0.40,     0.30,     0.30]

STICKY_SERIES  = ["CORESTICKM159SFRBATL", "MEDCPIM158SFRBCLE", "CPILFESL"]
STICKY_WEIGHTS = [0.45,                    0.35,                 0.20]


def run(client) -> dict:
    print("  [Inflation] Fetching data...")

    raw = {}
    for sid in SERIES:
        try:
            raw[sid] = client.get(sid, start="1970-01-01")
        except Exception as e:
            print(f"    ⚠ Could not fetch {sid}: {e}")

    # Score всяка серия
    scores = {}
    for sid, meta in SERIES.items():
        if sid in raw:
            # Трансформираме: изчисляваме YoY промяна за level серии
            series = raw[sid]
            # Ако серията е level (а не rate), изчисляваме YoY
            series_to_score = _to_yoy_if_needed(sid, series)
            scores[sid] = score_series(
                series_to_score,
                history_start=HISTORY_START,
                invert=meta["invert"],
                name=meta["label"],
            )

    # Composite scores
    pulse    = _composite(scores, PULSE_SERIES, PULSE_WEIGHTS)
    expect   = _composite(scores, EXPECT_SERIES, EXPECT_WEIGHTS)
    stickiness = _composite(scores, STICKY_SERIES, STICKY_WEIGHTS)

    regime_label, regime_color = _get_regime(pulse)

    sparklines = {}
    for sid in ["CPILFESL", "PCEPILFE", "T5YIE", "MICH", "CORESTICKM159SFRBATL"]:
        if sid in raw:
            s = _to_yoy_if_needed(sid, raw[sid])
            sparklines[sid] = build_sparkline(s, months=36)

    hist_context = {}
    if "CPILFESL" in raw:
        s = _to_yoy_if_needed("CPILFESL", raw["CPILFESL"])
        hist_context["CPILFESL"] = build_historical_context(s, float(s.iloc[-1]))

    return {
        "module": "inflation",
        "label": "Inflation & Prices",
        "icon": "📊",
        "scores": {
            "inflation_pulse": {"score": pulse,      "label": "Inflation Pulse"},
            "expectations":    {"score": expect,     "label": "Expectations"},
            "stickiness":      {"score": stickiness, "label": "Stickiness"},
        },
        "composite": pulse,
        "regime": regime_label,
        "regime_color": regime_color,
        "indicators": scores,
        "sparklines": sparklines,
        "historical_context": hist_context,
        "key_readings": _key_readings(scores, raw),
    }


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _to_yoy_if_needed(sid: str, series):
    """За level серии (PPI, etc.) изчислява YoY %. За rate серии — директно."""
    level_series = {"PPIACO", "CPIAUCSL", "CPILFESL", "PCEPILFE",
                    "CORESTICKM159SFRBATL", "MEDCPIM158SFRBCLE"}
    if sid in level_series:
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
    return "DEFLATIONARY", "#0091ea"


def _key_readings(scores: dict, raw: dict) -> list:
    result = []
    for sid in ["CPILFESL", "PCEPILFE", "T5YIE", "MICH", "CORESTICKM159SFRBATL"]:
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
