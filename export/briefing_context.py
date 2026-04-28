"""
export/briefing_context.py
===========================
Генерира Claude-friendly briefing context като Markdown.

Целта: единичен .md файл с пълния analytical state, който можеш да
attach-неш към Claude чат и да питаш дълбоки въпроси за всяка серия.

Phase 1 sections:
  1. Header (дата, regime, composite scores)
  2. Executive Summary (theme breadth × посока × аномалии)
  3. Theme blocks (4 теми × peer groups breadth tables)
  4. Cross-Lens Divergence (6 двойки с state + интерпретация + slot details)
  5. Top Anomalies (fact cards с 5-годишен context)
  6. Methodology compact

Usage:
  from export.briefing_context import generate_briefing_context
  generate_briefing_context(
      snapshot, lens_reports, cross_report, anomaly_report,
      today, output_path,
  )

Output: output/briefing_context_YYYY-MM-DD.md
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import math
import numpy as np
import pandas as pd

from catalog.series import SERIES_CATALOG
from catalog.cross_lens_pairs import CROSS_LENS_PAIRS
from core.display import (
    change_kind,
    compute_change,
    fmt_change,
    fmt_value,
)
from core.primitives import _infer_yoy_periods


# ============================================================
# CONFIG
# ============================================================

HISTORY_YEARS = 5             # window за percentile rank + range stats
FACT_CARD_TAIL = 6            # последни N readings в fact card
LENS_ORDER = ["labor", "growth", "inflation", "liquidity"]

# ─── STALENESS (D1) — period-aware staleness assessment ────
# За всеки release_schedule имаме:
#   period_length: колко дни обхваща един отчетен период
#     (FRED labelirua quarterly данни към първата дата на периода;
#      реалните данни покриват целия период)
#   typical_release_lag: типичен брой дни от край-на-период до публикация
PERIOD_LENGTH_DAYS = {
    "daily":     1,
    "weekly":    7,
    "monthly":   30,
    "quarterly": 90,
    "annually":  365,
}
TYPICAL_RELEASE_LAG_DAYS = {
    "daily":     1,
    "weekly":    5,
    "monthly":   30,
    "quarterly": 35,
    "annually":  90,
}

# ─── ANCHORED ZONES (A4) — Fed-quoted normal range за inflation expectations
# Базирани на post-Volcker / pre-2022 era (anchored regime)
ANCHORED_ZONES = {
    "BREAKEVEN_5Y5Y": (1.8, 2.5),    # forward inflation, Fed target ±band
    "BREAKEVEN_10Y":  (1.7, 2.6),    # 10y breakeven, similar
    "MICH_INFL_1Y":   (2.5, 3.5),    # Michigan 1y, household upward bias
}

# ─── NOMINAL SERIES (B3) — изискват deflation за real-volume claims
NOMINAL_SERIES_NEED_DEFLATION = {
    "RSXFS":          "Retail sales",
    "DGORDER":        "Durable goods orders",
    "C_AND_I_LOANS":  "Commercial & Industrial loans",
    "M2":             "M2 money supply",
    "AHE":            "Average hourly earnings",
    "ECIWAG":         "Employment Cost Index",
    "PCEC96":         "Real PCE (already deflated — flag if used)",
    "INDPRO":         "Industrial production index",
    "PAYEMS":         "Total payrolls (count, не nominal в обичайния смисъл)",
}
LENS_LABEL_BG = {
    "labor":     "Трудов пазар",
    "growth":    "Растеж",
    "inflation": "Инфлация",
    "liquidity": "Ликвидност и кредит",
}
DIRECTION_LABEL_BG = {
    "expanding":         "разширяване",
    "contracting":       "свиване",
    "mixed":             "смесено",
    "insufficient_data": "недостатъчно данни",
}
STATE_LABEL_BG = {
    "both_up":           "↑↑ и двете нагоре",
    "both_down":         "↓↓ и двете надолу",
    "a_up_b_down":       "↑↓ A нагоре / B надолу",
    "a_down_b_up":       "↓↑ A надолу / B нагоре",
    "transition":        "⇄ преход",
    "insufficient_data": "недостатъчно данни",
}


# ============================================================
# PUBLIC API
# ============================================================

def generate_briefing_context(
    snapshot: dict[str, pd.Series],
    lens_reports: dict,
    cross_report,
    anomaly_report,
    today: date,
    output_path: str | Path,
    history_years: int = HISTORY_YEARS,
) -> str:
    """Генерира Markdown context файл с пълен analytical state.

    Args:
        snapshot: {series_key: pd.Series}.
        lens_reports: {lens: LensBreadthReport}.
        cross_report: CrossLensReport (с .pairs).
        anomaly_report: AnomalyReport (с .top).
        today: дата за file name + header.
        output_path: директория за изход.
        history_years: window за percentile/range (default 5).

    Returns:
        Абсолютен path към записания .md файл.
    """
    sections: list[str] = []
    sections.append(_render_header(today, lens_reports, cross_report, anomaly_report))
    sections.append(_render_executive_summary(lens_reports, anomaly_report))
    sections.append(_render_cross_spreads(snapshot, today, history_years))
    sections.append(_render_themes(lens_reports, snapshot, history_years))
    sections.append(_render_cross_lens(cross_report, snapshot))
    sections.append(_render_anomalies(anomaly_report, snapshot, today, history_years))
    sections.append(_render_methodology_compact())

    body = "\n\n".join(sections)

    out_dir = Path(output_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"briefing_context_{today.isoformat()}.md"
    out_file.write_text(body, encoding="utf-8")
    return str(out_file.resolve())


# ============================================================
# COMPUTATIONAL HELPERS
# ============================================================

def _last_value(series: Optional[pd.Series]) -> Optional[float]:
    """Връща последната не-NaN стойност, или None."""
    if series is None or series.empty:
        return None
    s = series.dropna()
    if s.empty:
        return None
    return float(s.iloc[-1])


def _last_obs_date(series: Optional[pd.Series]) -> Optional[date]:
    """Връща датата на последното observation (date обект), или None."""
    if series is None or series.empty:
        return None
    s = series.dropna()
    if s.empty:
        return None
    last = s.index[-1]
    return last.date() if hasattr(last, "date") else None


def _yoy_pct(series: Optional[pd.Series], periods: Optional[int] = None) -> Optional[float]:
    """YoY % за последното observation.

    Ако periods е None — auto-infer (12 за monthly, 4 за quarterly, 252 за daily).
    Връща стойност в проценти (12.5 = 12.5%), или None ако данни недостатъчно.
    """
    if series is None or series.empty:
        return None
    s = series.dropna()
    if len(s) < 2:
        return None
    if periods is None:
        periods = _infer_yoy_periods(s)
    if len(s) <= periods:
        return None
    pct = s.pct_change(periods=periods) * 100
    last = pct.iloc[-1]
    if pd.isna(last):
        return None
    return float(last)


def _annualized_change(series: Optional[pd.Series], periods: int = 3) -> Optional[float]:
    """N-period change annualized to yearly rate (за monthly: periods=3 → 3m ann).

    За CPI/PPI/payrolls конвенцията е (1 + cumulative_n_period)^(12/n) − 1.
    Връща в проценти (12.5 = 12.5%).
    """
    if series is None or series.empty:
        return None
    s = series.dropna()
    if len(s) <= periods:
        return None
    cumulative = s.iloc[-1] / s.iloc[-1 - periods] - 1
    # Infer how many periods per year
    inferred = _infer_yoy_periods(s)
    if inferred <= 0:
        return None
    annualization_factor = inferred / periods
    annualized = (1 + cumulative) ** annualization_factor - 1
    return float(annualized * 100)


def _percentile_5y(series: Optional[pd.Series], history_years: int = 5) -> Optional[float]:
    """Percentile rank на последната стойност спрямо 5y window."""
    if series is None or series.empty:
        return None
    s = series.dropna().sort_index()
    if len(s) < 2:
        return None
    last_idx = s.index[-1]
    cutoff = last_idx - pd.DateOffset(years=history_years)
    s5y = s[s.index >= cutoff]
    if len(s5y) < 2:
        return None
    last_value = float(s5y.iloc[-1])
    return float((s5y < last_value).sum() / len(s5y) * 100)


def assess_staleness(
    last_obs: Optional[date],
    release_schedule: str,
    today: date,
) -> dict:
    """Период-aware staleness assessment.

    Логика:
      effective_data_end = last_obs + period_length
        (краят на периода, който данните вече покриват)
      this_release ≈ effective_data_end + typical_release_lag
        (когато е публикуван текущият last_obs — вече е минало)
      next_data_end = effective_data_end + period_length
        (края на следващия период, който очакваме следва)
      next_release = next_data_end + typical_release_lag
        (кога очакваме нов print)
      days_overdue = today - next_release

      level:
        - "fresh"    — days_overdue ≤ 0 (още в normalния cycle)
        - "warning"  — days_overdue > 2× typical_release_lag
        - "critical" — days_overdue > 4× typical_release_lag

    За тримесечни серии: FRED labelira с началото на тримесечието,
    но ние коригираме за реалния период (purpose: не false-flag-ваме
    Q4 2025 като stale ако днес сме преди очакван Q1 2026 release).
    """
    if last_obs is None:
        return {"level": "no_data", "days_overdue": 0, "explanation": "няма данни"}

    period_len = PERIOD_LENGTH_DAYS.get(release_schedule, 30)
    release_lag = TYPICAL_RELEASE_LAG_DAYS.get(release_schedule, 30)

    effective_data_end = last_obs + timedelta(days=period_len)
    this_release = effective_data_end + timedelta(days=release_lag)
    next_data_end = effective_data_end + timedelta(days=period_len)
    next_release = next_data_end + timedelta(days=release_lag)

    days_overdue = (today - next_release).days

    warning_thresh = release_lag * 2
    critical_thresh = release_lag * 4

    if days_overdue <= 0:
        level = "fresh"
    elif days_overdue > critical_thresh:
        level = "critical"
    elif days_overdue > warning_thresh:
        level = "warning"
    else:
        level = "fresh"

    # Generate explanation
    if release_schedule == "quarterly":
        q_num = (last_obs.month - 1) // 3 + 1
        q_year = last_obs.year
        next_q_num = q_num % 4 + 1
        next_q_year = q_year + 1 if q_num == 4 else q_year
        explanation = (
            f"FRED показва Q{q_num} {q_year} (label {last_obs.isoformat()} = "
            f"start-of-quarter; реално обхваща {effective_data_end.strftime('%b %Y').lower()}). "
            f"Q{q_num} {q_year} печатът беше публикуван около {this_release.isoformat()}. "
            f"Следващ печат Q{next_q_num} {next_q_year} се очаква около {next_release.isoformat()}."
        )
    elif level == "fresh":
        explanation = (
            f"в нормален release cycle (this print: {this_release.isoformat()}; "
            f"next: {next_release.isoformat()})"
        )
    else:
        explanation = (
            f"очакваният next release беше около {next_release.isoformat()}; "
            f"закъснение {days_overdue} дни"
        )

    return {
        "level": level,
        "effective_data_end": effective_data_end,
        "this_release": this_release,
        "next_release": next_release,
        "days_overdue": max(0, days_overdue),
        "explanation": explanation,
    }


def _staleness_marker(level: str) -> str:
    """Visual marker за staleness level."""
    return {
        "fresh":    "",
        "warning":  "⚠ ",
        "critical": "❌ ",
        "no_data":  "(няма данни) ",
    }.get(level, "")


# ============================================================
# SECTION RENDERERS
# ============================================================

def _render_header(today, lens_reports, cross_report, anomaly_report) -> str:
    lines = [
        f"# Briefing Context — {today.isoformat()}",
        "",
        "Машинно-генериран **дълбок** analytical snapshot за LLM анализ. "
        "Подава всичкото което briefing.html-ът показва, плюс per-series fact cards "
        f"с {HISTORY_YEARS}-годишен исторически контекст.",
        "",
        "**Как да го ползваш:** копирай съдържанието или закачи файла в Claude чат "
        "и питай дълбоки въпроси за серии, темите или текущите аномалии. "
        "Всичко е детерминистично, без LLM нарация — само изчислени стойности.",
        "",
        f"- **Дата на брифинга:** {today.isoformat()}",
        f"- **Брой теми:** {len(lens_reports)}",
        f"- **Cross-lens двойки:** {len(cross_report.pairs)}",
        f"- **Аномалии (|z|>2):** {anomaly_report.total_flagged} (top {len(anomaly_report.top)})",
    ]
    return "\n".join(lines)


def _render_executive_summary(lens_reports, anomaly_report) -> str:
    lines = ["## 1. Executive Summary", ""]
    lines.append("| Тема | Посока (general) | Breadth ↑ (avg) | Аномалии (|z|>2) |")
    lines.append("|---|---|---|---|")

    for lens in LENS_ORDER:
        rep = lens_reports.get(lens)
        if rep is None:
            continue
        # Aggregate breadth across peer groups
        breadths = [
            pg.breadth_positive for pg in rep.peer_groups
            if not (isinstance(pg.breadth_positive, float) and math.isnan(pg.breadth_positive))
        ]
        avg_breadth = (sum(breadths) / len(breadths)) if breadths else None
        avg_str = f"{avg_breadth*100:.0f}%" if avg_breadth is not None else "—"

        # Direction summary across peer groups
        dir_counts = {"expanding": 0, "contracting": 0, "mixed": 0, "insufficient_data": 0}
        for pg in rep.peer_groups:
            dir_counts[pg.direction] = dir_counts.get(pg.direction, 0) + 1
        if dir_counts["expanding"] > dir_counts["contracting"]:
            general = "разширяване"
        elif dir_counts["contracting"] > dir_counts["expanding"]:
            general = "свиване"
        else:
            general = "смесено"

        # Anomalies in this lens
        n_anom = len(anomaly_report.by_lens.get(lens, []))

        lines.append(
            f"| {LENS_LABEL_BG.get(lens, lens)} | {general} | {avg_str} | {n_anom} |"
        )
    return "\n".join(lines)


def _render_cross_spreads(snapshot, today: date, history_years: int) -> str:
    """Cross-spreads и реални нива — derived metrics за thesis-критични числа.

    Включва:
      - Реални нива (real wages, real Fed Funds forward, real M2, real volume)
      - Yield curve spreads (10Y-2Y, 10Y-3M в bps)
      - Inflation expectations gaps
      - Anchored band проверка (BE 5Y5Y, MICH срещу 2010-19 anchored zone)
      - PPI Core vs CPI Core lead-lag (3m annualized)

    Deflator: Core CPI YoY (CPILFESL) — Fed-preferred.
    Real Fed Funds: forward (FED_FUNDS − BREAKEVEN_5Y5Y).
    """
    parts = ["## 1.5 Cross-spreads и реални нива", ""]
    parts.append(
        "Производни числа за директно използване в теза. **Deflator: Core CPI** "
        "(CPILFESL YoY) — Fed-preferred. **Real Fed Funds: forward** "
        "(FED_FUNDS − BREAKEVEN_5Y5Y). Тези числа НЕ са в caталога — "
        "изчислени са тук от налични серии."
    )
    parts.append("")

    # ─── Get core CPI YoY for deflator ───
    core_cpi_yoy = _yoy_pct(snapshot.get("CPILFESL"))

    # ═══════════════════════════════════════
    # Реални нива
    # ═══════════════════════════════════════
    parts.append("### Реални нива")
    parts.append("")

    if core_cpi_yoy is None:
        parts.append("_Core CPI липсва — реалните нива не могат да се изчислят._")
        parts.append("")
    else:
        parts.append(f"_Core CPI (CPILFESL) YoY = **{core_cpi_yoy:+.2f}%** — използва се като deflator._")
        parts.append("")
        parts.append("| Метрика | Стойност | Интерпретация |")
        parts.append("|---|---|---|")

        # Real wages — ECIWAG (quarterly, periods=4)
        eci_yoy = _yoy_pct(snapshot.get("ECIWAG"), periods=4)
        if eci_yoy is not None:
            real = eci_yoy - core_cpi_yoy
            interp = (
                "workers winning" if real > 0.5 else
                "workers losing (real wages contracting)" if real < -0.3 else
                "essentially flat — реално workers не печелят, въпреки nominal ръст"
            )
            parts.append(f"| Real ECIWAG (Q-o-Q ann.) | {real:+.2f}% (nominal {eci_yoy:+.2f}% − core CPI {core_cpi_yoy:+.2f}%) | {interp} |")

        # Real wages — AHE (monthly)
        ahe_yoy = _yoy_pct(snapshot.get("AHE"))
        if ahe_yoy is not None:
            real = ahe_yoy - core_cpi_yoy
            interp = (
                "AHE winning" if real > 0.5 else
                "AHE losing" if real < -0.3 else
                "AHE flat real"
            )
            parts.append(f"| Real AHE (YoY) | {real:+.2f}% (nominal {ahe_yoy:+.2f}%) | {interp} |")

        # Real Fed Funds (forward — A2 decision)
        ff_now = _last_value(snapshot.get("FED_FUNDS"))
        be_5y5y = _last_value(snapshot.get("BREAKEVEN_5Y5Y"))
        if ff_now is not None and be_5y5y is not None:
            real_ff = ff_now - be_5y5y
            interp = (
                "**clearly restrictive**" if real_ff > 1.5 else
                "moderately restrictive" if real_ff > 0.5 else
                "near neutral" if real_ff > -0.5 else
                "stimulative"
            )
            parts.append(
                f"| **Real Fed Funds (forward)** | "
                f"{real_ff:+.2f}% ({real_ff*100:+.0f} bps) "
                f"= FFR {ff_now:.2f}% − BE5Y5Y {be_5y5y:.2f}% | {interp} |"
            )

        # Real M2 (с Core CPI)
        m2_yoy = _yoy_pct(snapshot.get("M2"))
        if m2_yoy is not None:
            real = m2_yoy - core_cpi_yoy
            interp = (
                "expansionary (excess liquidity, Friedman tradition)" if real > 2.0 else
                "modest expansion" if real > 0.5 else
                "neutral" if real > -0.5 else
                "contractionary"
            )
            parts.append(f"| Real M2 (YoY) | {real:+.2f}% (nominal M2 {m2_yoy:+.2f}%) | {interp} |")

        # Real RSXFS
        rsxfs_yoy = _yoy_pct(snapshot.get("RSXFS"))
        if rsxfs_yoy is not None:
            real = rsxfs_yoy - core_cpi_yoy
            interp = (
                "strong consumer (real volume growth)" if real > 2.0 else
                "modest real growth" if real > 0.3 else
                "near-flat — nominal NEW MAX е nominal illusion" if real > -0.5 else
                "real consumer pullback"
            )
            parts.append(f"| Real retail sales (YoY) | {real:+.2f}% (nominal {rsxfs_yoy:+.2f}%) | {interp} |")

        # Real C&I loans
        cni_yoy = _yoy_pct(snapshot.get("C_AND_I_LOANS"))
        if cni_yoy is not None:
            real = cni_yoy - core_cpi_yoy
            interp = (
                "real credit expansion" if real > 1.0 else
                "neutral credit" if real > -0.5 else
                "real contraction"
            )
            parts.append(f"| Real C&I loans (YoY) | {real:+.2f}% (nominal {cni_yoy:+.2f}%) | {interp} |")

        parts.append("")

    # ═══════════════════════════════════════
    # Yield curve
    # ═══════════════════════════════════════
    parts.append("### Yield curve")
    parts.append("")

    yc_10y2y = _last_value(snapshot.get("YC_10Y2Y"))
    yc_10y3m = _last_value(snapshot.get("YC_10Y3M"))
    ust_10y = _last_value(snapshot.get("UST_10Y"))
    ust_2y = _last_value(snapshot.get("UST_2Y"))

    has_curve = yc_10y2y is not None or yc_10y3m is not None or (ust_10y is not None and ust_2y is not None)
    if not has_curve:
        parts.append("_Yield curve серии липсват._")
    else:
        parts.append("| Spread | Стойност | Интерпретация |")
        parts.append("|---|---|---|")

        # 10Y-2Y
        if yc_10y2y is not None:
            bps = yc_10y2y * 100
            interp = (
                "**inverted** — recession 6-18m напред в 80% от случаите" if yc_10y2y < 0 else
                "flat (late-cycle / pre-recession)" if yc_10y2y < 0.5 else
                "normal slope" if yc_10y2y < 1.5 else
                "steep (early-cycle / re-acceleration)"
            )
            parts.append(f"| 10Y-2Y (YC_10Y2Y) | {bps:+.0f} bps | {interp} |")
        elif ust_10y is not None and ust_2y is not None:
            spread = (ust_10y - ust_2y) * 100
            parts.append(f"| 10Y-2Y (computed) | {spread:+.0f} bps | (от UST_10Y − UST_2Y) |")

        # 10Y-3M (NY Fed классическият recession signal)
        if yc_10y3m is not None:
            bps = yc_10y3m * 100
            interp = (
                "**inverted** — NY Fed класически recession signal (6-18m напред)" if yc_10y3m < 0 else
                "flat" if yc_10y3m < 0.5 else
                "normal"
            )
            parts.append(f"| 10Y-3M (YC_10Y3M) | {bps:+.0f} bps | {interp} |")

        parts.append("")

    # ═══════════════════════════════════════
    # Inflation expectations gaps
    # ═══════════════════════════════════════
    parts.append("### Inflation expectations — gaps & anchoring")
    parts.append("")

    be_10y = _last_value(snapshot.get("BREAKEVEN_10Y"))
    mich_1y = _last_value(snapshot.get("MICH_INFL_1Y"))

    parts.append("| Метрика | Стойност | Интерпретация |")
    parts.append("|---|---|---|")

    if be_10y is not None and be_5y5y is not None:
        gap = (be_10y - be_5y5y) * 100  # bps
        interp = (
            "near-term inflation **по-висока** от forward (front-end pressure)" if gap > 15 else
            "term structure relatively flat" if abs(gap) <= 15 else
            "near-term **по-ниска** (disinflation очаквания near-term)"
        )
        parts.append(f"| BE 10Y − BE 5Y5Y | {gap:+.0f} bps | {interp} |")

    if mich_1y is not None and be_10y is not None:
        gap = (mich_1y - be_10y) * 100  # bps
        interp = (
            "households виждат inflation **значително над** market" if gap > 75 else
            "households малко над market (typical bias)" if gap > 25 else
            "in line" if abs(gap) <= 25 else
            "households **под** market (rare)"
        )
        parts.append(f"| Michigan 1Y − BE 10Y | {gap:+.0f} bps | {interp} |")

    parts.append("")

    # ─── Anchored zones (A4) ───
    parts.append("**Anchored band проверка** (zone от 2010-19 era; percentile vs 5y window):")
    parts.append("")
    parts.append("| Серия | Текущо | Anchored zone | В зоната? | 5y percentile |")
    parts.append("|---|---|---|---|---|")

    for sid, (lo, hi) in ANCHORED_ZONES.items():
        cur = _last_value(snapshot.get(sid))
        if cur is None:
            continue
        in_zone = "✅ да" if lo <= cur <= hi else f"❌ извън ({(cur - (lo+hi)/2):+.2f} от средата)"
        pct = _percentile_5y(snapshot.get(sid), history_years)
        pct_str = f"{pct:.0f}%" if pct is not None else "—"
        parts.append(f"| {sid} | {cur:.2f}% | {lo}% — {hi}% | {in_zone} | {pct_str} |")

    parts.append("")

    # ═══════════════════════════════════════
    # Inflation lead-lag (PPI core → CPI core)
    # ═══════════════════════════════════════
    parts.append("### Inflation pipeline (PPI Core → CPI Core, lead 1-3m)")
    parts.append("")

    ppi_3m = _annualized_change(snapshot.get("PPICORE"), periods=3)
    cpi_3m = _annualized_change(snapshot.get("CPILFESL"), periods=3)
    ppi_yoy = _yoy_pct(snapshot.get("PPICORE"))
    cpi_yoy = _yoy_pct(snapshot.get("CPILFESL"))

    if ppi_3m is not None and cpi_3m is not None:
        gap_3m = ppi_3m - cpi_3m
        if gap_3m > 0.5:
            interp = "**PPI горещ → CPI likely up в next 1-3m print**"
        elif gap_3m < -0.5:
            interp = "**PPI cooler → CPI може да последва (disinflation в pipeline)**"
        else:
            interp = "PPI и CPI aligned — neutral pipeline"

        parts.append(f"- PPI Core: {ppi_yoy:+.2f}% YoY · **{ppi_3m:+.2f}% 3m annualized**")
        parts.append(f"- CPI Core: {cpi_yoy:+.2f}% YoY · **{cpi_3m:+.2f}% 3m annualized**")
        parts.append(f"- 3m gap (PPI − CPI): **{gap_3m:+.2f}pp**")
        parts.append(f"- Pipeline signal: {interp}")
    else:
        parts.append("_PPICORE или CPILFESL липсват — pipeline lead-lag не може да се изчисли._")

    parts.append("")
    return "\n".join(parts)


def _render_themes(lens_reports, snapshot, history_years) -> str:
    parts = ["## 2. Темите по peer group", ""]
    for lens in LENS_ORDER:
        rep = lens_reports.get(lens)
        if rep is None:
            continue
        parts.append(f"### {LENS_LABEL_BG.get(lens, lens)}")
        parts.append("")
        parts.append("| Peer group | breadth ↑ | breadth |z|>2 | данни | посока | екстремни членове |")
        parts.append("|---|---|---|---|---|---|")
        for pg in rep.peer_groups:
            bp = _fmt_breadth_pct(pg.breadth_positive)
            be = _fmt_breadth_pct(pg.breadth_extreme)
            n_str = f"{pg.n_available}/{pg.n_members}"
            dir_lbl = DIRECTION_LABEL_BG.get(pg.direction, pg.direction)
            ext_str = ", ".join(f"`{m}`" for m in pg.extreme_members) if pg.extreme_members else "—"
            parts.append(
                f"| {pg.name} | {bp} | {be} | {n_str} | {dir_lbl} | {ext_str} |"
            )
        parts.append("")
    return "\n".join(parts)


def _render_cross_lens(cross_report, snapshot) -> str:
    parts = ["## 3. Cross-Lens Divergence", ""]
    pair_lookup = {p["id"]: p for p in CROSS_LENS_PAIRS}

    for pair_reading in cross_report.pairs:
        pair_meta = pair_lookup.get(pair_reading.pair_id, {})
        narrative = pair_meta.get("narrative", "")
        state_lbl = STATE_LABEL_BG.get(pair_reading.state, pair_reading.state)
        breadth_a = _fmt_breadth_pct(pair_reading.breadth_a)
        breadth_b = _fmt_breadth_pct(pair_reading.breadth_b)

        parts.append(f"### {pair_reading.name_bg}")
        parts.append("")
        parts.append(f"**Въпрос:** {pair_reading.question_bg}")
        parts.append("")
        if narrative:
            parts.append(f"**Контекст:** {narrative}")
            parts.append("")
        parts.append(f"**Текущо състояние:** {state_lbl} (`{pair_reading.state}`)")
        parts.append("")
        parts.append(f"**Интерпретация:** {pair_reading.interpretation}")
        parts.append("")

        # Slot data
        parts.append("| Slot | Label | Breadth | n |")
        parts.append("|---|---|---|---|")
        parts.append(
            f"| A | {pair_reading.slot_a_label} | {breadth_a} | {pair_reading.n_a_available} |"
        )
        parts.append(
            f"| B | {pair_reading.slot_b_label} | {breadth_b} | {pair_reading.n_b_available} |"
        )
        parts.append("")

        # Slot composition (which peer_groups)
        slot_a_pgs = pair_meta.get("slot_a", {}).get("peer_groups", [])
        slot_b_pgs = pair_meta.get("slot_b", {}).get("peer_groups", [])
        slot_a_inv = pair_meta.get("slot_a", {}).get("invert", {})
        slot_b_inv = pair_meta.get("slot_b", {}).get("invert", {})
        parts.append("**Състав:**")
        parts.append(f"- A peer_groups: {', '.join(f'`{p}`' + (' (inv)' if slot_a_inv.get(p) else '') for p in slot_a_pgs)}")
        parts.append(f"- B peer_groups: {', '.join(f'`{p}`' + (' (inv)' if slot_b_inv.get(p) else '') for p in slot_b_pgs)}")
        parts.append("")

        # All possible interpretations (за reference при alternative scenarios)
        interps = pair_meta.get("interpretations", {})
        if interps:
            parts.append("**Всички възможни състояния:**")
            for state_key, interp in interps.items():
                state_lbl_alt = STATE_LABEL_BG.get(state_key, state_key)
                marker = " ← АКТИВНО" if state_key == pair_reading.state else ""
                parts.append(f"- `{state_key}` ({state_lbl_alt}): {interp}{marker}")
            parts.append("")
    return "\n".join(parts)


def _render_anomalies(anomaly_report, snapshot, today: date, history_years: int) -> str:
    parts = ["## 4. Top Anomalies (fact cards)", ""]
    if not anomaly_report.top:
        parts.append("_Няма серии с |z|>2 в момента._")
        return "\n".join(parts)

    parts.append(
        f"Серии с **|z|>2** (lookback {anomaly_report.lookback_years}y), "
        f"сортирани по абсолютна сила. Всеки fact card съдържа стойност, "
        f"делта в правилни units (bps/Δ/%), 5-годишен range, последни {FACT_CARD_TAIL} readings и narrative_hint."
    )
    parts.append("")
    parts.append(
        "> ⚠ **Caveat за NEW 5Y MAX/MIN flags:** 5y window = post-COVID era. "
        "За по-дълъг исторически контекст (Volcker / GFC / 1970s) виж "
        "explorer.html#<KEY> или направи отделен query."
    )
    parts.append("")

    for i, a in enumerate(anomaly_report.top, 1):
        parts.append(_series_fact_card(a.series_key, snapshot, today, history_years, rank=i, anomaly=a))
        parts.append("")
    return "\n".join(parts)


def _series_fact_card(
    sid: str,
    snapshot: dict,
    today: date,
    history_years: int,
    rank: Optional[int] = None,
    anomaly=None,
) -> str:
    """Markdown fact card за единична серия с full context."""
    meta = SERIES_CATALOG.get(sid, {})
    series = snapshot.get(sid, pd.Series(dtype=float))

    title = meta.get("name_bg", sid)
    rank_prefix = f"#{rank} " if rank else ""

    if series.empty:
        return f"### {rank_prefix}{sid} — {title}\n_(няма данни в snapshot-а)_"

    s = series.dropna().sort_index()
    last_value = float(s.iloc[-1])
    last_date = s.index[-1].date() if hasattr(s.index[-1], "date") else str(s.index[-1])[:10]

    # Display kind (bps/abs/percent)
    kind = change_kind(sid, meta)

    # Long и short change
    try:
        long_periods = _infer_yoy_periods(s)
    except Exception:
        long_periods = 12
    try:
        long_chg_series = compute_change(s, kind, long_periods)
        short_chg_series = compute_change(s, kind, 1)
        long_chg = long_chg_series.iloc[-1] if not long_chg_series.empty else float("nan")
        short_chg = short_chg_series.iloc[-1] if not short_chg_series.empty else float("nan")
    except Exception:
        long_chg = float("nan")
        short_chg = float("nan")

    # 5y window
    cutoff = pd.Timestamp(last_date) - pd.DateOffset(years=history_years)
    s_hist = s[s.index >= cutoff]

    # 5y range stats
    if len(s_hist) > 1:
        hist_min = float(s_hist.min())
        hist_max = float(s_hist.max())
        hist_median = float(s_hist.median())
        below_count = int((s_hist < last_value).sum())
        pct_rank = below_count / len(s_hist) * 100  # current percentile
    else:
        hist_min = hist_max = hist_median = pct_rank = float("nan")

    # Z-score (recompute от 5y window за consistency)
    if len(s_hist) > 1:
        std = float(s_hist.std())
        mean = float(s_hist.mean())
        z = (last_value - mean) / std if std != 0 else 0.0
    else:
        z = float("nan")

    # Last N readings
    tail = s.tail(FACT_CARD_TAIL)

    # Build markdown
    lines = []
    lines.append(f"### {rank_prefix}`{sid}` — {title}")
    lines.append("")

    # Identification line
    fred_id = meta.get("id", sid)
    lens_str = " / ".join(meta.get("lens", []))
    peer_str = meta.get("peer_group", "")
    tags = meta.get("tags") or []
    tags_str = " · ".join(f"`{t}`" for t in tags) if tags else ""

    lines.append(f"- **FRED:** `{fred_id}` · **Тема:** {lens_str} · **Peer:** {peer_str}"
                 + (f" · **Тагове:** {tags_str}" if tags_str else ""))

    # Staleness flag (D1 — period-aware за тримесечни)
    release_schedule = meta.get("release_schedule", "monthly")
    last_obs_d = last_date if isinstance(last_date, date) else None
    if last_obs_d:
        stale = assess_staleness(last_obs_d, release_schedule, today)
        if stale["level"] in ("warning", "critical"):
            marker = _staleness_marker(stale["level"])
            lines.append(f"- {marker}**Staleness:** {stale['explanation']}")
        elif release_schedule == "quarterly":
            # За quarterly винаги показваме explanation (date convention easy to misread)
            lines.append(f"- **ℹ Quarterly note:** {stale['explanation']}")

    # Nominal warning (B3 — за nominal серии без deflation)
    if sid in NOMINAL_SERIES_NEED_DEFLATION:
        purpose = NOMINAL_SERIES_NEED_DEFLATION[sid]
        if "already deflated" not in purpose.lower():
            lines.append(
                f"- **⚠ Nominal:** тази серия е nominal — за thesis-claim "
                f"за real growth, виж секция 1.5 (Cross-spreads → Real {purpose.split(' ')[0].lower()})"
            )

    # Current state line
    lines.append(
        f"- **Текущо ({last_date}):** {fmt_value(last_value)} · "
        f"**z** {z:+.2f} · **percentile (5y)** {pct_rank:.0f}%"
        + (f" · **Δ direction** {anomaly.direction}" if anomaly else "")
        + (" · **NEW 5Y MAX** ⚠" if anomaly and anomaly.is_new_extreme and anomaly.new_extreme_direction == "max" else "")
        + (" · **NEW 5Y MIN** ⚠" if anomaly and anomaly.is_new_extreme and anomaly.new_extreme_direction == "min" else "")
    )

    # Change line (proper units)
    long_lbl = "Δ1y" if long_periods >= 12 else f"Δ{long_periods}p"
    lines.append(
        f"- **Промяна:** {long_lbl} {fmt_change(long_chg, kind)} · "
        f"Δ short {fmt_change(short_chg, kind)} (display: {kind})"
    )

    # 5y range
    if not (math.isnan(hist_min) or math.isnan(hist_max)):
        lines.append(
            f"- **5y range:** мин {fmt_value(hist_min)} · "
            f"медиана {fmt_value(hist_median)} · макс {fmt_value(hist_max)}"
        )

    # Last readings
    lines.append(f"- **Последни {len(tail)} readings:**")
    for dt, val in tail.items():
        d_str = dt.date() if hasattr(dt, "date") else str(dt)[:10]
        lines.append(f"  - {d_str} → {fmt_value(float(val))}")

    # Narrative hint
    hint = meta.get("narrative_hint") or ""
    if hint:
        lines.append(f"- **Тълкуване (от каталога):** {hint}")

    return "\n".join(lines)


def _render_methodology_compact() -> str:
    return """## 5. Методология (compact)

- **Breadth ↑** — % серии в peer group с положителен 1-периоден momentum. Прагове: >60% разширяване, <40% свиване, между = смесено.
- **Breadth |z|>2** — % серии в групата със стойност >2 стандартни отклонения от 5y mean (екстремна).
- **z-score** — стандартизирана отдалеченост от 5y средна. |z|>2 = ~5% от времето в нормална дистрибуция.
- **Percentile (5y)** — къде стои текущата стойност в 5-годишното разпределение (0% = нов 5y минимум, 100% = нов 5y максимум).
- **Cross-lens states** — `both_up` / `both_down` / `a_up_b_down` / `a_down_b_up` (divergence) / `transition` (между прагове) / `insufficient_data`.
- **Display-by-type** — за rate-нива (BREAKEVEN, UST, OAS, FED_FUNDS, UNRATE) Δ е в bps; за signed индекси (NFCI, CFNAI, UMCSENT) — абсолютна делта; за price levels (CPI, payrolls) — %.
- **Малки peer groups (3 серии)** — 1 серия флипваща = 33pp промяна. 100pp в WoW не е грешка, а пълна смяна на посока в малка група.
- **Серии с † тагове** — revision-prone, изчакай 2-3 релиза за потвърждение.
"""


# ============================================================
# HELPERS
# ============================================================

def _fmt_breadth_pct(v) -> str:
    """Форматира breadth (0..1 decimal) като '67%'. NaN → '—'."""
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if math.isnan(f):
        return "—"
    return f"{f*100:.0f}%"
