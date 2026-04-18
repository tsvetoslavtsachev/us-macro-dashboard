"""
analysis/guardrails.py
======================
Два компонента:

1. Regime Falsification criteria
   За всеки идентифициран regime, какво би го обезсилило.
   Статичен mapping от regime_label → list[str].
   Целта е дисциплина: какво трябва да се случи,
   за да знаем, че диагнозата е грешна.

2. Threshold Flags
   Стойности от snapshot-а, които превишават предефинирани прагове:
     - yield curve inversion (T10Y2Y, T10Y3M < 0)
     - HY credit stress (HY_OAS > 5% / 7%)
     - Sahm rule (3m avg UNRATE vs 12m low > 0.5pp)
     - Initial claims spike (ICSA > 300K)

Без LLM — чисти threshold checks, lightweight и deterministic.

Dependencies:
  - pandas (за series обработка при Sahm rule)
  - catalog.series — за series metadata (label_bg в флаговете)
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import pandas as pd


# ============================================================
# FALSIFICATION CRITERIA
# ============================================================

FALSIFIERS_BY_REGIME: dict[str, list[str]] = {
    "stagflation_confirmed": [
        "Headline CPI YoY < 3% за 2 последователни месеца",
        "Wage breadth (wage_dynamics) спада под 0.4",
        "Core measures ↓ while headline ↑ (base effects)",
    ],
    "soft_landing": [
        "HY OAS се разширява над 500bps",
        "Initial claims > 275K седмично, 3 последователни седмици",
        "Wage breadth > 0.75 (re-acceleration)",
    ],
    "disinflation_cooling": [
        "Headline или core CPI YoY се връща нагоре 2 последователни прints",
        "Wage dynamics breadth > 0.65",
        "Sticky CPI спира спада (mom ≈ 0)",
    ],
    "policy_dilemma": [
        "Labor tightens — claims спадат под 230K",
        "Inflation cools 2 последователни прints под предишно ниво",
        "Expectations de-anchor (T5YIFR > 2.75%)",
    ],
    "expansion": [
        "Initial claims > 275K седмично",
        "ISM/Philly Fed activity diffusion < 45",
        "T10Y2Y инвертира под 0 за 1 месец",
    ],
    "slowdown": [
        "Initial claims < 225K (стабилизиране)",
        "Activity indicators reverse: ISM/Philly > 50 за 2 месеца",
        "Labor breadth > 0.65",
    ],
    "credit_stress": [
        "HY OAS се връща под 400bps",
        "Financial conditions (NFCI) labeled easy",
        "Banking credit расте mom (C&I loans, consumer)",
    ],
    "transition": [
        "Няма активна диагноза — чакаме следващи 2-3 macro прints",
        "Ако цели домейни заеми ясна посока (breadth > 0.65 или < 0.35), режимът ще се появи",
    ],
}


def get_falsifiers(regime_key: str) -> list[str]:
    """Връща falsification criteria за даден regime. Празен списък при unknown."""
    return list(FALSIFIERS_BY_REGIME.get(regime_key, []))


# ============================================================
# THRESHOLD FLAGS
# ============================================================

SEVERITY_RED = "red"
SEVERITY_AMBER = "amber"


@dataclass
class ThresholdFlag:
    key: str                    # stable identifier (e.g. "yield_curve_10y2y")
    label_bg: str               # human label
    series_key: str             # каталожен ключ (за линкване в briefing)
    value: float
    threshold: float
    severity: str               # "red" | "amber"
    message_bg: str             # кратко обяснение
    last_date: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def compute_threshold_flags(
    snapshot: dict[str, pd.Series],
) -> list[ThresholdFlag]:
    """Изчислява всички активни threshold flags от snapshot-а.

    Missing серии просто се пропускат.
    """
    flags: list[ThresholdFlag] = []

    # ─── 1. Yield curve inversion (T10Y2Y) ───
    flag = _check_yield_curve(snapshot, "YC_10Y2Y", "10Y-2Y")
    if flag:
        flags.append(flag)

    # ─── 2. Yield curve inversion (T10Y3M) ───
    flag = _check_yield_curve(snapshot, "YC_10Y3M", "10Y-3M")
    if flag:
        flags.append(flag)

    # ─── 3. HY OAS credit stress ───
    flag = _check_hy_oas(snapshot)
    if flag:
        flags.append(flag)

    # ─── 4. Sahm rule ───
    flag = _check_sahm_rule(snapshot)
    if flag:
        flags.append(flag)

    # ─── 5. Initial claims spike ───
    flag = _check_claims_spike(snapshot)
    if flag:
        flags.append(flag)

    return flags


# ============================================================
# INTERNAL CHECKS
# ============================================================

def _check_yield_curve(
    snapshot: dict[str, pd.Series],
    key: str,
    pretty_label: str,
) -> Optional[ThresholdFlag]:
    s = snapshot.get(key)
    if s is None:
        return None
    clean = s.dropna()
    if clean.empty:
        return None
    val = float(clean.iloc[-1])
    if val >= 0:
        return None
    last_date = _iso_date(clean.index[-1])
    return ThresholdFlag(
        key=f"yield_curve_{key.lower()}",
        label_bg=f"Yield curve {pretty_label}",
        series_key=key,
        value=round(val, 3),
        threshold=0.0,
        severity=SEVERITY_RED,
        message_bg=f"Yield curve {pretty_label} е инвертирана: {val:+.2f}pp. "
                   f"Исторически — водещ recession сигнал.",
        last_date=last_date,
    )


def _check_hy_oas(snapshot: dict[str, pd.Series]) -> Optional[ThresholdFlag]:
    s = snapshot.get("HY_OAS")
    if s is None:
        return None
    clean = s.dropna()
    if clean.empty:
        return None
    val = float(clean.iloc[-1])
    last_date = _iso_date(clean.index[-1])

    if val >= 7.0:
        return ThresholdFlag(
            key="hy_oas_stress_red",
            label_bg="HY OAS (credit stress)",
            series_key="HY_OAS",
            value=round(val, 2),
            threshold=7.0,
            severity=SEVERITY_RED,
            message_bg=f"HY OAS е на {val:.1f}% — acute credit stress (> 700bps).",
            last_date=last_date,
        )
    if val >= 5.0:
        return ThresholdFlag(
            key="hy_oas_stress_amber",
            label_bg="HY OAS (credit stress)",
            series_key="HY_OAS",
            value=round(val, 2),
            threshold=5.0,
            severity=SEVERITY_AMBER,
            message_bg=f"HY OAS е на {val:.1f}% — елевиран credit stress (> 500bps).",
            last_date=last_date,
        )
    return None


def _check_sahm_rule(snapshot: dict[str, pd.Series]) -> Optional[ThresholdFlag]:
    """Sahm rule: 3-month avg UNRATE - min(12-month UNRATE) > 0.5pp → recession."""
    s = snapshot.get("UNRATE")
    if s is None:
        return None
    clean = s.dropna()
    if len(clean) < 12:
        return None

    # Последните 3 месеца
    last_3m_avg = float(clean.iloc[-3:].mean())
    # Min за последните 12 месеца
    min_12m = float(clean.iloc[-12:].min())
    diff = last_3m_avg - min_12m

    if diff >= 0.5:
        last_date = _iso_date(clean.index[-1])
        return ThresholdFlag(
            key="sahm_rule",
            label_bg="Sahm rule",
            series_key="UNRATE",
            value=round(diff, 2),
            threshold=0.5,
            severity=SEVERITY_RED,
            message_bg=f"Sahm rule активен: 3m-avg UNRATE ({last_3m_avg:.1f}) е "
                       f"{diff:+.2f}pp над 12m-min ({min_12m:.1f}). "
                       f"Исторически 100% recession hit rate.",
            last_date=last_date,
        )
    if diff >= 0.3:
        last_date = _iso_date(clean.index[-1])
        return ThresholdFlag(
            key="sahm_rule_approaching",
            label_bg="Sahm rule (наближава)",
            series_key="UNRATE",
            value=round(diff, 2),
            threshold=0.3,
            severity=SEVERITY_AMBER,
            message_bg=f"Sahm indicator на {diff:+.2f}pp — близо до 0.5 recession trigger.",
            last_date=last_date,
        )
    return None


def _check_claims_spike(snapshot: dict[str, pd.Series]) -> Optional[ThresholdFlag]:
    """Initial claims > 300K = stressed; > 275K = watchlist."""
    s = snapshot.get("ICSA")
    if s is None:
        return None
    clean = s.dropna()
    if clean.empty:
        return None
    val = float(clean.iloc[-1])
    last_date = _iso_date(clean.index[-1])

    # ICSA е в хиляди
    if val >= 300:
        return ThresholdFlag(
            key="claims_spike_red",
            label_bg="Initial jobless claims",
            series_key="ICSA",
            value=round(val, 0),
            threshold=300,
            severity=SEVERITY_RED,
            message_bg=f"Initial claims са {val:.0f}K — stressed level (> 300K).",
            last_date=last_date,
        )
    if val >= 275:
        return ThresholdFlag(
            key="claims_spike_amber",
            label_bg="Initial jobless claims",
            series_key="ICSA",
            value=round(val, 0),
            threshold=275,
            severity=SEVERITY_AMBER,
            message_bg=f"Initial claims са {val:.0f}K — над watch threshold (275K).",
            last_date=last_date,
        )
    return None


def _iso_date(idx) -> Optional[str]:
    if isinstance(idx, pd.Timestamp):
        return idx.strftime("%Y-%m-%d")
    return None
