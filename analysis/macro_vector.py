"""
analysis/macro_vector.py
========================
8-dimensional macro state vector за historical analog engine (Phase 4).

Дименсии (8):
  1. unrate          — UNRATE level (%)
  2. core_cpi_yoy    — CPILFESL YoY (%)
  3. real_ffr        — DFF monthly avg − core CPI YoY (%)
  4. yc_10y2y        — T10Y2Y level (bps as %); fallback = DGS10 − DGS2
  5. hy_oas          — BAMLH0A0HYM2 level (%); fallback pre-1996 = BAA − DGS10, rescaled
  6. ip_yoy          — INDPRO YoY (%)
  7. breakeven       — T10YIE level (%); fallback pre-2003 = MICH, rescaled
  8. sahm            — Sahm rule (3mma UNRATE − min trailing 12m 3mma) (pp)

Window: 1976-01-01 → сега. Това покрива 1970s stagflation, Volcker, 80s
disinflation, dotcom, GFC, 2020 COVID, 2022-23 inflation shock — всички
regime-defining епизоди от последните 50 години.

Proxy calibration (за hy_oas и breakeven):
  На overlap периода (когато и двете серии имат данни) изчисляваме
  mean/std и на двете, след това rescale-ваме proxy-a към scale-а на
  primary: proxy_rescaled = proxy × (σ_primary/σ_proxy) + (μ_primary − μ_proxy·σ_primary/σ_proxy).
  Резултатът: няма level discontinuity при splice date, z-score-ът
  е коректен full-sample.

  **Caveat:** Michigan 1Y survey и T10YIE 10Y breakeven мерят РАЗЛИЧНИ
  неща (retail survey vs market pricing, 1Y vs 10Y horizon). Rescaling
  изравнява средната и волатилността, но не ZMZ корелацията. Това е
  документиран MVP компромис — за analog matching формата на движение
  е по-важна от absolute level.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


# ============================================================
# STATE VECTOR DEFINITION
# ============================================================

ANALOG_WINDOW_START = "1976-01-01"

# Всички FRED IDs, които analog engine ползва (включително proxy-тата)
# Ключовете тук са вътрешните имена за fetch — не се пресичат с каталога
# (вместо "UNRATE" ползваме "ANALOG_UNRATE" за да не пренапишем catalog cache
# entry-та с евентуално различни transform-и в бъдеще).
ANALOG_FETCH_SPEC: list[dict] = [
    # Primary series
    {"key": "ANALOG_UNRATE",       "fred_id": "UNRATE",        "schedule": "monthly"},
    {"key": "ANALOG_CORE_CPI",     "fred_id": "CPILFESL",      "schedule": "monthly"},
    {"key": "ANALOG_DFF",          "fred_id": "DFF",           "schedule": "weekly"},
    {"key": "ANALOG_T10Y2Y",       "fred_id": "T10Y2Y",        "schedule": "weekly"},
    {"key": "ANALOG_HY_OAS",       "fred_id": "BAMLH0A0HYM2",  "schedule": "weekly"},
    {"key": "ANALOG_INDPRO",       "fred_id": "INDPRO",        "schedule": "monthly"},
    {"key": "ANALOG_T10YIE",       "fred_id": "T10YIE",        "schedule": "weekly"},
    # Proxies & curve building blocks
    {"key": "ANALOG_DGS10",        "fred_id": "DGS10",         "schedule": "weekly"},
    {"key": "ANALOG_DGS2",         "fred_id": "DGS2",          "schedule": "weekly"},
    {"key": "ANALOG_BAA",          "fred_id": "BAA",           "schedule": "monthly"},
    {"key": "ANALOG_MICH",         "fred_id": "MICH",          "schedule": "monthly"},
]


# Proxy splice dates — от кога primary series става достъпна
HY_OAS_START = "1996-12-01"
BREAKEVEN_START = "2003-01-01"


STATE_VECTOR_DIMS: list[str] = [
    "unrate",
    "core_cpi_yoy",
    "real_ffr",
    "yc_10y2y",
    "hy_oas",
    "ip_yoy",
    "breakeven",
    "sahm",
]


DIM_LABELS_BG: dict[str, str] = {
    "unrate":       "Безработица",
    "core_cpi_yoy": "Core CPI YoY",
    "real_ffr":     "Реален Fed Funds",
    "yc_10y2y":     "Крива 10Y-2Y",
    "hy_oas":       "HY spread",
    "ip_yoy":       "Industrial prod YoY",
    "breakeven":    "Инфл. очаквания",
    "sahm":         "Sahm rule",
}


DIM_UNITS: dict[str, str] = {
    "unrate":       "%",
    "core_cpi_yoy": "%",
    "real_ffr":     "%",
    "yc_10y2y":     "pp",
    "hy_oas":       "%",
    "ip_yoy":       "%",
    "breakeven":    "%",
    "sahm":         "pp",
}


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class MacroState:
    """Macro state в даден момент: raw values + z-scored."""
    as_of: pd.Timestamp
    raw: dict[str, float]       # {dim: raw value in native units}
    z: dict[str, float]         # {dim: z-score full-sample}

    def as_array(self) -> np.ndarray:
        """Върне z-scored vector като np.ndarray в STATE_VECTOR_DIMS ред."""
        return np.array([self.z[d] for d in STATE_VECTOR_DIMS], dtype=float)


# ============================================================
# TRANSFORM PRIMITIVES
# ============================================================

def _to_month_end(s: pd.Series) -> pd.Series:
    """Resample-ва серия на month-end (последно наблюдение в месеца).

    DFF/T10Y2Y/DGS10 и т.н. са daily; ползваме последната налична стойност
    на месеца (end-of-month convention). Monthly серии остават същите.
    """
    s = s.dropna()
    if s.empty:
        return s
    return s.resample("ME").last().dropna()


def _yoy_pct(s: pd.Series) -> pd.Series:
    """12-month % change на monthly серия."""
    return (s / s.shift(12) - 1.0) * 100.0


def _compute_sahm_rule(unrate_monthly: pd.Series) -> pd.Series:
    """Sahm Rule Recession Indicator (реална дефиниция):

        SR = 3mma(UNRATE) − min(3mma(UNRATE)) за trailing 12 месеца

    При SR ≥ 0.5 pp историческо recession signal.
    """
    sma3 = unrate_monthly.rolling(3).mean()
    trailing_min = sma3.rolling(12).min()
    return sma3 - trailing_min


# ============================================================
# PROXY CALIBRATION
# ============================================================

def _calibrate_proxy(
    primary: pd.Series,
    proxy: pd.Series,
    splice_date: str,
) -> pd.Series:
    """Съединява proxy (преди splice_date) и primary (от splice_date нататък),
    rescaled върху overlap периода.

    Резултат: единна серия без level discontinuity при splice_date.

    Ако няма overlap (proxy свършва преди splice_date) — raise.
    """
    overlap_primary = primary.loc[splice_date:].dropna()
    overlap_proxy = proxy.loc[splice_date:].dropna()

    common_idx = overlap_primary.index.intersection(overlap_proxy.index)
    if len(common_idx) < 12:
        # fallback: без rescale, просто concat (по-малко прецизно)
        proxy_rescaled = proxy.copy()
    else:
        p1 = overlap_primary.loc[common_idx]
        p2 = overlap_proxy.loc[common_idx]
        mu1, sig1 = p1.mean(), p1.std(ddof=0)
        mu2, sig2 = p2.mean(), p2.std(ddof=0)
        if sig2 == 0 or np.isnan(sig2):
            proxy_rescaled = proxy.copy()
        else:
            scale = sig1 / sig2
            shift = mu1 - mu2 * scale
            proxy_rescaled = proxy * scale + shift

    before = proxy_rescaled.loc[:splice_date]
    # strict "<" на splice_date за да не получим дублиране
    before = before.loc[before.index < pd.Timestamp(splice_date)]
    after = primary.loc[splice_date:]
    return pd.concat([before, after]).sort_index()


# ============================================================
# HISTORY MATRIX BUILDER
# ============================================================

def build_history_matrix(
    fetched: dict[str, pd.Series],
    start: str = ANALOG_WINDOW_START,
) -> pd.DataFrame:
    """Построява monthly history matrix 8-dim от raw FRED серии.

    Args:
        fetched: dict {ANALOG_KEY: pd.Series} както върна adapter.fetch_many.
                 Очаквани ключове: виж ANALOG_FETCH_SPEC.
        start:   Начална дата за analog window (default 1976-01-01).

    Returns:
        DataFrame индексирана по month-end, колони = STATE_VECTOR_DIMS.
        NaN редове са оставени — `.dropna()` от caller ако иска complete cases.
    """
    # 1. Resample всичко на month-end
    m = {k: _to_month_end(v) for k, v in fetched.items()}

    # 2. Dim 1 — UNRATE level
    unrate = m.get("ANALOG_UNRATE", pd.Series(dtype=float))

    # 3. Dim 2 — core CPI YoY
    core_cpi = m.get("ANALOG_CORE_CPI", pd.Series(dtype=float))
    core_cpi_yoy = _yoy_pct(core_cpi) if not core_cpi.empty else pd.Series(dtype=float)

    # 4. Dim 3 — real Fed Funds (DFF monthly avg − core CPI YoY)
    dff = m.get("ANALOG_DFF", pd.Series(dtype=float))
    real_ffr = (dff - core_cpi_yoy).dropna()

    # 5. Dim 4 — 10Y-2Y; ако T10Y2Y липсва, computed от DGS10 − DGS2
    yc = m.get("ANALOG_T10Y2Y", pd.Series(dtype=float))
    if yc.empty:
        dgs10 = m.get("ANALOG_DGS10", pd.Series(dtype=float))
        dgs2 = m.get("ANALOG_DGS2", pd.Series(dtype=float))
        yc = (dgs10 - dgs2).dropna()

    # 6. Dim 5 — HY OAS с BAA − DGS10 proxy pre-1996-12
    hy = m.get("ANALOG_HY_OAS", pd.Series(dtype=float))
    baa = m.get("ANALOG_BAA", pd.Series(dtype=float))
    dgs10 = m.get("ANALOG_DGS10", pd.Series(dtype=float))
    baa_spread = (baa - dgs10).dropna() if not baa.empty else pd.Series(dtype=float)

    if not hy.empty and not baa_spread.empty:
        hy_composite = _calibrate_proxy(hy, baa_spread, HY_OAS_START)
    elif not hy.empty:
        hy_composite = hy
    elif not baa_spread.empty:
        hy_composite = baa_spread
    else:
        hy_composite = pd.Series(dtype=float)

    # 7. Dim 6 — INDPRO YoY
    indpro = m.get("ANALOG_INDPRO", pd.Series(dtype=float))
    ip_yoy = _yoy_pct(indpro) if not indpro.empty else pd.Series(dtype=float)

    # 8. Dim 7 — Breakeven 10Y с MICH proxy pre-2003-01
    be = m.get("ANALOG_T10YIE", pd.Series(dtype=float))
    mich = m.get("ANALOG_MICH", pd.Series(dtype=float))
    if not be.empty and not mich.empty:
        breakeven = _calibrate_proxy(be, mich, BREAKEVEN_START)
    elif not be.empty:
        breakeven = be
    elif not mich.empty:
        breakeven = mich
    else:
        breakeven = pd.Series(dtype=float)

    # 9. Dim 8 — SAHM rule от UNRATE
    sahm = _compute_sahm_rule(unrate) if not unrate.empty else pd.Series(dtype=float)

    # 10. Merge
    df = pd.concat(
        {
            "unrate": unrate,
            "core_cpi_yoy": core_cpi_yoy,
            "real_ffr": real_ffr,
            "yc_10y2y": yc,
            "hy_oas": hy_composite,
            "ip_yoy": ip_yoy,
            "breakeven": breakeven,
            "sahm": sahm,
        },
        axis=1,
    )

    # 11. Filter към window
    df = df.loc[pd.Timestamp(start):].copy()
    df = df.sort_index()

    # 12. Column order
    df = df[STATE_VECTOR_DIMS]

    return df


# ============================================================
# Z-SCORING
# ============================================================

def z_score_matrix(history_df: pd.DataFrame) -> pd.DataFrame:
    """Full-sample z-score на всяка колона.

    Args:
        history_df: output от build_history_matrix.

    Returns:
        DataFrame със същия shape. Колона с константна стойност → 0.0.
        NaN-ите в входа остават NaN.
    """
    out = pd.DataFrame(index=history_df.index, columns=history_df.columns, dtype=float)
    for col in history_df.columns:
        s = history_df[col].dropna()
        if s.empty:
            out[col] = np.nan
            continue
        mu = s.mean()
        sigma = s.std(ddof=0)
        if sigma == 0 or np.isnan(sigma):
            out[col] = 0.0
            out.loc[history_df[col].isna(), col] = np.nan
            continue
        out[col] = (history_df[col] - mu) / sigma
    return out


# ============================================================
# CURRENT VECTOR
# ============================================================

def build_current_vector(
    history_df: pd.DataFrame,
    history_z: pd.DataFrame,
    today: Optional[pd.Timestamp] = None,
) -> Optional[MacroState]:
    """Текущият macro state — последният complete-case ред в history_z.

    Args:
        history_df: raw matrix от build_history_matrix.
        history_z: z-scored matrix от z_score_matrix.
        today: ако е зададен, търсим последния ред ≤ today; иначе последния
               ред в индекса. Полезно при smoke-тест на фиксирана дата.

    Returns:
        MacroState или None ако няма complete-case ред.
    """
    z = history_z.dropna()
    # Ако z е празен (empty history) индексът не е DatetimeIndex и
    # сравнението ≤ Timestamp крашва. Guard-ваме преди filter-а.
    if z.empty:
        return None
    if today is not None:
        z = z.loc[z.index <= pd.Timestamp(today)]
    if z.empty:
        return None

    as_of = z.index[-1]
    z_row = z.iloc[-1]
    raw_row = history_df.loc[as_of]

    return MacroState(
        as_of=as_of,
        raw={d: float(raw_row[d]) for d in STATE_VECTOR_DIMS},
        z={d: float(z_row[d]) for d in STATE_VECTOR_DIMS},
    )
