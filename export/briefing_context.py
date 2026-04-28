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

from datetime import date
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
    sections.append(_render_themes(lens_reports, snapshot, history_years))
    sections.append(_render_cross_lens(cross_report, snapshot))
    sections.append(_render_anomalies(anomaly_report, snapshot, history_years))
    sections.append(_render_methodology_compact())

    body = "\n\n".join(sections)

    out_dir = Path(output_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"briefing_context_{today.isoformat()}.md"
    out_file.write_text(body, encoding="utf-8")
    return str(out_file.resolve())


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


def _render_anomalies(anomaly_report, snapshot, history_years) -> str:
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

    for i, a in enumerate(anomaly_report.top, 1):
        parts.append(_series_fact_card(a.series_key, snapshot, history_years, rank=i, anomaly=a))
        parts.append("")
    return "\n".join(parts)


def _series_fact_card(
    sid: str,
    snapshot: dict,
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

    # Current state line
    lines.append(
        f"- **Текущо ({last_date}):** {fmt_value(last_value)} · "
        f"**z** {z:+.2f} · **percentile (5y)** {pct_rank:.0f}%"
        + (f" · **Δ direction** {anomaly.direction}" if anomaly else "")
        + (" · **NEW 5Y MAX**" if anomaly and anomaly.is_new_extreme and anomaly.new_extreme_direction == "max" else "")
        + (" · **NEW 5Y MIN**" if anomaly and anomaly.is_new_extreme and anomaly.new_extreme_direction == "min" else "")
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
