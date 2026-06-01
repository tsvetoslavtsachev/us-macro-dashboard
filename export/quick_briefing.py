"""Quick briefing — China-style scoreboard за бърз поглед.

Генерира compact HTML с:
  - Композитен macro score (0-100, mean от lens breadth_agg)
  - Regime badge от executive snapshot
  - Per-lens score bars (breadth_agg на всеки lens)
  - Кратък narrative bullets (top-level signals)

Не дублира compute logic — внасря existing analysis functions от deep
briefing. Цел: дай headline за 30 секунди (commute / mobile / screenshot).
За подробен анализ — виж `weekly_briefing.py` (Executive Summary,
Cross-Lens, Modules, Top Anomalies).
"""
from __future__ import annotations

import html as _html
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

from analysis.executive import (
    LENS_LABEL_BG,
    REGIME_CSS_CLASS,
    REGIME_LABELS_BG,
    compute_executive_summary,
)
# NB: импортираме LENS_ORDER от weekly_briefing (single source of truth),
# за да не drift-ваме от deep briefing-а
from export.weekly_briefing import LENS_ORDER
from analysis.breadth import compute_lens_breadth
from analysis.divergence import compute_cross_lens_divergence
from analysis.anomaly import compute_anomalies
from analysis.non_consensus import compute_non_consensus


LENS_ICON = {
    "labor": "👷",
    "growth": "📈",
    "inflation": "🔥",
    "liquidity": "🏦",
    "housing": "🏗️",
    "credit": "💳",
    "fed": "🏛",
    "consumer": "🛒",
}

# Score thresholds (синхронно с China-style цветове)
SCORE_RED = 35.0   # < 35 → червен (свиване / стрес)
SCORE_GREEN = 65.0  # > 65 → зелен (експанзия)
# Между двата → жълт


def _score_color(score: float) -> str:
    """Hex color по score band."""
    if score is None or pd.isna(score):
        return "#8b949e"  # сив
    if score < SCORE_RED:
        return "#f85149"  # red
    if score > SCORE_GREEN:
        return "#3fb950"  # green
    return "#d29922"  # amber


def _regime_badge_colors(regime_key: str) -> tuple[str, str, str]:
    """Връща (bg, fg, border) hex цветове за regime badge."""
    css = REGIME_CSS_CLASS.get(regime_key, "regime-trans")
    palette = {
        "regime-stag": ("#d5000022", "#f85149", "#d5000044"),     # red-ish (stagflation)
        "regime-soft": ("#3fb95022", "#3fb950", "#3fb95044"),     # green (soft landing)
        "regime-cool": ("#58a6ff22", "#58a6ff", "#58a6ff44"),     # blue (disinflation)
        "regime-dilem": ("#d2992222", "#d29922", "#d2992244"),    # amber (dilemma)
        "regime-exp": ("#3fb95022", "#3fb950", "#3fb95044"),      # green (expansion)
        "regime-slow": ("#d2992222", "#d29922", "#d2992244"),     # amber (slowdown)
        "regime-stress": ("#d5000022", "#f85149", "#d5000044"),   # red (credit stress)
        "regime-trans": ("#8b949e22", "#8b949e", "#8b949e44"),    # gray (transition)
    }
    return palette.get(css, palette["regime-trans"])


def _composite_score(exec_snapshot) -> float:
    """Mean breadth_agg × 100 от lens_rows (skip-ва None стойностите)."""
    vals = [
        r.breadth_agg for r in exec_snapshot.lens_rows
        if r.breadth_agg is not None and not pd.isna(r.breadth_agg)
    ]
    if not vals:
        return float("nan")
    return sum(vals) / len(vals) * 100.0


def _lens_score(lens_row) -> float:
    """breadth_agg × 100 за един lens row."""
    if lens_row.breadth_agg is None or pd.isna(lens_row.breadth_agg):
        return float("nan")
    return float(lens_row.breadth_agg) * 100.0


def _direction_label(direction: str) -> str:
    """ Bulgarian label за direction."""
    return {
        "expanding": "ЕКСПАНЗИЯ",
        "contracting": "СВИВАНЕ",
        "mixed": "СМЕСЕН",
        "insufficient_data": "ЛИПСА",
    }.get(direction, direction.upper())


def _direction_colors(direction: str) -> tuple[str, str, str]:
    """(bg, fg, border) за direction badge."""
    return {
        "expanding": ("#3fb95022", "#3fb950", "#3fb95044"),
        "contracting": ("#d5000022", "#f85149", "#d5000044"),
        "mixed": ("#d2992222", "#d29922", "#d2992244"),
        "insufficient_data": ("#8b949e22", "#8b949e", "#8b949e44"),
    }.get(direction, ("#8b949e22", "#8b949e", "#8b949e44"))


def _state_colors(state: str) -> tuple[str, str]:
    """(hex, BG label) за cross-lens divergence state."""
    return {
        "both_up": ("#3fb950", "Двете нагоре"),
        "both_down": ("#f85149", "Двете надолу"),
        "a_up_b_down": ("#d29922", "Разнопосочни"),
        "a_down_b_up": ("#d29922", "Разнопосочни"),
        "transition": ("#8b949e", "Преход"),
        "insufficient_data": ("#8b949e", "Липса данни"),
    }.get(state, ("#8b949e", state or "—"))


def _fmt_breadth(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v * 100:.0f}%"


def _render_cross_lens_section(cross_report) -> str:
    """Cross-Lens Divergence — China-style pair cards (inline-styled, self-contained)."""
    pairs = getattr(cross_report, "pairs", None) or []
    if not pairs:
        return ""
    cards = []
    for p in pairs:
        color, state_lbl = _state_colors(getattr(p, "state", "") or "")
        name = _html.escape(getattr(p, "name_bg", "") or "")
        interp = _html.escape(getattr(p, "interpretation", "") or "")
        a_lbl = _html.escape(getattr(p, "slot_a_label", "") or "")
        b_lbl = _html.escape(getattr(p, "slot_b_label", "") or "")
        cards.append(f"""
        <div style="background:#0d1117;border:1px solid #30363d;border-left:3px solid {color};border-radius:8px;padding:14px 16px;margin-bottom:10px">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:6px">
            <span style="color:#f0f6fc;font-size:14px;font-weight:600">{name}</span>
            <span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px;background:{color}22;color:{color};border:1px solid {color}44;white-space:nowrap">{state_lbl}</span>
          </div>
          <div style="display:flex;gap:16px;margin-bottom:6px;flex-wrap:wrap">
            <span style="color:#8b949e;font-size:12px">{a_lbl}: <b style="color:#c9d1d9">{_fmt_breadth(getattr(p, 'breadth_a', None))}</b></span>
            <span style="color:#8b949e;font-size:12px">{b_lbl}: <b style="color:#c9d1d9">{_fmt_breadth(getattr(p, 'breadth_b', None))}</b></span>
          </div>
          <div style="color:#8b949e;font-size:12px;line-height:1.5">{interp}</div>
        </div>""")
    return f"""
    <div class="lens-bars">
      <h3>Cross-Lens Divergence</h3>
      {''.join(cards)}
    </div>"""


def _render_anomalies_section(anomaly_report) -> str:
    """Top Anomalies — China-style таблица (inline-styled)."""
    top = getattr(anomaly_report, "top", None) or []
    if not top:
        return ""
    total = getattr(anomaly_report, "total_flagged", len(top))
    rows = []
    for a in top[:10]:
        z = getattr(a, "z_score", 0) or 0.0
        zc = "#f85149" if z > 0 else "#58a6ff"
        d = getattr(a, "direction", "") or ""
        arrow = "▲" if d == "up" else ("▼" if d == "down" else "•")
        name = _html.escape(getattr(a, "series_name_bg", "") or getattr(a, "series_key", "") or "")
        sid = _html.escape(getattr(a, "series_key", "") or "")
        ext = ""
        if getattr(a, "is_new_extreme", False):
            ed = (getattr(a, "new_extreme_direction", "") or "").upper()
            ext = f' <span style="color:#d29922;font-size:10px;font-weight:700">NEW-{ed}</span>'
        rows.append(f"""
        <tr style="border-bottom:1px solid #21262d">
          <td style="padding:7px 8px;color:#e6edf3;font-size:13px">{name}{ext}<div style="color:#8b949e;font-size:10px">{sid}</div></td>
          <td style="padding:7px 8px;text-align:right;font-weight:700;color:{zc};font-size:13px;white-space:nowrap">{arrow} {z:+.2f}σ</td>
        </tr>""")
    return f"""
    <div class="lens-bars">
      <h3>Top Anomalies ({len(top)}/{total})</h3>
      <table style="width:100%;border-collapse:collapse">{''.join(rows)}</table>
    </div>"""


def _render_data_quality_section() -> str:
    return """
    <div class="lens-bars">
      <h3>Бележки за данните</h3>
      <div style="color:#8b949e;font-size:12px;line-height:1.6">
        Композитът е mean breadth_positive × 100 на наличните lens-ове. Z-score за аномалиите е спрямо 5-годишен прозорец (|z|&gt;2 = екстремно четене спрямо peer групата). Месечните серии се движат по-бавно от седмичните. За пълния анализ (executive summary, WoW delta, falsifiers, исторически аналози, journal) виж подробния briefing.
      </div>
    </div>"""


def _fmt_val(v, decimals: int = 2) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    try:
        return f"{float(v):.{decimals}f}"
    except Exception:
        return str(v)


def _lens_readings(lens: str, snapshot: dict, top_n: int = 5) -> list[dict]:
    """Top серии в лещата по |z|, със стойност/percentile/дата (China-style readings)."""
    from catalog.series import series_by_lens
    from core.scorer import score_series

    rows = []
    for meta in series_by_lens(lens):
        key = meta.get("_key")
        s = snapshot.get(key)
        if s is None:
            continue
        try:
            sd = score_series(
                s, history_start=meta.get("historical_start", "2000-01-01"),
                invert=bool(meta.get("invert", False)), name=meta.get("name_bg", key),
            )
        except Exception:
            continue
        if sd.get("current_value") is None:
            continue
        rows.append({
            "label": meta.get("name_bg", key),
            "value": sd.get("current_value"),
            "percentile": sd.get("percentile"),
            "date": sd.get("last_date"),
            "absz": abs(sd.get("z_score") or 0.0),
        })
    rows.sort(key=lambda r: r["absz"], reverse=True)
    return rows[:top_n]


def _render_lens_cards(exec_snapshot, snapshot) -> str:
    """China-style lens cards: header (icon+label+score) + score bar + direction
    badge + readings table (показател/стойност/percentile/дата)."""
    cards = []
    for row in exec_snapshot.lens_rows:
        lens = row.lens
        label = LENS_LABEL_BG.get(lens, lens)
        icon = LENS_ICON.get(lens, "•")
        score = _lens_score(row)
        sc_color = _score_color(score)
        sc_pct = 0 if pd.isna(score) else max(0, min(100, score))
        score_disp = "—" if pd.isna(score) else f"{score:.1f}"
        dir_bg, dir_fg, dir_bd = _direction_colors(row.direction)
        dir_lbl = _direction_label(row.direction)
        anomaly_note = f" · {row.anomaly_count} аном." if getattr(row, "anomaly_count", 0) else ""

        rows_html = ""
        for rd in (_lens_readings(lens, snapshot) if snapshot is not None else []):
            pct = rd["percentile"]
            pct_v = 50.0 if pct is None or pd.isna(pct) else max(0.0, min(100.0, pct))
            date_str = str(rd["date"])[:10] if rd["date"] else ""
            lbl = _html.escape(str(rd["label"]))
            rows_html += f"""
            <tr style="border-top:1px solid #21262d">
              <td style="padding:4px;color:#e6edf3;max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{lbl}">{lbl}</td>
              <td style="padding:4px;text-align:right;color:#c9d1d9;font-weight:600">{_fmt_val(rd['value'])}</td>
              <td style="padding:4px;text-align:center;white-space:nowrap"><span style="display:inline-block;width:32px;height:5px;background:#21262d;border-radius:3px;vertical-align:middle;overflow:hidden"><span style="display:block;width:{pct_v:.0f}%;height:100%;background:{sc_color}"></span></span> <span style="color:#8b949e;font-size:10px">{pct_v:.0f}</span></td>
              <td style="padding:4px;text-align:right;color:#8b949e;font-size:10px;white-space:nowrap">{date_str}</td>
            </tr>"""
        table_html = ""
        if rows_html:
            table_html = f"""
            <table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:10px">
              <thead><tr style="color:#8b949e">
                <th style="text-align:left;padding:3px 4px;font-weight:600;font-size:10px;text-transform:uppercase">Показател</th>
                <th style="text-align:right;padding:3px 4px;font-weight:600;font-size:10px;text-transform:uppercase">Стойност</th>
                <th style="text-align:center;padding:3px 4px;font-weight:600;font-size:10px;text-transform:uppercase">Pctl</th>
                <th style="text-align:right;padding:3px 4px;font-weight:600;font-size:10px;text-transform:uppercase">Дата</th>
              </tr></thead>
              <tbody>{rows_html}</tbody>
            </table>"""
        cards.append(f"""
        <div style="background:#0d1117;border:1px solid #30363d;border-radius:10px;padding:16px 18px">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:10px">
            <span style="display:flex;align-items:center;gap:8px;min-width:0"><span style="font-size:18px">{icon}</span><span style="color:#f0f6fc;font-size:15px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{_html.escape(label)}">{_html.escape(label)}</span></span>
            <span style="font-size:22px;font-weight:800;color:{sc_color};flex:0 0 auto">{score_disp}</span>
          </div>
          <div style="display:flex;align-items:center;gap:8px">
            <div style="flex:1;height:6px;background:#21262d;border-radius:3px;overflow:hidden"><div style="width:{sc_pct:.0f}%;height:100%;background:{sc_color};border-radius:3px"></div></div>
            <span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px;background:{dir_bg};color:{dir_fg};border:1px solid {dir_bd};white-space:nowrap">{dir_lbl}{anomaly_note}</span>
          </div>
          {table_html}
        </div>""")
    return f"""
    <div class="lens-bars">
      <h3>По lens-ове</h3>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:14px">
        {''.join(cards)}
      </div>
    </div>"""


def _render_html(
    today: date,
    composite: float,
    exec_snapshot,
    deep_link: Optional[str] = "briefing_deep.html",
    cross_report=None,
    anomaly_report=None,
    snapshot=None,
) -> str:
    """Render single-page scoreboard HTML."""
    composite_color = _score_color(composite)
    regime_bg_c, regime_fg_c, regime_bd_c = _regime_badge_colors(exec_snapshot.regime_label)
    regime_label_bg = _html.escape(exec_snapshot.regime_label_bg)

    # Score circle
    score_str = "—" if pd.isna(composite) else f"{composite:.1f}"

    # Lens cards (China-style: header + score bar + direction + readings table)
    lens_cards_html = _render_lens_cards(exec_snapshot, snapshot)

    # Narrative (от exec_snapshot)
    narrative_html = ""
    if exec_snapshot.narrative_bg:
        sentences = [s.strip() for s in exec_snapshot.narrative_bg.split(".") if s.strip()]
        for s in sentences[:4]:  # max 4 изречения
            narrative_html += f'<div class="narrative-item">{_html.escape(s)}.</div>'

    # Supporting signals
    signals_html = ""
    for sig in exec_snapshot.supporting_signals[:4]:
        signals_html += f'<div class="narrative-item">{_html.escape(sig)}</div>'

    as_of_str = exec_snapshot.as_of or today.isoformat()
    today_str = today.strftime("%d %b %Y")

    deep_btn = ""
    if deep_link:
        deep_btn = f'<a href="{deep_link}" style="display:inline-block;padding:8px 16px;background:#1f6feb;color:white;text-decoration:none;border-radius:6px;font-size:13px;font-weight:500;margin-top:8px">За подробен анализ →</a>'

    # China-style секции (данните вече са изчислени в generate_quick_briefing)
    cross_lens_html = _render_cross_lens_section(cross_report) if cross_report is not None else ""
    anomalies_html = _render_anomalies_section(anomaly_report) if anomaly_report is not None else ""
    data_quality_html = _render_data_quality_section()

    return f"""<!DOCTYPE html>
<html lang="bg">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>🇺🇸 US Macro Quick — {today.isoformat()}</title>
  <style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: #0d1117; color: #e6edf3;
    line-height: 1.6; font-size: 14px;
    min-height: 100vh;
}}
.container {{ max-width: 900px; margin: 0 auto; padding: 24px 16px; }}

.header {{
    background: linear-gradient(135deg, #1a1f2e 0%, #161b27 100%);
    border: 1px solid #30363d; border-radius: 12px;
    padding: 28px 32px; margin-bottom: 20px;
    display: flex; justify-content: space-between; align-items: center;
    gap: 16px; flex-wrap: wrap;
}}
.header-left h1 {{ font-size: 24px; font-weight: 700; color: #f0f6fc; }}
.header-left h1 .flag {{ font-size: 28px; margin-right: 8px; }}
.header-left .subtitle {{ color: #8b949e; font-size: 13px; margin-top: 4px; }}
.header-right {{ text-align: right; }}
.header-right .date {{ color: #8b949e; font-size: 13px; }}

.scoreboard {{
    background: #161b27; border: 1px solid #30363d; border-radius: 12px;
    padding: 24px 28px; margin-bottom: 20px;
    display: flex; align-items: center; gap: 28px; flex-wrap: wrap;
}}
.score-circle {{
    width: 100px; height: 100px; border-radius: 50%;
    display: flex; flex-direction: column; align-items: center;
    justify-content: center; flex-shrink: 0; border: 3px solid;
}}
.score-circle .score-num {{ font-size: 30px; font-weight: 800; line-height: 1; }}
.score-circle .score-label {{ font-size: 10px; color: #8b949e; margin-top: 4px }}
.composite-info {{ flex: 1 1 240px; min-width: 0; }}
.composite-info h2 {{ font-size: 18px; font-weight: 600; color: #f0f6fc; }}
.composite-info .regime-badge {{
    display: inline-block; padding: 5px 14px; border-radius: 20px;
    font-size: 13px; font-weight: 700; margin-top: 8px; letter-spacing: 0.3px;
}}
.composite-info .description {{ color: #8b949e; font-size: 12px; margin-top: 8px; line-height: 1.5 }}

.lens-bars {{
    background: #161b27; border: 1px solid #30363d; border-radius: 12px;
    padding: 20px 24px; margin-bottom: 20px;
}}
.lens-bars h3 {{ color: #8b949e; font-size: 12px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 14px; }}

.narrative-block {{
    background: #161b27; border: 1px solid #30363d; border-radius: 12px;
    padding: 20px 24px; margin-bottom: 20px;
}}
.narrative-block h3 {{ color: #8b949e; font-size: 12px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 12px; }}
.narrative-item {{
    font-size: 13px; color: #c9d1d9; padding: 8px 12px;
    border-left: 2px solid #30363d; margin-bottom: 6px;
    background: #0d1117; border-radius: 0 4px 4px 0;
    line-height: 1.5;
}}

.footer {{
    background: #161b27; border: 1px solid #30363d; border-radius: 10px;
    padding: 16px 20px; color: #8b949e; font-size: 11px;
    text-align: center;
}}
.footer strong {{ color: #58a6ff; }}
.footer a {{ color: #58a6ff; text-decoration: none; }}
.footer a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="header-left">
        <h1><span class="flag">🇺🇸</span> US Macro — Бърз преглед</h1>
        <div class="subtitle">Седмичен scoreboard · 30-секунден поглед</div>
      </div>
      <div class="header-right">
        <div class="date">{today_str}</div>
        <div style="color:#8b949e;font-size:11px;margin-top:4px">данни към {as_of_str}</div>
      </div>
    </div>

    <div class="scoreboard">
      <div class="score-circle" style="border-color:{composite_color}">
        <span class="score-num" style="color:{composite_color}">{score_str}</span>
        <span class="score-label">SCORE</span>
      </div>
      <div class="composite-info">
        <h2>Композитен Macro Score</h2>
        <span class="regime-badge" style="background:{regime_bg_c};color:{regime_fg_c};border:1px solid {regime_bd_c}">{regime_label_bg}</span>
        <div class="description">Mean breadth_positive × 100 across {len(exec_snapshot.lens_rows)} lens-а. Score &lt; {SCORE_RED:.0f} = свиване; &gt; {SCORE_GREEN:.0f} = експанзия; между двата = смесен/преходен.</div>
        {deep_btn}
      </div>
    </div>

    {lens_cards_html}

    {cross_lens_html}

    <div class="narrative-block">
      <h3>Какво виждаме</h3>
      {narrative_html or '<div class="narrative-item">Няма narrative — exec snapshot е празен.</div>'}
      {signals_html}
    </div>

    {anomalies_html}

    {data_quality_html}

    <div class="footer">
      <strong>US Macro Dashboard</strong> — Quick scoreboard (China-style headline view).<br>
      За пълен briefing (Cross-Lens Divergence, Top Anomalies, Modules): <a href="{deep_link or '#'}">подробен анализ →</a><br>
      Генериран: {today.isoformat()} · Lens-ове: {len(exec_snapshot.lens_rows)}
    </div>
  </div>
</body>
</html>"""


def generate_quick_briefing(
    snapshot: dict[str, pd.Series],
    output_path: str,
    today: Optional[date] = None,
    deep_link: Optional[str] = "briefing_deep.html",
) -> str:
    """Генерира quick scoreboard HTML.

    Args:
        snapshot: {series_key → pd.Series}.
        output_path: път до HTML файл.
        today: override за тестове.
        deep_link: relative/absolute link към deep briefing-а. None → без бутон.

    Returns:
        Абсолютен path към записания файл.
    """
    if today is None:
        today = date.today()

    lens_reports = {
        lens: compute_lens_breadth(lens, snapshot) for lens in LENS_ORDER
    }
    cross_report = compute_cross_lens_divergence(snapshot)
    anomaly_report = compute_anomalies(
        snapshot, z_threshold=2.0, top_n=10, lookback_years=5
    )
    nc_report = compute_non_consensus(snapshot)
    exec_snapshot = compute_executive_summary(
        cross_report, lens_reports, anomaly_report, nc_report,
    )

    composite = _composite_score(exec_snapshot)

    html_out = _render_html(
        today, composite, exec_snapshot, deep_link=deep_link,
        cross_report=cross_report, anomaly_report=anomaly_report,
        snapshot=snapshot,
    )

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_out, encoding="utf-8")
    return str(out_path.resolve())
