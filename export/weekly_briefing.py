"""
export/weekly_briefing.py
=========================
Lens-first седмичен briefing — self-contained HTML.

Структура:
  1. Header — дата, as_of, summary counters
  2. Cross-Lens Divergence Pairs (5 canonical) — state + interpretation
  3. Per-lens блокове (4 × labor/growth/inflation/liquidity):
       - Breadth table (peer_groups)
       - Notable intra-lens divergences
       - Anomalies в този lens
  4. Non-consensus highlights (triaged tagged серии)
  5. Top anomalies feed (cross-lens |z|>2)
  6. Footer — methodology + revision caveats

Философия: sparse MVP. Без JS, без CDN, без images. Inline CSS.
Печатаемо. Всички стойности, обяснения и interpretacii са вече изчислени
в analysis/ слоя — това е само renderer.

Dependencies:
  - analysis.breadth, divergence, non_consensus, anomaly
  - catalog.series — за revision_prone caveats
"""
from __future__ import annotations

import html
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from scripts._utils import JournalEntry  # noqa: F401

from catalog.series import SERIES_CATALOG, ALLOWED_LENSES
from core.display import change_kind, compute_change, fmt_change, fmt_value
from analysis.breadth import compute_lens_breadth
from analysis.divergence import (
    compute_intra_lens_divergence,
    compute_cross_lens_divergence,
)
from analysis.non_consensus import compute_non_consensus
from analysis.anomaly import compute_anomalies
from analysis.executive import compute_executive_summary, LENS_LABEL_BG as _EXEC_LENS_BG
from analysis.delta import (
    build_state_snapshot,
    compute_delta,
    save_state,
    load_latest_state,
    STATE_DIR_DEFAULT,
)
from analysis.guardrails import (
    compute_threshold_flags,
    get_falsifiers,
    SEVERITY_RED,
    SEVERITY_AMBER,
)
from analysis.analog_pipeline import AnalogBundle
from analysis.analog_matcher import classify_strength, STRENGTH_LABELS_BG
from analysis.macro_vector import DIM_LABELS_BG, DIM_UNITS, STATE_VECTOR_DIMS


LENS_ORDER = ["labor", "growth", "inflation", "liquidity"]
LENS_LABEL_BG = {
    "labor": "Трудов пазар",
    "growth": "Растеж",
    "inflation": "Инфлация",
    "liquidity": "Ликвидност и кредит",
    "housing": "Жилищен пазар",
}

# Default href prefix за series-ref линкове. Briefing-ът сочи към
# explorer.html#KEY; Explorer-ът сам при вътрешни референции подава "".
EXPLORER_HREF = "explorer.html"

DIRECTION_LABEL_BG = {
    "expanding": "разширяване",
    "contracting": "свиване",
    "mixed": "смесено",
    "insufficient_data": "недостатъчно данни",
}

STATE_LABEL_BG = {
    "both_up": "↑↑ и двете нагоре",
    "both_down": "↓↓ и двете надолу",
    "a_up_b_down": "↑↓ A нагоре / B надолу",
    "a_down_b_up": "↓↑ A надолу / B нагоре",
    "transition": "⇄ преход",
    "insufficient_data": "недостатъчно данни",
}


# ============================================================
# PUBLIC API
# ============================================================

def generate_weekly_briefing(
    snapshot: dict[str, pd.Series],
    output_path: str,
    top_anomalies_n: int = 10,
    today: Optional[date] = None,
    state_dir: Optional[str] = STATE_DIR_DEFAULT,
    persist_state: bool = True,
    analog_bundle: Optional[AnalogBundle] = None,
    journal_entries: Optional[list[Any]] = None,
) -> str:
    """Генерира HTML briefing от snapshot; връща абсолютния path.

    Args:
        snapshot: {series_key → pd.Series}.
        output_path: path до output HTML файла (може и само име).
        top_anomalies_n: колко top anomalies да листваме.
        today: override за тестове.
        state_dir: директория за briefing state snapshots (WoW delta).
            Ако None — WoW delta се пропуска напълно.
        persist_state: дали да записва текущия state за бъдещо сравнение.
        analog_bundle: Optional резултат от compute_analog_bundle. Ако е
            None — "Исторически аналог" секцията се пропуска напълно.
        journal_entries: Optional list от JournalEntry (scripts._utils) обекти
            за "Свързани бележки" секцията. Ако None или празно — секцията
            се пропуска. Очаква entries вече filtered/relevance-ranked.

    Returns:
        Абсолютен path към записания HTML файл.
    """
    if today is None:
        today = date.today()

    # ─── Compute всички доклади ───
    lens_reports = {
        lens: compute_lens_breadth(lens, snapshot) for lens in LENS_ORDER
    }
    intra_reports = {
        lens: compute_intra_lens_divergence(lens, snapshot) for lens in LENS_ORDER
    }
    cross_report = compute_cross_lens_divergence(snapshot)
    nc_report = compute_non_consensus(snapshot)
    anomaly_report = compute_anomalies(
        snapshot, z_threshold=2.0, top_n=top_anomalies_n, lookback_years=5
    )
    exec_snapshot = compute_executive_summary(
        cross_report, lens_reports, anomaly_report, nc_report,
    )

    # Threshold flags и falsifiers
    threshold_flags = compute_threshold_flags(snapshot)
    falsifiers = get_falsifiers(exec_snapshot.regime_label)

    # Week-over-week delta (no-op ако state_dir е None)
    current_state = build_state_snapshot(
        exec_snapshot, cross_report, lens_reports, anomaly_report, nc_report,
        generated_on=today,
    )
    prev_state = None
    if state_dir is not None:
        try:
            # WoW сравнение — гледаме поне 5 дни назад, за да хванем предишната
            # календарна седмица (типично предишния понеделник).
            prev_state = load_latest_state(
                state_dir=state_dir, before=today, min_age_days=5
            )
        except Exception:
            prev_state = None
    delta = compute_delta(current_state, prev_state)

    as_of = _pick_as_of(lens_reports, cross_report, anomaly_report)

    # ─── Render всички секции ───
    sections: list[str] = []
    sections.append(_render_header(today, as_of, snapshot, lens_reports, nc_report, anomaly_report))
    sections.append(_render_executive(exec_snapshot, falsifiers, threshold_flags))
    sections.append(_render_delta(delta))
    sections.append(_render_cross_lens(cross_report))
    if analog_bundle is not None:
        sections.append(_render_analogs(analog_bundle))
    for lens in LENS_ORDER:
        sections.append(_render_lens_block(
            lens, lens_reports[lens], intra_reports[lens], anomaly_report,
        ))
    sections.append(_render_non_consensus(nc_report))
    sections.append(_render_anomalies_feed(anomaly_report, snapshot))
    if journal_entries:
        sections.append(_render_journal(journal_entries))
    sections.append(_render_footer(as_of, today))

    body = "\n".join(sections)
    full_html = _skeleton(
        title=f"Седмичен Briefing — {today.isoformat()}",
        body=body,
    )

    out = Path(output_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(full_html, encoding="utf-8")

    # Persist state за следваща WoW сравнение
    if persist_state and state_dir is not None:
        try:
            save_state(current_state, state_dir=state_dir)
        except Exception:
            # persistence грешки не trigger-ват briefing failure
            pass

    return str(out)


# ============================================================
# SECTION RENDERERS
# ============================================================

def _render_header(today, as_of, snapshot, lens_reports, nc_report, anomaly_report) -> str:
    n_series = len(snapshot)
    n_high_signals = sum(1 for r in nc_report.highlights if r.signal_strength == "high")
    n_medium_signals = sum(1 for r in nc_report.highlights if r.signal_strength == "medium")
    n_anomalies = anomaly_report.total_flagged
    return f"""
<header class="brief-header">
  <div class="brief-title">
    <h1>Седмичен Briefing</h1>
    <div class="brief-subtitle">Генериран {today.isoformat()} · Данни към {html.escape(as_of or '—')}</div>
  </div>
  <div class="brief-kpis">
    <div class="kpi"><div class="kpi-n">{n_series}</div><div class="kpi-l">серии</div></div>
    <div class="kpi"><div class="kpi-n">{n_anomalies}</div><div class="kpi-l">аномалии |z|>2</div></div>
    <div class="kpi"><div class="kpi-n">{n_high_signals}</div><div class="kpi-l">non-consensus HIGH</div></div>
    <div class="kpi"><div class="kpi-n">{n_medium_signals}</div><div class="kpi-l">non-consensus MEDIUM</div></div>
  </div>
</header>
"""


def _render_executive(exec_snapshot, falsifiers=None, threshold_flags=None) -> str:
    """Executive Summary + Regime table — първа съдържателна секция."""
    falsifiers = falsifiers or []
    threshold_flags = threshold_flags or []
    # Regime badge + narrative
    regime_label = html.escape(exec_snapshot.regime_label_bg)
    regime_cls = html.escape(exec_snapshot.regime_css_class)
    narrative = html.escape(exec_snapshot.narrative_bg)
    driver = html.escape(exec_snapshot.primary_driver)

    # Lens regime table
    lens_rows_html = []
    for row in exec_snapshot.lens_rows:
        lens_bg = _EXEC_LENS_BG.get(row.lens, row.lens)
        dir_cls = _direction_class(row.direction)
        dir_label = DIRECTION_LABEL_BG.get(row.direction, row.direction)
        breadth_str = _fmt_breadth(row.breadth_agg)
        ne_badge = (
            f"<span class='ne-inline'>{row.new_extreme_count} NEW</span>"
            if row.new_extreme_count > 0 else ""
        )
        lens_rows_html.append(f"""
<tr>
  <td class="pg-name">{html.escape(lens_bg)}</td>
  <td><span class="dir-badge {dir_cls}">{html.escape(dir_label)}</span></td>
  <td class="num">{breadth_str}</td>
  <td class="num">{row.anomaly_count} {ne_badge}</td>
</tr>
""")

    # Supporting signals
    if exec_snapshot.supporting_signals:
        signals_html = "".join(
            f"<li>{html.escape(s)}</li>"
            for s in exec_snapshot.supporting_signals
        )
        signals_block = f"<div class='exec-signals'><h4>Поддържащи сигнали</h4><ul>{signals_html}</ul></div>"
    else:
        signals_block = "<div class='exec-signals muted'>Няма активни поддържащи сигнали.</div>"

    # Threshold flags banner
    flags_banner = _render_threshold_flags_banner(threshold_flags)

    # Falsification criteria
    if falsifiers:
        f_items = "".join(f"<li>{html.escape(f)}</li>" for f in falsifiers)
        falsification_block = (
            f"<div class='exec-falsifiers'>"
            f"<h4>Falsification criteria — какво би обезсилило тази диагноза</h4>"
            f"<ul>{f_items}</ul>"
            f"</div>"
        )
    else:
        falsification_block = ""

    return f"""
<section class="brief-section exec-section">
  <h2>Executive Summary</h2>
  <div class="exec-headline">
    <div class="regime-badge {regime_cls}">
      <div class="regime-label">Режим</div>
      <div class="regime-val">{regime_label}</div>
      <div class="regime-driver">driver: {driver}</div>
    </div>
    <div class="exec-narrative">{narrative}</div>
  </div>
  {flags_banner}
  <div class="exec-grid">
    <table class="regime-table">
      <thead><tr>
        <th>Тема</th><th>Посока</th><th>Breadth ↑</th><th>Аномалии</th>
      </tr></thead>
      <tbody>{"".join(lens_rows_html)}</tbody>
    </table>
    {signals_block}
  </div>
  {falsification_block}
</section>
"""


def _render_threshold_flags_banner(threshold_flags) -> str:
    """Color-coded баннер за активни threshold flags."""
    if not threshold_flags:
        return ""
    items = []
    for f in threshold_flags:
        sev_cls = f"flag-{f.severity}"
        link = render_series_ref(f.series_key, "code-ref", EXPLORER_HREF) \
            if f.series_key else f.series_key
        items.append(
            f'<div class="flag-item {sev_cls}">'
            f'<span class="flag-sev">{f.severity.upper()}</span>'
            f'<span class="flag-label">{html.escape(f.label_bg)}</span>'
            f'<span class="flag-val">{link} = {f.value}</span>'
            f'<div class="flag-msg">{html.escape(f.message_bg)}</div>'
            f'</div>'
        )
    return f"""
<div class="flags-banner">
  <div class="flags-banner-head">⚠️ Threshold алерти ({len(threshold_flags)})</div>
  <div class="flags-banner-body">{"".join(items)}</div>
</div>
"""


def _render_delta(delta) -> str:
    """Week-over-week delta секция."""
    if delta.prev_generated_on is None:
        # Първи run — няма предишен state
        return """
<section class="brief-section delta-section">
  <h2>Week-over-Week</h2>
  <p class="muted">Няма референтен snapshot — това е първият генериран briefing (или няма предишно състояние в state/).</p>
</section>
"""
    if not delta.has_content:
        return f"""
<section class="brief-section delta-section">
  <h2>Week-over-Week <span class="delta-since">(спрямо {html.escape(delta.prev_generated_on)})</span></h2>
  <p class="muted">Без съществени промени от предишния brief.</p>
</section>
"""

    parts: list[str] = []

    # Regime change — най-горе, ако има
    if delta.regime_change:
        from_lbl, to_lbl = delta.regime_change
        parts.append(f"""
<div class="delta-regime">
  <span class="delta-label">Смяна на режим:</span>
  <span class="delta-arrow">{html.escape(from_lbl)} → <strong>{html.escape(to_lbl)}</strong></span>
</div>
""")

    # Cross-lens flips — user-friendly наименования + кратка интерпретация
    if delta.cross_lens_changes:
        from catalog.cross_lens_pairs import CROSS_LENS_PAIRS
        pair_lookup = {p["id"]: p for p in CROSS_LENS_PAIRS}
        rows = []
        for c in delta.cross_lens_changes:
            pair_meta = pair_lookup.get(c.pair_id, {})
            pair_name = pair_meta.get("name_bg", c.pair_id)
            from_lbl = STATE_LABEL_BG.get(c.from_state, c.from_state)
            to_lbl = STATE_LABEL_BG.get(c.to_state, c.to_state)
            new_interp = (pair_meta.get("interpretations") or {}).get(c.to_state, "")
            interp_html = (
                f" <em class='delta-interp'>— {html.escape(new_interp)}</em>"
                if new_interp and new_interp != "—" else ""
            )
            rows.append(
                f"<li><strong>{html.escape(pair_name)}</strong>: "
                f"<span class='state-from'>{html.escape(from_lbl)}</span> → "
                f"<strong class='state-to'>{html.escape(to_lbl)}</strong>"
                f"{interp_html}</li>"
            )
        parts.append(
            f"<div class='delta-block'><h4>Cross-lens flips</h4>"
            f"<ul>{''.join(rows)}</ul></div>"
        )

    # Breadth moves
    if delta.breadth_moves:
        rows = "".join(
            f"<li><strong>{html.escape(m.lens)}/{html.escape(m.peer_group)}</strong>: "
            f"{m.from_value:.0%} → {m.to_value:.0%} "
            f"<span class='delta-pp {_delta_sign_class(m.delta_pp)}'>"
            f"{_fmt_pp(m.delta_pp)}</span></li>"
            for m in delta.breadth_moves[:8]
        )
        more = ""
        if len(delta.breadth_moves) > 8:
            more = f"<div class='muted'>…+{len(delta.breadth_moves) - 8} още</div>"
        parts.append(f"<div class='delta-block'><h4>Breadth движения (≥10pp)</h4><ul>{rows}</ul>{more}</div>")

    # New / vanished HIGH NC
    if delta.new_high_nc or delta.vanished_high_nc:
        subs = []
        if delta.new_high_nc:
            keys = " ".join(render_series_ref(k, "code-ref", EXPLORER_HREF) for k in delta.new_high_nc)
            subs.append(f"<div><span class='delta-tag new'>NEW HIGH</span> {keys}</div>")
        if delta.vanished_high_nc:
            keys = " ".join(
                f"<code class='ref-vanished'>{html.escape(k)}</code>"
                for k in delta.vanished_high_nc
            )
            subs.append(f"<div><span class='delta-tag gone'>GONE</span> {keys}</div>")
        parts.append(f"<div class='delta-block'><h4>Non-consensus HIGH</h4>{''.join(subs)}</div>")

    # New / resolved NEW-5Y екстремуми
    if delta.new_extremes_surfaced or delta.new_extremes_resolved:
        subs = []
        if delta.new_extremes_surfaced:
            keys = " ".join(render_series_ref(k, "code-ref", EXPLORER_HREF) for k in delta.new_extremes_surfaced)
            subs.append(f"<div><span class='delta-tag new'>NEW 5Y</span> {keys}</div>")
        if delta.new_extremes_resolved:
            keys = " ".join(
                f"<code class='ref-vanished'>{html.escape(k)}</code>"
                for k in delta.new_extremes_resolved
            )
            subs.append(f"<div><span class='delta-tag gone'>RESOLVED</span> {keys}</div>")
        parts.append(f"<div class='delta-block'><h4>5-годишни екстремуми</h4>{''.join(subs)}</div>")

    return f"""
<section class="brief-section delta-section">
  <h2>Week-over-Week <span class="delta-since">(спрямо {html.escape(delta.prev_generated_on)})</span></h2>
  {"".join(parts)}
</section>
"""


def _delta_sign_class(delta_pp: float) -> str:
    if delta_pp > 0:
        return "up"
    if delta_pp < 0:
        return "down"
    return "flat"


def _fmt_pp(delta_pp: float) -> str:
    return f"{delta_pp * 100:+.1f}pp"


def _render_cross_lens(cross_report) -> str:
    pair_rows = []
    for p in cross_report.pairs:
        state_cls = _state_class(p.state)
        state_label = STATE_LABEL_BG.get(p.state, p.state)
        pair_rows.append(f"""
<div class="pair-card">
  <div class="pair-head">
    <span class="pair-state {state_cls}">{html.escape(state_label)}</span>
    <h3>{html.escape(p.name_bg)}</h3>
  </div>
  <div class="pair-question">{html.escape(p.question_bg)}</div>
  <div class="pair-grid">
    <div class="pair-slot">
      <div class="pair-slot-label">A · {html.escape(p.slot_a_label)}</div>
      <div class="pair-slot-val">{_fmt_breadth(p.breadth_a)}</div>
      <div class="pair-slot-n">n={p.n_a_available}</div>
    </div>
    <div class="pair-slot">
      <div class="pair-slot-label">B · {html.escape(p.slot_b_label)}</div>
      <div class="pair-slot-val">{_fmt_breadth(p.breadth_b)}</div>
      <div class="pair-slot-n">n={p.n_b_available}</div>
    </div>
  </div>
  <div class="pair-interp">{html.escape(p.interpretation)}</div>
</div>
""")
    return f"""
<section class="brief-section">
  <h2>Cross-Lens Divergence</h2>
  <div class="pair-wrap">
    {"".join(pair_rows)}
  </div>
</section>
"""


def _render_analogs(bundle: AnalogBundle) -> str:
    """Исторически аналог секция — top-3 analog-а + forward outcomes."""
    if not bundle.analogs:
        return ""

    # Header row — current state summary
    cur = bundle.current_state
    cur_cells = []
    for d in STATE_VECTOR_DIMS:
        if d not in cur.raw:
            continue
        label = DIM_LABELS_BG.get(d, d)
        unit = DIM_UNITS.get(d, "")
        cur_cells.append(
            f"<div class='analog-dim'>"
            f"<div class='analog-dim-label'>{html.escape(label)}</div>"
            f"<div class='analog-dim-val'>{cur.raw[d]:.2f}{unit}</div>"
            f"<div class='analog-dim-z'>z={cur.z[d]:+.2f}</div>"
            f"</div>"
        )
    current_strip = f"""
<div class="analog-current">
  <div class="analog-current-head">Текущ macro state — {cur.as_of.strftime('%Y-%m')}</div>
  <div class="analog-dim-grid">{"".join(cur_cells)}</div>
</div>
"""

    # Analog cards (top-3)
    card_html = []
    for i, (a, comp) in enumerate(zip(bundle.analogs, bundle.comparisons)):
        strength = classify_strength(a.similarity)
        strength_bg = STRENGTH_LABELS_BG.get(strength, strength)
        label = a.episode_label or "—"
        label_esc = html.escape(label) if a.episode_label else "<span class='muted'>—</span>"
        date_str = a.date.strftime("%Y-%m")

        # Top 3 similarity drivers (closest dims)
        tight_html = []
        for delta in comp.similarities[:3]:
            unit = DIM_UNITS.get(delta.dim, "")
            tight_html.append(
                f"<li><span class='analog-dim-label'>{html.escape(delta.label_bg)}</span>: "
                f"<span class='analog-num'>{delta.current_raw:.2f}{unit}</span> vs "
                f"<span class='analog-num'>{delta.analog_raw:.2f}{unit}</span> "
                f"<span class='analog-z'>(Δz={delta.z_diff:+.2f})</span></li>"
            )

        # Divergences (top 2, ако има)
        div_html = []
        for delta in comp.divergences[:2]:
            unit = DIM_UNITS.get(delta.dim, "")
            div_html.append(
                f"<li><span class='analog-dim-label'>{html.escape(delta.label_bg)}</span>: "
                f"<span class='analog-num'>{delta.current_raw:.2f}{unit}</span> vs "
                f"<span class='analog-num'>{delta.analog_raw:.2f}{unit}</span> "
                f"<span class='analog-z analog-z-div'>(Δz={delta.z_diff:+.2f})</span></li>"
            )
        div_block = (
            f"<div class='analog-div-block'><h5>Където разликата е голяма</h5>"
            f"<ul>{''.join(div_html)}</ul></div>"
            if div_html else ""
        )

        # Forward outcomes за този analog
        per = next((p for p in bundle.forward.per_analog if p.analog_date == a.date), None)
        if per:
            horizons = bundle.forward.horizons
            dims = bundle.forward.dims
            # Header row
            fw_header = "<tr><th>Измерение</th>" + "".join(f"<th class='num'>+{h}m</th>" for h in horizons) + "</tr>"
            fw_rows = []
            for d in dims:
                label_d = DIM_LABELS_BG.get(d, d)
                unit = DIM_UNITS.get(d, "")
                cells = []
                for h in horizons:
                    if h in per.values[d]:
                        val = per.values[d][h]
                        delta = per.deltas[d].get(h)
                        if delta is not None:
                            sign = "+" if delta >= 0 else ""
                            cells.append(
                                f"<td class='num'>{val:.2f}{unit} "
                                f"<span class='analog-delta'>({sign}{delta:.2f})</span></td>"
                            )
                        else:
                            cells.append(f"<td class='num'>{val:.2f}{unit}</td>")
                    else:
                        cells.append("<td class='num muted'>—</td>")
                fw_rows.append(f"<tr><td class='pg-name'>{html.escape(label_d)}</td>{''.join(cells)}</tr>")
            fw_block = f"""
<div class="analog-forward">
  <h5>Какво се е случило след {', '.join(f'{h}m' for h in horizons)}</h5>
  <table class="analog-fw-table">
    <thead>{fw_header}</thead>
    <tbody>{''.join(fw_rows)}</tbody>
  </table>
</div>
"""
        else:
            fw_block = ""

        card_html.append(f"""
<div class="analog-card analog-strength-{strength}">
  <div class="analog-card-head">
    <div class="analog-rank">#{a.rank}</div>
    <div class="analog-date">{date_str}</div>
    <div class="analog-episode">{label_esc}</div>
    <div class="analog-sim">
      <div class="analog-sim-val">{a.similarity:.3f}</div>
      <div class="analog-sim-lbl">{html.escape(strength_bg)}</div>
    </div>
  </div>
  <div class="analog-card-body">
    <div class="analog-sim-block">
      <h5>Къде приликата е най-тясна</h5>
      <ul>{''.join(tight_html)}</ul>
    </div>
    {div_block}
    {fw_block}
  </div>
</div>
""")

    # Aggregate forward outcomes (median across analogs)
    agg_dims = bundle.forward.dims
    agg_horizons = bundle.forward.horizons
    agg_header = "<tr><th>Измерение</th>" + "".join(f"<th class='num'>+{h}m (median)</th>" for h in agg_horizons) + "</tr>"
    agg_rows = []
    for d in agg_dims:
        label_d = DIM_LABELS_BG.get(d, d)
        unit = DIM_UNITS.get(d, "")
        cells = []
        for h in agg_horizons:
            summary = next(
                (s for s in bundle.forward.aggregates
                 if s.dim == d and s.horizon_months == h),
                None,
            )
            if summary and summary.median_value is not None:
                md = summary.median_delta
                if md is not None:
                    sign = "+" if md >= 0 else ""
                    cells.append(
                        f"<td class='num'>{summary.median_value:.2f}{unit} "
                        f"<span class='analog-delta'>({sign}{md:.2f})</span> "
                        f"<span class='analog-n'>n={summary.n}</span></td>"
                    )
                else:
                    cells.append(
                        f"<td class='num'>{summary.median_value:.2f}{unit} "
                        f"<span class='analog-n'>n={summary.n}</span></td>"
                    )
            else:
                cells.append("<td class='num muted'>—</td>")
        agg_rows.append(f"<tr><td class='pg-name'>{html.escape(label_d)}</td>{''.join(cells)}</tr>")
    aggregate_block = f"""
<div class="analog-aggregate">
  <h4>Агрегат: медиана през всички top-{len(bundle.analogs)} аналози</h4>
  <table class="analog-fw-table">
    <thead>{agg_header}</thead>
    <tbody>{''.join(agg_rows)}</tbody>
  </table>
</div>
"""

    caveat = (
        "<div class='analog-caveat'>"
        "⚠ <strong>Аналог ≠ прогноза.</strong> Sample size = {n} аналози; "
        "различните регуляторни и пазарни режими намаляват приложимостта. "
        "HY spread pre-1996 е BAA−10Y proxy; breakeven pre-2003 е Michigan 1Y proxy. "
        "Използвай като контекст, не като търговски сигнал."
        "</div>"
    ).format(n=len(bundle.analogs))

    return f"""
<section class="brief-section analog-section">
  <h2>Исторически аналог</h2>
  {current_strip}
  <div class="analog-wrap">
    {"".join(card_html)}
  </div>
  {aggregate_block}
  {caveat}
</section>
"""


def _render_lens_block(lens, breadth_report, intra_report, anomaly_report) -> str:
    label = LENS_LABEL_BG.get(lens, lens)

    # Breadth table
    breadth_rows = []
    for pg in breadth_report.peer_groups:
        bp_str = _fmt_breadth(pg.breadth_positive)
        be_str = _fmt_breadth(pg.breadth_extreme)
        dir_cls = _direction_class(pg.direction)
        dir_label = DIRECTION_LABEL_BG.get(pg.direction, pg.direction)
        extreme_marks = " ".join(
            render_series_ref(k, extra_classes="ext-mark", href_prefix=EXPLORER_HREF)
            for k in pg.extreme_members[:4]
        )
        breadth_rows.append(f"""
<tr>
  <td class="pg-name">{html.escape(pg.name)}</td>
  <td class="num">{bp_str}</td>
  <td class="num">{be_str}</td>
  <td class="num">{pg.n_available}/{pg.n_members}</td>
  <td><span class="dir-badge {dir_cls}">{html.escape(dir_label)}</span></td>
  <td class="extremes">{extreme_marks}</td>
</tr>
""")
    breadth_table = f"""
<table class="breadth-table">
  <thead><tr>
    <th>Peer group</th><th>breadth ↑</th><th>breadth |z|>2</th>
    <th>данни</th><th>посока</th><th>екстремни членове</th>
  </tr></thead>
  <tbody>{"".join(breadth_rows)}</tbody>
</table>
"""

    # Intra-lens divergences
    if intra_report.divergences:
        div_rows = "".join(
            f"<li><strong>{html.escape(d.group_a)}</strong> ({d.breadth_a:.0%}) "
            f"vs <strong>{html.escape(d.group_b)}</strong> ({d.breadth_b:.0%}) "
            f"<span class='diff'>Δ {d.diff:+.0%}</span></li>"
            for d in intra_report.divergences[:5]
        )
        div_block = f"<div class='intra-div'><h4>Вътрешни разминавания</h4><ul>{div_rows}</ul></div>"
    else:
        div_block = "<div class='intra-div muted'>Няма notable вътрешни разминавания.</div>"

    # Anomalies in this lens
    lens_anoms = anomaly_report.by_lens.get(lens, [])[:5]
    if lens_anoms:
        anom_rows = "".join(
            f"<li>{_arrow(a.direction)} {render_series_ref(a.series_key, 'code-ref', EXPLORER_HREF)} "
            f"<span class='z'>z={a.z_score:+.2f}</span>"
            f"{'  <span class=ne>NEW 5Y ' + a.new_extreme_direction.upper() + '</span>' if a.is_new_extreme and a.new_extreme_direction else ''}"
            f"<span class='pg'>· {html.escape(a.peer_group)}</span>"
            f"{_revision_caveat(a.series_key)}"
            f"</li>"
            for a in lens_anoms
        )
        anom_block = f"<div class='lens-anoms'><h4>Аномалии в лещата</h4><ol>{anom_rows}</ol></div>"
    else:
        anom_block = "<div class='lens-anoms muted'>Няма аномалии в тази леща.</div>"

    return f"""
<section class="brief-section lens-block" data-lens="{html.escape(lens)}">
  <h2>{html.escape(label)}</h2>
  {breadth_table}
  <div class="lens-grid">
    {div_block}
    {anom_block}
  </div>
</section>
"""


def _render_non_consensus(nc_report) -> str:
    if not nc_report.highlights:
        return """
<section class="brief-section">
  <h2>Non-Consensus</h2>
  <p class="muted">Нито една tagged серия не е с high/medium сигнал в момента.</p>
</section>
"""
    rows = []
    for r in nc_report.highlights:
        tag_spans = " ".join(
            f"<span class='tag tag-{html.escape(t)}'>{html.escape(t)}</span>"
            for t in r.tags
        )
        z_str = f"{r.z_score:+.2f}" if r.z_score == r.z_score else "—"
        peer_str = f"{r.peer_breadth:.0%}" if r.peer_breadth == r.peer_breadth else "—"
        rows.append(f"""
<tr class="sig-{html.escape(r.signal_strength)}">
  <td><span class="sig-badge sig-{html.escape(r.signal_strength)}">{html.escape(r.signal_strength.upper())}</span></td>
  <td>{render_series_ref(r.series_key, 'code-ref', EXPLORER_HREF)}{_revision_caveat(r.series_key)}</td>
  <td>{html.escape(r.series_name_bg)}</td>
  <td class="num">{z_str}</td>
  <td class="num">{peer_str}</td>
  <td>{html.escape(r.peer_direction)}</td>
  <td>{'✓' if r.deviates_from_peers else ''}</td>
  <td>{tag_spans}</td>
</tr>
""")
    return f"""
<section class="brief-section">
  <h2>Non-Consensus Highlights</h2>
  <table class="nc-table">
    <thead><tr>
      <th>сила</th><th>серия</th><th>име</th><th>z</th><th>peer breadth</th>
      <th>peer посока</th><th>дев.?</th><th>тагове</th>
    </tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</section>
"""


def _render_anomalies_feed(anomaly_report, snapshot: dict | None = None) -> str:
    if not anomaly_report.top:
        return """
<section class="brief-section">
  <h2>Top Anomalies</h2>
  <p class="muted">Няма серии с |z|>2 в момента.</p>
</section>
"""
    rows = []
    for i, a in enumerate(anomaly_report.top, 1):
        new_ext = (f"<span class='ne'>NEW 5Y {a.new_extreme_direction.upper()}</span>"
                   if a.is_new_extreme and a.new_extreme_direction else "")

        # Smart value + Δ (1 period back) — display-by-type-aware
        meta = SERIES_CATALOG.get(a.series_key, {})
        kind = change_kind(a.series_key, meta)
        value_cell = fmt_value(a.last_value, digits=2 if kind == "absolute" else 3)

        delta_cell = "—"
        if snapshot is not None:
            s = snapshot.get(a.series_key)
            if s is not None and not s.empty and len(s) >= 2:
                try:
                    delta_series = compute_change(s, kind, periods=1)
                    delta_cell = fmt_change(delta_series.iloc[-1], kind)
                except Exception:
                    pass

        rows.append(f"""
<tr>
  <td class="rank">{i}</td>
  <td>{_arrow(a.direction)}</td>
  <td>{render_series_ref(a.series_key, 'code-ref', EXPLORER_HREF)}{_revision_caveat(a.series_key)}</td>
  <td>{html.escape(a.series_name_bg)}</td>
  <td class="num">{value_cell}</td>
  <td class="num">{delta_cell}</td>
  <td class="num">{a.z_score:+.2f}</td>
  <td>{new_ext}</td>
  <td>{" / ".join(html.escape(l) for l in a.lens)}</td>
  <td>{html.escape(a.peer_group)}</td>
</tr>
""")
    return f"""
<section class="brief-section">
  <h2>Top Anomalies ({len(anomaly_report.top)}/{anomaly_report.total_flagged})</h2>
  <table class="anom-table">
    <thead><tr>
      <th>#</th><th></th><th>серия</th><th>име</th>
      <th>стойност</th><th>Δ</th><th>z</th>
      <th>5Y екстремум</th><th>lens</th><th>peer group</th>
    </tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</section>
"""


def _render_journal(entries: list[Any]) -> str:
    """Секция 'Свързани бележки' — link-ове към journal записи.

    Всяка бележка става row с: дата, topic badge, заглавие, статус, тагове.
    Очаква entries да е вече filtered + sorted (newest first, ≤5 items).
    """
    STATUS_LABELS = {
        "open_question": "Отворен въпрос",
        "hypothesis":    "Хипотеза",
        "finding":       "Извод",
        "decision":      "Решение",
    }
    TOPIC_LABELS = {
        "labor":       "Трудов пазар",
        "inflation":   "Инфлация",
        "credit":      "Кредит",
        "growth":      "Растеж",
        "analogs":     "Аналози",
        "regime":      "Режими",
        "methodology": "Методология",
    }

    rows = []
    for e in entries:
        topic_label = TOPIC_LABELS.get(e.topic, e.topic)
        status_label = STATUS_LABELS.get(e.status, e.status)
        tags_html = ""
        if e.tags:
            tags_html = " · ".join(
                f'<code class="journal-tag">{html.escape(str(t))}</code>' for t in e.tags[:4]
            )
        # Relative link — предполагаме, че briefing-ът е в output/ и
        # journal-ът е на ../journal/... спрямо него.
        rel = str(e.relative_path).replace("\\", "/")
        href = f"../{rel}"
        rows.append(f"""
      <li class="journal-item">
        <div class="journal-meta">
          <span class="journal-date">{e.date.isoformat()}</span>
          <span class="journal-topic">{html.escape(topic_label)}</span>
          <span class="journal-status journal-status-{html.escape(e.status)}">{html.escape(status_label)}</span>
        </div>
        <a class="journal-link" href="{html.escape(href)}">{html.escape(e.title)}</a>
        {'<div class="journal-tags">' + tags_html + '</div>' if tags_html else ''}
      </li>""")

    return f"""
<section class="brief-section journal-section">
  <h2>📓 Свързани бележки</h2>
  <p class="muted journal-caveat">
    Автоматично подбрани journal записи, релевантни за текущия режим
    и активните аномалии. Пълен списък: <a href="../journal/README.md">journal/</a>.
  </p>
  <ul class="journal-list">{"".join(rows)}</ul>
</section>
"""


def _render_footer(as_of, today) -> str:
    return f"""
<footer class="brief-footer">
  <details class="methodology" open>
    <summary><strong>Методология — как да четеш този briefing</strong></summary>

    <h4>Breadth (% положителна момент)</h4>
    <p class="muted">
      <strong>Какво е:</strong> процент от сериите в peer group, чийто 1-периоден
      momentum е положителен. Дава синтетично „накъде клони групата като цяло".
    </p>
    <p class="muted">
      <strong>Пример:</strong> peer group <code>wage_dynamics</code> с 3 серии (AHE,
      ECIWAG, AWHNONAG) — ако 2 от 3-те имат положителна 1m промяна → breadth = 67%.
      Ако всички 3 — 100%. Ако нито една — 0%.
    </p>
    <p class="muted">
      <strong>Прагове:</strong> breadth &gt; 60% → „разширяване" · breadth &lt; 40% →
      „свиване" · между 40–60% → „смесено" · &lt;2 серии с данни → „insufficient_data".
    </p>
    <p class="muted">
      <strong>За малки peer groups (3 серии)</strong>: 1 серия flip = 33pp промяна.
      Не е грешка ако в WoW виждаш +67pp / +100pp — просто цялата група е сменила
      посока. За peer groups с 5–7 серии промените са по-плавни.
    </p>

    <h4>Z-score</h4>
    <p class="muted">
      Стандартизирана отдалеченост на текущата стойност от историческата средна
      (за прозорец от 5 години). <code>z = +2.0</code> означава „2 стандартни
      отклонения над нормата" — настъпва ~5% от времето в нормална дистрибуция.
      <code>|z|&gt;2</code> — флаг за „екстремна" стойност (раздел „Top Anomalies").
    </p>

    <h4>Тема блокове (Трудов пазар, Растеж, Инфлация, Ликвидност и кредит)</h4>
    <p class="muted">
      Всеки ред в таблицата е <strong>peer group</strong> в дадената тема:
    </p>
    <ul class="muted">
      <li><code>breadth ↑</code> — % положителен 1m момент в групата (виж по-горе).</li>
      <li><code>breadth |z|&gt;2</code> — % серии в групата с екстремен z-score.
          Идентифицира чисто-аномални peer groups.</li>
      <li><code>данни</code> — налични серии / каталожни членове (напр. 3/3 = пълно
          покритие, 4/5 = 1 серия липсва в snapshot-а).</li>
      <li><code>посока</code> — derived от breadth ↑ (виж праговете по-горе).</li>
      <li><code>екстремни членове</code> — линкове към exploreр-а за серии с |z|&gt;2.</li>
    </ul>

    <h4>Cross-Lens Divergence — двойките</h4>
    <p class="muted">
      Шест икономически тези, всяка съпоставя breadth между две slot-а (групи peer_groups).
      Възможни състояния:
    </p>
    <ul class="muted">
      <li><strong>↑↑ и двете нагоре</strong> (<code>both_up</code>) — A и B растат заедно.</li>
      <li><strong>↓↓ и двете надолу</strong> (<code>both_down</code>) — A и B спадат заедно.</li>
      <li><strong>↑↓ A нагоре / B надолу</strong> (<code>a_up_b_down</code>) — divergence.</li>
      <li><strong>↓↑ A надолу / B нагоре</strong> (<code>a_down_b_up</code>) — divergence.</li>
      <li><strong>⇄ преход</strong> (<code>transition</code>) — breadth-овете не пресичат
          ясно праговете 60/40% → смесени сигнали, изчакваме яснота.</li>
      <li><strong>недостатъчно данни</strong> — една от групите е под минималния праг.</li>
    </ul>
    <p class="muted">
      Под всяка двойка има конкретна интерпретация на текущото състояние
      (от каталога <code>cross_lens_pairs.py</code>). „Invert" флагът в slot-а
      означава, че breadth се обръща (напр. unemployment ↑ = labor weakening, инвертирано
      на „labor tightness").
    </p>

    <h4>Top Anomalies</h4>
    <p class="muted">
      Серии с <code>|z|&gt;2</code> сортирани по абсолютна сила. Колоните „стойност"
      и „Δ" са в типично-подходящи единици: <strong>bps</strong> за rate-нива
      (BREAKEVEN, UST, OAS, FED_FUNDS), <strong>абсолютна делта</strong> за signed
      индекси (NFCI, CFNAI, UMCSENT), <strong>%</strong> за price levels (CPI,
      payrolls). Това избягва подвеждащи % промени за rate-нива близки до нула.
    </p>

    <h4>Week-over-Week (WoW)</h4>
    <p class="muted">
      Сравнение с briefing snapshot от <strong>≥5 дни назад</strong> — типично
      хваща предишната календарна седмица. Ако пускаш briefing вторник, ще видиш
      промени от предходния понеделник (или най-близкия по-стар запис). Snapshot-овете
      се пазят в <code>data/state/briefing_YYYY-MM-DD.json</code>.
    </p>

    <h4>Non-consensus</h4>
    <p class="muted">
      Серии маркирани с tag <code>non_consensus</code> в каталога, които към момента
      имат <code>|z|&gt;2</code> ИЛИ голяма дистанция от breadth-а на peer group-а
      (deviation).Mainstream narrative-ът обикновено им обръща по-малко внимание.
    </p>
  </details>

  <p class="muted brief-meta">
    Всички изчисления са детерминистични — няма LLM нарация в самия briefing.
    <strong>Caveat:</strong> серии с <sup>†</sup> подлежат на ревизии (изчакай
    2–3 релиза за потвърждение преди тезен избор).
    As_of: {html.escape(as_of or '—')} · Today: {today.isoformat()}.
  </p>
</footer>
"""


# ============================================================
# HELPERS
# ============================================================

def _arrow(direction: str) -> str:
    return "<span class='arrow up'>↑</span>" if direction == "up" else "<span class='arrow down'>↓</span>"


def _fmt_breadth(v) -> str:
    if v is None:
        return "—"
    try:
        if v != v:  # NaN check
            return "—"
    except TypeError:
        return "—"
    return f"{v:.0%}"


def _state_class(state: str) -> str:
    mapping = {
        "both_up": "state-up-up",
        "both_down": "state-dn-dn",
        "a_up_b_down": "state-mixed",
        "a_down_b_up": "state-mixed",
        "transition": "state-trans",
        "insufficient_data": "state-ins",
    }
    return mapping.get(state, "state-trans")


def _direction_class(direction: str) -> str:
    mapping = {
        "expanding": "dir-up",
        "contracting": "dir-dn",
        "mixed": "dir-mix",
        "insufficient_data": "dir-ins",
    }
    return mapping.get(direction, "dir-mix")


def _revision_caveat(series_key: str) -> str:
    meta = SERIES_CATALOG.get(series_key, {})
    if meta.get("revision_prone"):
        return "<sup class='revision-mark' title='подлежи на ревизии'>†</sup>"
    return ""


def render_series_ref(
    series_key: str,
    extra_classes: str = "",
    href_prefix: str = "",
) -> str:
    """Обгръща серийния код с hover-tooltip от каталожните metadata.

    Tooltip показва: name_bg (bold), FRED id · source · region, Lens, Peer,
    Tags (ако има), revision caveat (ако е revision_prone), narrative_hint.

    Рендира се като ``<a href="{prefix}#{key}">`` — клик отвежда към
    detail-секцията в explorer.html (или в същия файл, ако prefix е празен).
    При неизвестен ключ — рендира се само кода в ``<span>`` без tooltip/линк.

    Args:
        series_key: каталожен ключ (например "UNRATE").
        extra_classes: допълнителни CSS класове ("code-ref" или "ext-mark").
        href_prefix: префикс за href атрибута. Празен низ → same-page ("#KEY").
            В briefing-а: подаваме "explorer.html"; в explorer-а: "".

    Returns:
        HTML низ.
    """
    key_esc = html.escape(series_key)
    meta = SERIES_CATALOG.get(series_key)
    if meta is None:
        cls = ("series-ref-unknown " + extra_classes).strip()
        return f'<span class="{cls}">{key_esc}</span>'

    name_bg = meta.get("name_bg") or series_key
    fred_id = meta.get("id") or series_key
    source = (meta.get("source") or "").upper()
    region = meta.get("region") or ""
    lenses = " / ".join(meta.get("lens", []))
    peer_group = meta.get("peer_group") or ""
    tags = meta.get("tags") or []
    hint = (meta.get("narrative_hint") or "").strip()
    revision_prone = bool(meta.get("revision_prone"))

    # ID ред — само non-empty парчета
    id_parts = [p for p in [fred_id, source, region] if p]
    id_line = " · ".join(id_parts)

    # Meta редове
    meta_html_parts: list[str] = [
        f'<span class="tooltip-meta">'
        f'<span class="tooltip-meta-label">Тема:</span> {html.escape(lenses) or "—"}</span>',
        f'<span class="tooltip-meta">'
        f'<span class="tooltip-meta-label">Peer:</span> {html.escape(peer_group) or "—"}</span>',
    ]
    if tags:
        meta_html_parts.append(
            f'<span class="tooltip-meta">'
            f'<span class="tooltip-meta-label">Тагове:</span> '
            f'{html.escape(" · ".join(tags))}</span>'
        )
    if revision_prone:
        meta_html_parts.append(
            '<span class="tooltip-meta tooltip-revision">'
            '<span class="tooltip-meta-label">Ревизии:</span> '
            'да (†)</span>'
        )

    hint_html = (
        f'<span class="tooltip-hint">{html.escape(hint)}</span>' if hint else ""
    )

    cls = ("series-ref " + extra_classes).strip()
    href = f'{html.escape(href_prefix)}#{key_esc}'
    return (
        f'<a class="{cls}" data-key="{key_esc}" href="{href}">'
        f'{key_esc}'
        f'<span class="tooltip" role="tooltip">'
        f'<span class="tooltip-title">{html.escape(name_bg)}</span>'
        f'<span class="tooltip-id">{html.escape(id_line)}</span>'
        f'{"".join(meta_html_parts)}'
        f'{hint_html}'
        f'</span>'
        f'</a>'
    )


# Backwards-compat alias — вътрешни тестове ползваха _render_series_ref
_render_series_ref = render_series_ref


def _pick_as_of(lens_reports, cross_report, anomaly_report) -> Optional[str]:
    candidates = []
    for r in lens_reports.values():
        if r.as_of:
            candidates.append(r.as_of)
    if cross_report.as_of:
        candidates.append(cross_report.as_of)
    if anomaly_report.as_of:
        candidates.append(anomaly_report.as_of)
    if not candidates:
        return None
    return max(candidates)  # ISO дати се сортират като низове правилно


# ============================================================
# HTML SKELETON + CSS
# ============================================================

def _skeleton(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="bg">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<main class="brief-main">
{body}
</main>
</body>
</html>"""


_CSS = """
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  margin: 0; padding: 0;
  background: #f8f9fa;
  color: #1a1a1a;
  line-height: 1.5;
}
.brief-main { max-width: 1100px; margin: 0 auto; padding: 28px 24px 60px; }

/* Header */
.brief-header {
  display: flex; justify-content: space-between; align-items: flex-end;
  border-bottom: 2px solid #222; padding-bottom: 14px; margin-bottom: 24px;
  flex-wrap: wrap; gap: 16px;
}
.brief-title h1 { margin: 0; font-size: 26px; font-weight: 600; }
.brief-subtitle { color: #666; font-size: 13px; margin-top: 4px; }
.brief-kpis { display: flex; gap: 14px; }
.kpi {
  background: #fff; border: 1px solid #e0e0e0; border-radius: 6px;
  padding: 8px 14px; text-align: center; min-width: 84px;
}
.kpi-n { font-size: 22px; font-weight: 600; color: #222; }
.kpi-l { font-size: 10.5px; color: #777; text-transform: uppercase; letter-spacing: 0.5px; }

/* Sections */
.brief-section { margin-bottom: 36px; }
.brief-section h2 {
  font-size: 17px; text-transform: uppercase; letter-spacing: 1px;
  color: #333; border-bottom: 1px solid #ddd; padding-bottom: 6px; margin: 0 0 14px;
}
.brief-section h4 { font-size: 12.5px; text-transform: uppercase; color: #666; letter-spacing: 0.7px; margin: 0 0 8px; }

/* Cross-lens pairs */
.pair-wrap { display: grid; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); gap: 14px; }
.pair-card {
  background: #fff; border: 1px solid #e0e0e0; border-radius: 8px;
  padding: 14px 16px;
}
.pair-head { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.pair-head h3 { margin: 0; font-size: 14.5px; font-weight: 600; }
.pair-state { font-size: 10.5px; padding: 3px 8px; border-radius: 4px; font-weight: 600; white-space: nowrap; }
.state-up-up { background: #fee; color: #a03030; }        /* both up — often inflationary/tight */
.state-dn-dn { background: #e8f2ff; color: #2050a0; }     /* both down — cooling */
.state-mixed { background: #fff5d6; color: #806020; }     /* divergent */
.state-trans { background: #eee; color: #555; }
.state-ins   { background: #f3f3f3; color: #999; }
.pair-question { font-size: 12.5px; color: #666; font-style: italic; margin-bottom: 10px; }
.pair-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px; }
.pair-slot { background: #fafafa; border: 1px solid #eee; border-radius: 5px; padding: 8px 10px; }
.pair-slot-label { font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }
.pair-slot-val { font-family: 'Consolas', 'Monaco', monospace; font-size: 18px; font-weight: 600; margin-top: 4px; color: #222; }
.pair-slot-n { font-size: 10.5px; color: #999; }
.pair-interp { background: #fafafa; border-left: 3px solid #999; padding: 8px 12px; font-size: 13px; color: #333; }

/* Lens blocks */
.lens-block h2 { color: #222; }
.breadth-table, .nc-table, .anom-table { width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e0e0e0; font-size: 13px; margin-bottom: 14px; }
.breadth-table th, .breadth-table td,
.nc-table th, .nc-table td,
.anom-table th, .anom-table td { padding: 7px 10px; text-align: left; border-bottom: 1px solid #eee; vertical-align: middle; }
.breadth-table th, .nc-table th, .anom-table th { background: #fafafa; color: #555; font-weight: 500; font-size: 11.5px; text-transform: uppercase; letter-spacing: 0.5px; }
.num { font-family: 'Consolas', 'Monaco', monospace; text-align: right; }
.pg-name { font-weight: 500; }
.dir-badge { font-size: 11px; padding: 2px 8px; border-radius: 3px; font-weight: 500; }
.dir-up  { background: #e6f4ea; color: #1e6b30; }
.dir-dn  { background: #fdeaea; color: #a02020; }
.dir-mix { background: #fff5d6; color: #806020; }
.dir-ins { background: #f1f1f1; color: #888; }
.ext-mark { display: inline-block; background: #fff3d6; border: 1px solid #e8c97a; color: #806020; padding: 1px 6px; border-radius: 3px; font-size: 10.5px; font-family: monospace; margin-right: 4px; }
.extremes { max-width: 260px; }
.muted { color: #888; font-style: italic; font-size: 13px; }

.lens-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.lens-grid > div { background: #fff; border: 1px solid #e8e8e8; border-radius: 6px; padding: 12px 14px; }
.lens-grid ul, .lens-grid ol { margin: 0; padding-left: 18px; }
.lens-grid li { font-size: 13px; margin-bottom: 4px; }
.diff { color: #666; font-family: monospace; margin-left: 6px; }

/* Non-consensus signals */
.sig-badge { display: inline-block; font-size: 10.5px; padding: 2px 7px; border-radius: 3px; font-weight: 600; }
.sig-high   { background: #fee; color: #a03030; }
.sig-medium { background: #fff5d6; color: #806020; }
.sig-low    { background: #f3f3f3; color: #888; }
tr.sig-high { background: #fff8f8; }
.tag { display: inline-block; font-size: 10.5px; padding: 1px 6px; border-radius: 3px; margin-right: 3px; background: #eef; color: #3060a0; font-family: monospace; }
.tag-ai_exposure { background: #f3e8ff; color: #6030a0; }
.tag-structural  { background: #e8f5e8; color: #306030; }

/* Anomalies */
.rank { color: #999; font-family: monospace; }
.arrow { font-family: monospace; font-weight: 600; }
.arrow.up { color: #1e6b30; }
.arrow.down { color: #a02020; }
.ne { display: inline-block; background: #ffeedd; color: #a05020; font-size: 10.5px; padding: 1px 6px; border-radius: 3px; font-weight: 600; margin-left: 4px; font-family: monospace; }
.z { font-family: monospace; color: #555; margin: 0 6px; }
.pg { color: #888; font-size: 12px; margin-left: 4px; }

code { font-family: 'Consolas', 'Monaco', monospace; background: #f4f4f4; padding: 1px 5px; border-radius: 3px; font-size: 12.5px; }
sup.revision-mark { color: #a06020; cursor: help; margin-left: 2px; }

.brief-footer { border-top: 1px solid #ddd; padding-top: 16px; margin-top: 30px; font-size: 12px; color: #666; }
.brief-footer p { margin: 6px 0; }

/* Executive Summary */
.exec-section { background: #fff; border: 1px solid #d4d9e0; border-radius: 8px; padding: 18px 20px; }
.exec-section h2 { margin-top: 0; }
.exec-headline { display: grid; grid-template-columns: minmax(180px, 260px) 1fr; gap: 18px; align-items: start; margin-bottom: 14px; }
.regime-badge {
  padding: 12px 14px; border-radius: 6px; text-align: center;
  border: 1px solid currentColor;
}
.regime-badge .regime-label { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.6px; opacity: 0.75; }
.regime-badge .regime-val { font-size: 18px; font-weight: 700; margin: 4px 0 6px; line-height: 1.25; }
.regime-badge .regime-driver { font-size: 10.5px; opacity: 0.6; font-family: monospace; }
.regime-stag   { background: #fdecec; color: #8a2020; }
.regime-soft   { background: #e9f5ee; color: #1e6b30; }
.regime-cool   { background: #e8f2ff; color: #2050a0; }
.regime-dilem  { background: #fff2e0; color: #8a4010; }
.regime-exp    { background: #e6f4ea; color: #1e6b30; }
.regime-slow   { background: #f3e8ff; color: #6030a0; }
.regime-stress { background: #fee0e0; color: #a02020; }
.regime-trans  { background: #f1f1f1; color: #555; }
.exec-narrative {
  background: #fafbfc; border-left: 3px solid #888; padding: 10px 14px;
  font-size: 14px; line-height: 1.55; color: #222;
}
.exec-grid { display: grid; grid-template-columns: minmax(340px, 1fr) 1fr; gap: 16px; align-items: start; }
.regime-table { width: 100%; border-collapse: collapse; font-size: 13px; background: #fff; }
.regime-table th, .regime-table td { padding: 7px 10px; text-align: left; border-bottom: 1px solid #eee; }
.regime-table th { background: #fafafa; color: #555; font-weight: 500; font-size: 11.5px; text-transform: uppercase; letter-spacing: 0.5px; }
.ne-inline { display: inline-block; background: #ffeedd; color: #a05020; font-size: 10px; padding: 1px 5px; border-radius: 3px; font-weight: 600; margin-left: 4px; font-family: monospace; }
.exec-signals { background: #fafbfc; border: 1px solid #e8e8e8; border-radius: 6px; padding: 10px 14px; }
.exec-signals h4 { margin: 0 0 6px; }
.exec-signals ul { margin: 0; padding-left: 18px; }
.exec-signals li { font-size: 12.5px; margin-bottom: 3px; }
@media (max-width: 760px) {
  .exec-headline, .exec-grid { grid-template-columns: 1fr; }
}

/* Week-over-Week delta */
.delta-section { background: #f7f9fc; border: 1px solid #d4dbe4; border-radius: 8px; padding: 14px 18px; }
.delta-section .delta-since { font-size: 12px; color: #888; text-transform: none; letter-spacing: 0; font-weight: normal; }
.delta-regime {
  background: #fff3cd; border: 1px solid #e0c060; color: #805020;
  padding: 10px 14px; border-radius: 6px; margin-bottom: 12px; font-size: 14px;
}
.delta-regime .delta-label { font-weight: 600; margin-right: 8px; }
.delta-regime .delta-arrow { font-family: monospace; }
.delta-block { margin: 10px 0; }
.delta-block h4 { font-size: 12px; text-transform: uppercase; color: #666; margin: 0 0 6px; }
.delta-block ul { margin: 0; padding-left: 18px; font-size: 13px; }
.delta-block li { margin-bottom: 3px; }
.state-from { color: #888; font-family: monospace; }
.state-to { font-family: monospace; color: #222; }
.delta-pp { font-family: monospace; margin-left: 6px; font-weight: 600; padding: 0 4px; border-radius: 3px; }
.delta-pp.up { background: #e6f4ea; color: #1e6b30; }
.delta-pp.down { background: #fdeaea; color: #a02020; }
.delta-pp.flat { color: #888; }
.delta-tag { display: inline-block; font-size: 10.5px; padding: 1px 7px; border-radius: 3px; font-weight: 600; margin-right: 4px; }
.delta-tag.new { background: #ddeeff; color: #2050a0; }
.delta-tag.gone { background: #f1f1f1; color: #888; }
.ref-vanished { background: #f4f4f4; color: #888; text-decoration: line-through; font-family: monospace; font-size: 12.5px; padding: 1px 5px; border-radius: 3px; }

/* Threshold flags banner */
.flags-banner {
  margin: 14px 0;
  border: 1px solid #d4a040;
  border-radius: 6px;
  background: #fff8e8;
  padding: 10px 14px;
}
.flags-banner-head {
  font-weight: 600;
  color: #805020;
  margin-bottom: 8px;
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.flag-item {
  padding: 8px 12px;
  border-radius: 4px;
  margin-bottom: 6px;
  background: #fff;
}
.flag-item:last-child { margin-bottom: 0; }
.flag-red {
  background: #fdecec;
  border-left: 3px solid #a02020;
}
.flag-amber {
  background: #fff5d6;
  border-left: 3px solid #d4a040;
}
.flag-sev {
  display: inline-block;
  font-weight: 700;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 3px;
  margin-right: 8px;
  letter-spacing: 0.5px;
}
.flag-red .flag-sev { background: #a02020; color: #fff; }
.flag-amber .flag-sev { background: #d4a040; color: #fff; }
.flag-label { font-weight: 600; margin-right: 8px; font-size: 13px; }
.flag-val { font-family: 'Consolas', 'Monaco', monospace; font-size: 12px; color: #333; }
.flag-msg { font-size: 12.5px; color: #555; margin-top: 5px; line-height: 1.45; }

/* Falsification criteria block */
.exec-falsifiers {
  margin-top: 14px;
  background: #fafbfc;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  padding: 10px 14px;
}
.exec-falsifiers h4 {
  margin: 0 0 6px;
  color: #555;
}
.exec-falsifiers ul {
  margin: 0;
  padding-left: 18px;
}
.exec-falsifiers li {
  font-size: 12.5px;
  color: #333;
  margin-bottom: 3px;
  line-height: 1.5;
}

/* ============================================================
   Series references with pure-CSS hover tooltip
   ============================================================ */
.series-ref {
  position: relative;
  border-bottom: 1px dotted #888;
  cursor: help;
  color: inherit;
  text-decoration: none;
}
.series-ref:hover { color: inherit; }
.series-ref.code-ref {
  font-family: 'Consolas', 'Monaco', monospace;
  background: #f4f4f4;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 12.5px;
}
.series-ref.ext-mark {
  display: inline-block;
  border-bottom: 1px solid #e8c97a;   /* override dotted от .series-ref */
}
.series-ref-unknown {
  font-family: 'Consolas', 'Monaco', monospace;
  background: #f4f4f4;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 12.5px;
  color: #888;
}
.series-ref .tooltip {
  display: none;
  position: absolute;
  bottom: calc(100% + 6px);
  left: 50%;
  transform: translateX(-50%);
  z-index: 1000;
  width: 280px;
  background: #fff;
  border: 1px solid #bbb;
  border-radius: 6px;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.18);
  padding: 10px 13px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-size: 12px;
  font-weight: 400;
  font-style: normal;
  color: #222;
  text-align: left;
  text-transform: none;
  letter-spacing: normal;
  line-height: 1.5;
  white-space: normal;
  pointer-events: none;
}
.series-ref:hover .tooltip { display: block; }
.series-ref .tooltip > span { display: block; }
.tooltip-title { font-weight: 600; font-size: 13px; color: #111; margin-bottom: 2px; }
.tooltip-id { font-family: 'Consolas', 'Monaco', monospace; font-size: 10.5px; color: #777; margin-bottom: 8px; }
.tooltip-meta { font-size: 11.5px; color: #333; margin: 2px 0; }
.tooltip-meta-label { color: #888; display: inline-block; min-width: 52px; font-weight: 500; }
.tooltip-revision .tooltip-meta-label { color: #a06020; }
.tooltip-hint { font-size: 11.5px; color: #444; margin-top: 8px; padding-top: 8px; border-top: 1px solid #eee; font-style: italic; line-height: 1.5; }

/* ============================================================
   Historical Analog section
   ============================================================ */
.analog-section { }
.analog-current {
  background: #f7f8fc;
  border: 1px solid #dee2ed;
  border-radius: 6px;
  padding: 12px 16px;
  margin-bottom: 16px;
}
.analog-current-head {
  font-size: 13px;
  font-weight: 600;
  color: #3a3f52;
  margin-bottom: 8px;
}
.analog-dim-grid {
  display: grid;
  grid-template-columns: repeat(8, minmax(0, 1fr));
  gap: 8px;
}
.analog-dim {
  background: #fff;
  border: 1px solid #e4e6f0;
  border-radius: 4px;
  padding: 6px 8px;
  text-align: center;
}
.analog-dim-label {
  font-size: 10.5px;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}
.analog-dim-val {
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 13px;
  font-weight: 600;
  color: #222;
  margin-top: 2px;
}
.analog-dim-z {
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 10.5px;
  color: #777;
  margin-top: 1px;
}
.analog-wrap {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}
.analog-card {
  background: #fff;
  border: 1px solid #dfe0e6;
  border-radius: 8px;
  padding: 12px 14px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.analog-strength-strong { border-left: 4px solid #2d7a4b; }
.analog-strength-good   { border-left: 4px solid #6b9a4b; }
.analog-strength-weak   { border-left: 4px solid #b99a3a; }
.analog-strength-marginal { border-left: 4px solid #b05050; }
.analog-card-head {
  display: grid;
  grid-template-columns: auto auto 1fr auto;
  gap: 10px;
  align-items: center;
  border-bottom: 1px solid #eee;
  padding-bottom: 8px;
  margin-bottom: 10px;
}
.analog-rank {
  font-size: 16px;
  font-weight: 700;
  color: #556080;
}
.analog-date {
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 14px;
  color: #333;
}
.analog-episode {
  font-size: 12.5px;
  color: #444;
  font-style: italic;
}
.analog-sim {
  text-align: right;
}
.analog-sim-val {
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 15px;
  font-weight: 700;
  color: #2d4a7a;
}
.analog-sim-lbl {
  font-size: 10.5px;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}
.analog-card-body h5 {
  margin: 10px 0 4px;
  font-size: 12px;
  color: #555;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}
.analog-card-body ul {
  margin: 0 0 6px;
  padding-left: 18px;
  list-style: none;
}
.analog-card-body li {
  font-size: 12.5px;
  color: #333;
  margin-bottom: 3px;
  padding-left: 12px;
  position: relative;
}
.analog-card-body li::before {
  content: "·";
  position: absolute;
  left: 0;
  color: #888;
  font-weight: 700;
}
.analog-num {
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  color: #111;
}
.analog-z {
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 11px;
  color: #777;
  margin-left: 4px;
}
.analog-z-div { color: #a06030; font-weight: 600; }
.analog-div-block { margin-top: 6px; }
.analog-forward {
  margin-top: 10px;
  border-top: 1px solid #eee;
  padding-top: 8px;
}
.analog-fw-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.analog-fw-table th,
.analog-fw-table td {
  padding: 4px 6px;
  border-bottom: 1px solid #f0f0f0;
  text-align: left;
}
.analog-fw-table th {
  color: #666;
  font-weight: 600;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}
.analog-fw-table td.num,
.analog-fw-table th.num {
  text-align: right;
  font-family: 'Consolas', 'Monaco', monospace;
}
.analog-delta {
  color: #888;
  font-size: 10.5px;
  margin-left: 2px;
}
.analog-n {
  color: #aaa;
  font-size: 10.5px;
  margin-left: 3px;
}
.analog-aggregate {
  background: #fbfbfd;
  border: 1px solid #e5e6ee;
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 12px;
}
.analog-aggregate h4 {
  margin: 0 0 8px;
  font-size: 13px;
  color: #444;
}
.analog-caveat {
  background: #fff7ed;
  border-left: 3px solid #d4a040;
  padding: 8px 12px;
  font-size: 12px;
  color: #5a4a20;
  line-height: 1.5;
  border-radius: 0 4px 4px 0;
}

/* ─── Journal section ─────────────────────────────────────── */
.journal-section { }
.journal-caveat {
  margin-top: -6px;
  margin-bottom: 12px;
}
.journal-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.journal-item {
  padding: 10px 12px;
  background: #fafaf7;
  border: 1px solid #e2e2d8;
  border-radius: 4px;
}
.journal-meta {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 4px;
  font-size: 12px;
}
.journal-date {
  color: #6b6b5e;
  font-family: ui-monospace, 'SF Mono', Menlo, monospace;
}
.journal-topic {
  color: #3a3a32;
  font-weight: 500;
}
.journal-status {
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
}
.journal-status-open_question { background: #fef3c7; color: #78350f; }
.journal-status-hypothesis { background: #e0e7ff; color: #312e81; }
.journal-status-finding { background: #dcfce7; color: #14532d; }
.journal-status-decision { background: #fce7f3; color: #831843; }
.journal-link {
  display: block;
  font-weight: 500;
  color: #1a1a16;
  text-decoration: none;
  font-size: 14px;
  line-height: 1.4;
}
.journal-link:hover {
  text-decoration: underline;
}
.journal-tags {
  margin-top: 4px;
  font-size: 11px;
  color: #6b6b5e;
}
.journal-tag {
  background: #f0f0e8;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 10px;
}

@media (max-width: 760px) {
  .lens-grid { grid-template-columns: 1fr; }
  .pair-grid { grid-template-columns: 1fr; }
  .brief-kpis { width: 100%; }
  .series-ref .tooltip { width: 240px; }
  .analog-dim-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .analog-wrap { grid-template-columns: 1fr; }
}
"""
