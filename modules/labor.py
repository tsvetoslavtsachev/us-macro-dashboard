"""
econ_v2 — Module 00: Labor Market
===================================
42 FRED серии → 3 composite scores

Scores:
  • Cyclical Health   (0=Stressed, 100=Hot)
  • AI Displacement   (0=Low risk, 100=High evidence of displacement)
  • Fear Index        (0=Confident, 100=Panicked)

Режими: HOT → HEALTHY → COOLING → WEAK → STRESSED
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from core.scorer import score_series, composite_score, build_sparkline, build_historical_context
from config import HISTORY_START

# ─── FRED серии ──────────────────────────────────────────────────────────────

SERIES = {
    # Cyclical Health
    "UNRATE":    {"label": "Unemployment Rate (%)", "invert": True},
    "U6RATE":    {"label": "U-6 Underemployment (%)", "invert": True},
    "PAYEMS":    {"label": "Nonfarm Payrolls (000s)", "invert": False},
    "ICSA":      {"label": "Initial Claims (000s)", "invert": True},
    "CIVPART":   {"label": "Labor Force Participation (%)", "invert": False},
    "JTSJOL":    {"label": "Job Openings (000s)", "invert": False},
    "JTSQUR":    {"label": "Quit Rate (%)", "invert": False},

    # AI Displacement proxies
    "TEMPHELPS": {"label": "Temp Help Employment (000s)", "invert": True},
    "USINFO":    {"label": "Information Sector Jobs (000s)", "invert": False},

    # Fear Index
    "JTSLDL":   {"label": "Layoffs & Discharges (000s)", "invert": True},
}

# Composite weights
CYCLICAL_SERIES  = ["UNRATE", "U6RATE", "PAYEMS", "ICSA", "CIVPART", "JTSJOL", "JTSQUR"]
CYCLICAL_WEIGHTS = [0.25,      0.15,     0.20,    0.15,   0.10,       0.10,     0.05]

AI_SERIES        = ["TEMPHELPS", "USINFO"]
AI_WEIGHTS       = [0.60,         0.40]

FEAR_SERIES      = ["UNRATE", "ICSA", "JTSLDL"]
FEAR_WEIGHTS     = [0.40,     0.30,   0.30]

# Режими
REGIMES = [
    (80, "HOT",      "#00c853"),
    (65, "HEALTHY",  "#69f0ae"),
    (45, "COOLING",  "#ffd600"),
    (30, "WEAK",     "#ff6d00"),
    (0,  "STRESSED", "#d50000"),
]


def run(client) -> dict:
    """
    Главна функция — зарежда данни, изчислява 3 scores, връща dict.
    """
    print("  [Labor] Fetching data...")

    # Вземи всички серии
    raw = {}
    for sid, meta in SERIES.items():
        try:
            raw[sid] = client.get(sid, start="1970-01-01")
        except Exception as e:
            print(f"    ⚠ Could not fetch {sid}: {e}")

    # ── Score всяка серия ────────────────────────────────────────────────────
    scores = {}
    for sid, meta in SERIES.items():
        if sid in raw:
            scores[sid] = score_series(
                raw[sid],
                history_start=HISTORY_START,
                invert=meta["invert"],
                name=meta["label"],
            )

    # ── Composite scores ─────────────────────────────────────────────────────
    cyclical = _composite(scores, CYCLICAL_SERIES, CYCLICAL_WEIGHTS)
    ai_disp  = _ai_displacement(scores)
    fear     = _fear_index(scores)

    # ── Режим (базиран на Cyclical Health) ───────────────────────────────────
    regime_label, regime_color = _get_regime(cyclical)

    # ── Sparklines за ключови серии ──────────────────────────────────────────
    sparklines = {}
    for sid in ["UNRATE", "ICSA", "PAYEMS", "JTSJOL", "JTSLDL"]:
        if sid in raw:
            sparklines[sid] = build_sparkline(raw[sid], months=36)

    # ── Исторически контекст за UNRATE ───────────────────────────────────────
    hist_context = {}
    if "UNRATE" in raw:
        hist_context["UNRATE"] = build_historical_context(raw["UNRATE"], float(raw["UNRATE"].iloc[-1]))

    return {
        "module": "labor",
        "label": "Labor Market",
        "icon": "👷",
        "scores": {
            "cyclical_health": {"score": cyclical, "label": "Cyclical Health"},
            "ai_displacement":  {"score": ai_disp,  "label": "AI Displacement"},
            "fear_index":       {"score": fear,      "label": "Fear Index"},
        },
        "composite": cyclical,          # главният score на модула
        "regime": regime_label,
        "regime_color": regime_color,
        "indicators": scores,
        "sparklines": sparklines,
        "historical_context": hist_context,
        "key_readings": _key_readings(scores, raw),
    }


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _composite(scores: dict, series_list: list, weights: list) -> float:
    vals = [scores[s]["score"] for s in series_list if s in scores]
    wts  = [weights[i] for i, s in enumerate(series_list) if s in scores]
    if not vals:
        return 50.0
    return round(sum(v * w for v, w in zip(vals, wts)) / sum(wts), 1)


def _ai_displacement(scores: dict) -> float:
    """AI Displacement — инвертираме: нисък temp help = повече AI displacement."""
    vals, wts = [], []
    for sid, w in zip(AI_SERIES, AI_WEIGHTS):
        if sid in scores:
            # TEMPHELPS: invert=True → score вече е инвертиран (ниско = лошо)
            # За AI displacement: ниско temphelps → висок AI displacement score
            raw_score = scores[sid]["score"]
            ai_score = 100 - raw_score if sid == "TEMPHELPS" else raw_score
            vals.append(ai_score)
            wts.append(w)
    if not vals:
        return 50.0
    return round(sum(v * w for v, w in zip(vals, wts)) / sum(wts), 1)


def _fear_index(scores: dict) -> float:
    """Fear = висок unemployment + много claims + много layoffs = Fear близо до 100."""
    vals, wts = [], []
    for sid, w in zip(FEAR_SERIES, FEAR_WEIGHTS):
        if sid in scores:
            # Инвертираме обратно: по-висока безработица → по-висок Fear
            pct = scores[sid]["percentile"]
            vals.append(pct)
            wts.append(w)
    if not vals:
        return 50.0
    return round(sum(v * w for v, w in zip(vals, wts)) / sum(wts), 1)


def _get_regime(score: float) -> tuple:
    for threshold, label, color in REGIMES:
        if score >= threshold:
            return label, color
    return "STRESSED", "#d50000"


def _key_readings(scores: dict, raw: dict) -> list:
    """Топ показания за display в dashboard."""
    result = []
    for sid in ["UNRATE", "ICSA", "PAYEMS", "JTSJOL", "JTSQUR", "JTSLDL"]:
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
