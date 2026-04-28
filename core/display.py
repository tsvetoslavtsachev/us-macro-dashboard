"""
core/display.py
================
Display-by-type — единен източник за това КАК да се покаже промяна на серия.

% change няма смисъл за rate-level и signed-index серии (BREAKEVEN, UST, OAS,
NFCI, CFNAI). За тях показваме basis points (рейтове) или абсолютна делта
(signed индекси). За останалите (CPI, payrolls и др.) — % както е стандарт.

Decision-а е по `peer_group` + специфичен sid override от каталога.

Public API:
    change_kind(sid, meta) -> "percent" | "bps" | "absolute"
    compute_change(series, kind, periods) -> pd.Series
    fmt_change(value, kind) -> str
    period_label(periods, short) -> "1г" | "1м" | "1д" | "1кв"
"""
from __future__ import annotations

import math
from typing import Optional

import pandas as pd


# ============================================================
# CLASSIFICATION
# ============================================================

# Peer groups със стойности в rate units (%, около 0-10) — Δ в bps
BPS_PEER_GROUPS = {
    "expectations",       # BREAKEVEN_5Y5Y, BREAKEVEN_10Y, MICH_INFL_1Y
    "term_structure",     # UST_2Y, UST_10Y, YC_*
    "credit_spreads",     # HY_OAS, IG_OAS
    "policy_rates",       # FED_FUNDS, SOFR
    "unemployment",       # UNRATE, U6RATE, EMRATIO, CIVPART, UEMPMEAN
    "labor_share",        # COMP_GDP_SHARE, LABOR_SHARE_NBS
}

# Peer groups със signed индекси (около 0) или 0-100 sentiment — абсолютна Δ
ABS_PEER_GROUPS = {
    "financial_conditions",   # NFCI, STLFSI
    "business_sentiment",     # PHILLY_FED, CFNAI, CFNAIMA3
    "consumer_sentiment",     # UMCSENT (0-100 индекс)
}

# Серии-override: yield curves живеят в "leading" peer_group но са rates
BPS_SIDS_OVERRIDE = {"T10Y3M", "T10Y2Y", "YC_10Y3M", "YC_10Y2Y"}


def change_kind(sid: str, meta: dict) -> str:
    """Връща 'percent' | 'bps' | 'absolute' за дадена серия."""
    if sid in BPS_SIDS_OVERRIDE:
        return "bps"
    pg = meta.get("peer_group", "")
    if pg in BPS_PEER_GROUPS:
        return "bps"
    if pg in ABS_PEER_GROUPS:
        return "absolute"
    return "percent"


# ============================================================
# CHANGE COMPUTATION
# ============================================================

def compute_change(series: pd.Series, kind: str, periods: int) -> pd.Series:
    """Изчислява промяна за дадена серия и kind.

    - "percent":  pct_change(periods) * 100  (вече в %, 10.0 = 10%)
    - "bps":      diff(periods) * 100         (1.0 pp = 100 bps)
    - "absolute": diff(periods)               (raw delta)
    """
    s = series.dropna()
    if s.empty or periods <= 0:
        return pd.Series(dtype=float, index=series.index)
    if kind == "percent":
        return s.pct_change(periods=periods) * 100
    if kind == "bps":
        return s.diff(periods=periods) * 100
    # absolute
    return s.diff(periods=periods)


# ============================================================
# FORMATTING
# ============================================================

def _is_finite_number(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def fmt_change(value, kind: str) -> str:
    """Форматира промяна в правилните units. Връща '—' за NaN/None."""
    f = _is_finite_number(value)
    if f is None:
        return "—"
    if kind == "percent":
        return f"{f:+.2f}%"
    if kind == "bps":
        return f"{f:+.0f} bps"
    return f"{f:+.2f}"


def fmt_value(value, digits: int = 3) -> str:
    """Форматира raw стойност на серия (без знак)."""
    f = _is_finite_number(value)
    if f is None:
        return "—"
    return f"{f:.{digits}f}"


# ============================================================
# PERIOD LABELS
# ============================================================

def short_period_label(yoy_periods: int) -> str:
    """Bulgarian abbreviation за short delta period (1d/1w/1m/1q)."""
    return {252: "1д", 52: "1с", 12: "1м", 4: "1кв"}.get(yoy_periods, "1м")


def long_period_label(yoy_periods: int = 0) -> str:
    """Long delta винаги е 1 година."""
    return "1г"


def change_header(kind: str, period_lbl: str) -> str:
    """Header за колона с промяна (напр. 'Δ1г bps', '1м %', 'Δ1д')."""
    if kind == "percent":
        return f"{period_lbl} %"
    if kind == "bps":
        return f"Δ{period_lbl} bps"
    return f"Δ{period_lbl}"
