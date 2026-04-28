"""
export/explorer.py
==================
Series Explorer — browseable detail изглед за всички 71 каталожни серии.

Единичен self-contained HTML файл. Клик върху серия в briefing-а
(``explorer.html#KEY``) отвежда на съответната #KEY секция тук.

Всяка series секция съдържа:
  1. Header (name_bg + FRED id + lens + peer)
  2. Metadata панел (всички каталожни полета)
  3. Latest readings таблица (последните 12 observation-а с z/YoY/MoM)
  4. Inline SVG sparkline (последните 5 години)
  5. Peer group context (останалите членове на peer_group-а + тяхно z)

Философия: self-contained (без JS, без CDN, без images). Inline CSS.
Този файл е research tool за Цветослав — отваря се offline, scroll или Ctrl+F.
Серии без данни се показват с "няма данни" маркер, не скриват.

Dependencies:
  - catalog.series        : SERIES_CATALOG
  - core.primitives       : z_score, yoy_pct, mom_pct
  - export.weekly_briefing: render_series_ref (за consistent tooltip layout)
"""
from __future__ import annotations

import html
import math
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from catalog.series import SERIES_CATALOG
from core.primitives import z_score, yoy_pct, mom_pct, first_diff, _infer_yoy_periods
from core.display import (
    change_kind,
    compute_change,
    fmt_change,
    short_period_label,
    long_period_label,
    change_header,
)
from export.weekly_briefing import (
    LENS_ORDER,
    LENS_LABEL_BG,
    render_series_ref,
)


# ============================================================
# CONFIG
# ============================================================

LATEST_N_READINGS = 12           # колко observation-а в table-а
SPARKLINE_YEARS = 5              # history window за sparkline
SPARKLINE_WIDTH = 240
SPARKLINE_HEIGHT = 60


# ============================================================
# PUBLIC API
# ============================================================

def generate_explorer(
    snapshot: dict[str, pd.Series],
    output_path: str,
    today: Optional[date] = None,
    briefing_href: Optional[str] = None,
) -> str:
    """Генерира Series Explorer HTML със всичките 71 каталожни серии.

    Args:
        snapshot: {series_key → pd.Series}. Серии без данни се маркират
            "няма данни" но секцията им се рендира (каталожна metainfo).
        output_path: path до output HTML файла.
        today: override за тестове.
        briefing_href: ако се подаде (напр. "briefing_2026-04-18.html"),
            добавя "← Към briefing" линк в header-а.

    Returns:
        Абсолютен path към записания HTML файл.
    """
    if today is None:
        today = date.today()

    as_of = _pick_as_of(snapshot)

    parts: list[str] = []
    parts.append(_render_header(today, as_of, snapshot, briefing_href))
    parts.append(_render_index(snapshot))
    # Sections: groupped by primary lens (first в lens list-а)
    for lens in LENS_ORDER:
        keys = [
            k for k, meta in SERIES_CATALOG.items()
            if (meta.get("lens") or [""])[0] == lens
        ]
        if not keys:
            continue
        parts.append(_render_lens_group(lens, keys, snapshot))

    # Rest — серии с primary lens извън LENS_ORDER (напр. housing ако примарно)
    rest = [
        k for k, meta in SERIES_CATALOG.items()
        if (meta.get("lens") or [""])[0] not in LENS_ORDER
    ]
    if rest:
        parts.append(_render_lens_group("other", rest, snapshot))

    parts.append(_render_footer(today, as_of))

    body = "\n".join(parts)
    full_html = _skeleton(
        title=f"Series Explorer — {today.isoformat()}",
        body=body,
    )

    out = Path(output_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(full_html, encoding="utf-8")
    return str(out)


# ============================================================
# SECTION RENDERERS
# ============================================================

def _render_header(today, as_of, snapshot, briefing_href) -> str:
    n_total = len(SERIES_CATALOG)
    n_with_data = sum(
        1 for k in SERIES_CATALOG
        if k in snapshot and not snapshot[k].empty
    )
    back_link = ""
    if briefing_href:
        back_link = (
            f'<a class="back-link" href="{html.escape(briefing_href)}">'
            f'← Към briefing</a>'
        )
    return f"""
<header class="expl-header">
  <div class="expl-title">
    <h1>Series Explorer</h1>
    <div class="expl-subtitle">Генериран {today.isoformat()} · Данни към {html.escape(as_of or '—')}</div>
  </div>
  <div class="expl-kpis">
    <div class="kpi"><div class="kpi-n">{n_with_data}/{n_total}</div><div class="kpi-l">серии с данни</div></div>
  </div>
  {back_link}
</header>
"""


def _render_index(snapshot) -> str:
    """Top-level index: групиран по primary lens, anchor линкове към секциите."""
    groups: list[str] = []
    for lens in LENS_ORDER:
        keys = sorted(
            k for k, meta in SERIES_CATALOG.items()
            if (meta.get("lens") or [""])[0] == lens
        )
        if not keys:
            continue
        rows: list[str] = []
        for k in keys:
            meta = SERIES_CATALOG[k]
            has_data = k in snapshot and not snapshot[k].empty
            status = '' if has_data else '<span class="no-data-mark">няма данни</span>'
            rows.append(
                f'<li><a href="#{html.escape(k)}"><code>{html.escape(k)}</code></a> '
                f'<span class="idx-name">{html.escape(meta.get("name_bg", ""))}</span> '
                f'<span class="idx-pg">· {html.escape(meta.get("peer_group", ""))}</span>'
                f'{status}</li>'
            )
        groups.append(f"""
<div class="idx-group">
  <h3>{html.escape(LENS_LABEL_BG.get(lens, lens))} <span class="idx-count">({len(keys)})</span></h3>
  <ul class="idx-list">{"".join(rows)}</ul>
</div>
""")
    return f"""
<section class="expl-section expl-index">
  <h2>Индекс</h2>
  <div class="idx-grid">{"".join(groups)}</div>
</section>
"""


def _render_lens_group(lens: str, keys: list[str], snapshot) -> str:
    label = LENS_LABEL_BG.get(lens, lens.title())
    section_html = [
        f'<section class="lens-group" data-lens="{html.escape(lens)}">',
        f'<h2 class="lens-group-h">{html.escape(label)} <span class="lens-n">({len(keys)})</span></h2>',
    ]
    for k in sorted(keys):
        section_html.append(_render_series_section(k, snapshot))
    section_html.append("</section>")
    return "\n".join(section_html)


def _render_series_section(series_key: str, snapshot) -> str:
    """Пълна детайлна секция за една серия."""
    meta = SERIES_CATALOG.get(series_key, {})
    key_esc = html.escape(series_key)
    name_bg = html.escape(meta.get("name_bg", series_key))
    name_en = html.escape(meta.get("name_en", ""))
    fred_id = html.escape(meta.get("id", series_key))
    source = html.escape((meta.get("source") or "").upper())
    region = html.escape(meta.get("region") or "")
    peer_group = html.escape(meta.get("peer_group", ""))
    lenses = html.escape(" / ".join(meta.get("lens", [])))

    series = snapshot.get(series_key, pd.Series(dtype=float))
    has_data = not series.empty

    # Подсекции
    meta_panel = _render_metadata_panel(series_key, series)
    if has_data:
        readings_table = _render_readings_table(series_key, series)
        sparkline = _render_sparkline(series)
    else:
        readings_table = '<div class="sub-empty">Няма наличен snapshot за тази серия.</div>'
        sparkline = ''
    peer_ctx = _render_peer_context(series_key, snapshot)

    return f"""
<article class="series-card" id="{key_esc}">
  <div class="series-card-head">
    <h3><code>{key_esc}</code> <span class="series-card-title">{name_bg}</span></h3>
    <div class="series-card-sub">
      <span class="series-card-sub-item">{fred_id} · {source} · {region}</span>
      <span class="series-card-sub-item">Леща: {lenses}</span>
      <span class="series-card-sub-item">Peer: {peer_group}</span>
      {f'<span class="series-card-sub-item en">{name_en}</span>' if name_en else ''}
    </div>
    <a class="to-top" href="#top">↑ горе</a>
  </div>
  <div class="series-card-grid">
    <div class="sub sub-meta">
      <h4>Каталог</h4>
      {meta_panel}
    </div>
    <div class="sub sub-readings">
      <h4>Последни {LATEST_N_READINGS} observation-а</h4>
      {readings_table}
    </div>
    <div class="sub sub-spark">
      <h4>Sparkline ({SPARKLINE_YEARS} г.)</h4>
      {sparkline}
    </div>
    <div class="sub sub-peers">
      <h4>Peer group context</h4>
      {peer_ctx}
    </div>
  </div>
</article>
"""


def _render_metadata_panel(series_key: str, series: pd.Series) -> str:
    meta = SERIES_CATALOG.get(series_key, {})

    def row(label: str, val: str) -> str:
        return (
            f'<div class="md-row">'
            f'<span class="md-l">{html.escape(label)}</span>'
            f'<span class="md-v">{val}</span></div>'
        )

    fields = []
    fields.append(row("Име (BG)", html.escape(meta.get("name_bg", ""))))
    if meta.get("name_en"):
        fields.append(row("Име (EN)", html.escape(meta["name_en"])))
    fields.append(row("Източник", f'{html.escape((meta.get("source") or "").upper())}'))
    fields.append(row("FRED / ID", f'<code>{html.escape(meta.get("id", ""))}</code>'))
    fields.append(row("Регион", html.escape(meta.get("region", ""))))
    fields.append(row("Леща(и)", html.escape(" / ".join(meta.get("lens", [])))))
    fields.append(row("Peer group", html.escape(meta.get("peer_group", ""))))

    tags = meta.get("tags") or []
    if tags:
        tag_html = " ".join(
            f'<span class="tag tag-{html.escape(t)}">{html.escape(t)}</span>'
            for t in tags
        )
        fields.append(row("Тагове", tag_html))

    fields.append(row("Transform", html.escape(meta.get("transform", ""))))
    fields.append(row("Start", html.escape(meta.get("historical_start", ""))))
    fields.append(row("Release", html.escape(meta.get("release_schedule", ""))))
    if meta.get("typical_release"):
        fields.append(row("Typical", html.escape(meta["typical_release"])))
    if meta.get("revision_prone"):
        fields.append(row("Ревизии", '<span class="rev-mark">да (†)</span>'))

    if not series.empty:
        fields.append(row(
            "Диапазон в snapshot-а",
            f'{series.index.min().date()} → {series.index.max().date()} ({len(series)} точки)'
        ))

    hint = (meta.get("narrative_hint") or "").strip()
    hint_html = (
        f'<div class="md-hint">{html.escape(hint)}</div>' if hint else ""
    )

    return f'<div class="md-list">{"".join(fields)}</div>{hint_html}'


def _render_readings_table(series_key: str, series: pd.Series) -> str:
    """Последните N readings с z + дълга/кратка промяна (адаптивна по тип серия).

    За rate серии (BREAKEVEN, UST, OAS) показва Δ в bps вместо %.
    За signed индекси (NFCI, CFNAI) показва абсолютна Δ.
    За останалите (CPI, payrolls и др.) — YoY%/MoM% както преди.
    """
    s = series.dropna().sort_index()
    if s.empty:
        return '<div class="sub-empty">Празна серия.</div>'

    meta = SERIES_CATALOG.get(series_key, {})
    kind = change_kind(series_key, meta)
    long_periods = _infer_yoy_periods(s) if len(s) >= 13 else 0
    short_periods = 1
    long_lbl = long_period_label(long_periods)
    short_lbl = short_period_label(long_periods)

    # z остава винаги
    try:
        z = z_score(s)
    except Exception:
        z = pd.Series(dtype=float, index=s.index)

    # Long и short change според kind
    try:
        long_chg = compute_change(s, kind, long_periods)
        short_chg = compute_change(s, kind, short_periods) if len(s) >= 2 else pd.Series(dtype=float, index=s.index)
    except Exception:
        long_chg = pd.Series(dtype=float, index=s.index)
        short_chg = pd.Series(dtype=float, index=s.index)

    long_header = change_header(kind, long_lbl)
    short_header = change_header(kind, short_lbl)

    tail = s.tail(LATEST_N_READINGS)
    rows = []
    for dt, val in tail.items():
        z_cell = _fmt_num(z.get(dt), digits=2, signed=True)
        long_cell = fmt_change(long_chg.get(dt), kind)
        short_cell = fmt_change(short_chg.get(dt), kind)
        rows.append(
            f"<tr>"
            f"<td>{dt.date().isoformat() if hasattr(dt, 'date') else str(dt)[:10]}</td>"
            f"<td class='num'>{_fmt_num(val, digits=3)}</td>"
            f"<td class='num'>{z_cell}</td>"
            f"<td class='num'>{long_cell}</td>"
            f"<td class='num'>{short_cell}</td>"
            f"</tr>"
        )
    rows.reverse()
    return f"""
<table class="readings-table">
  <thead><tr>
    <th>дата</th><th>стойност</th><th>z</th><th>{long_header}</th><th>{short_header}</th>
  </tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table>
"""


def _render_sparkline(
    series: pd.Series,
    width: int = SPARKLINE_WIDTH,
    height: int = SPARKLINE_HEIGHT,
    years: int = SPARKLINE_YEARS,
) -> str:
    """Inline SVG sparkline — polyline + min/max markers + last value dot."""
    s = series.dropna().sort_index()
    if s.empty or len(s) < 2:
        return '<svg class="sparkline" aria-hidden="true"></svg>'

    end = s.index.max()
    start = end - pd.DateOffset(years=years)
    sub = s[s.index >= start]
    if len(sub) < 2:
        sub = s.tail(12)

    values = sub.values.astype(float)
    vmin, vmax = float(np.nanmin(values)), float(np.nanmax(values))
    vrange = max(vmax - vmin, 1e-9)
    n = len(values)
    pad_x, pad_y = 4, 6

    def xy(i: int, v: float) -> tuple[float, float]:
        x = pad_x + (width - 2 * pad_x) * (i / max(n - 1, 1))
        # inverse: по-висока стойност → по-нисък y (SVG y-нарастващ е надолу)
        y = pad_y + (height - 2 * pad_y) * (1 - (v - vmin) / vrange)
        return x, y

    points = [xy(i, v) for i, v in enumerate(values)]
    polyline_pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)

    # Последна точка — маркер
    last_x, last_y = points[-1]
    last_val = values[-1]
    last_dir_cls = "spark-up" if last_val > values[0] else "spark-dn"

    # Min / max markers
    imin = int(np.nanargmin(values))
    imax = int(np.nanargmax(values))
    mn_x, mn_y = xy(imin, values[imin])
    mx_x, mx_y = xy(imax, values[imax])

    start_label = sub.index[0].date().isoformat() if hasattr(sub.index[0], "date") else str(sub.index[0])[:10]
    end_label = sub.index[-1].date().isoformat() if hasattr(sub.index[-1], "date") else str(sub.index[-1])[:10]

    return f"""
<div class="spark-wrap">
  <svg class="sparkline {last_dir_cls}" viewBox="0 0 {width} {height}"
       width="{width}" height="{height}" preserveAspectRatio="none"
       role="img" aria-label="sparkline">
    <polyline points="{polyline_pts}" fill="none" stroke-width="1.4"/>
    <circle cx="{mx_x:.1f}" cy="{mx_y:.1f}" r="2.2" class="spark-max"/>
    <circle cx="{mn_x:.1f}" cy="{mn_y:.1f}" r="2.2" class="spark-min"/>
    <circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3" class="spark-last"/>
  </svg>
  <div class="spark-caption">
    <span>{html.escape(start_label)}</span>
    <span>{html.escape(end_label)}</span>
  </div>
  <div class="spark-stats">
    <span>min {_fmt_num(vmin, 3)}</span>
    <span>max {_fmt_num(vmax, 3)}</span>
    <span>last {_fmt_num(last_val, 3)}</span>
  </div>
</div>
"""


def _render_peer_context(series_key: str, snapshot) -> str:
    meta = SERIES_CATALOG.get(series_key, {})
    pg = meta.get("peer_group")
    if not pg:
        return '<div class="sub-empty">Няма peer group.</div>'

    peer_keys = [
        k for k, m in SERIES_CATALOG.items()
        if m.get("peer_group") == pg and k != series_key
    ]
    if not peer_keys:
        return '<div class="sub-empty">Единственият член на peer group-а.</div>'

    rows = []
    for pk in sorted(peer_keys):
        pmeta = SERIES_CATALOG[pk]
        pseries = snapshot.get(pk, pd.Series(dtype=float)).dropna()
        if not pseries.empty:
            try:
                z_ser = z_score(pseries)
                z_last = z_ser.iloc[-1]
            except Exception:
                z_last = float("nan")
            last_val = pseries.iloc[-1]
            last_date = pseries.index[-1].date().isoformat() if hasattr(pseries.index[-1], 'date') else str(pseries.index[-1])[:10]
        else:
            z_last = float("nan")
            last_val = float("nan")
            last_date = "—"

        ref = render_series_ref(pk, extra_classes="code-ref", href_prefix="")
        rows.append(
            f"<tr>"
            f"<td>{ref}</td>"
            f"<td>{html.escape(pmeta.get('name_bg',''))}</td>"
            f"<td class='num'>{_fmt_num(last_val, 3)}</td>"
            f"<td class='num'>{_fmt_num(z_last, 2, signed=True)}</td>"
            f"<td>{html.escape(last_date)}</td>"
            f"</tr>"
        )
    return f"""
<table class="peer-table">
  <thead><tr>
    <th>серия</th><th>име</th><th>last</th><th>z</th><th>дата</th>
  </tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table>
"""


def _render_footer(today, as_of) -> str:
    return f"""
<footer class="expl-footer">
  <p class="muted">
    <strong>Методология:</strong> z-score на пълната серия; YoY% върху 12-month lag;
    MoM% върху 1-period lag. Sparkline — последните {SPARKLINE_YEARS} години.
    Peer context — останалите членове на същата peer group.
  </p>
  <p class="muted">As_of: {html.escape(as_of or '—')} · Today: {today.isoformat()}.</p>
</footer>
"""


# ============================================================
# HELPERS
# ============================================================

def _pick_as_of(snapshot) -> Optional[str]:
    candidates = []
    for s in snapshot.values():
        try:
            if not s.empty:
                candidates.append(str(s.index.max())[:10])
        except Exception:
            continue
    return max(candidates) if candidates else None


def _fmt_num(v, digits: int = 2, signed: bool = False) -> str:
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(f):
        return "—"
    fmt = f"{{:+.{digits}f}}" if signed else f"{{:.{digits}f}}"
    return fmt.format(f)


# Format helpers са вече в core.display — само _fmt_num е local за неноминализирани
# числа (raw серийни стойности със зависим брой digits).


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
<a id="top"></a>
<main class="expl-main">
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
.expl-main { max-width: 1200px; margin: 0 auto; padding: 28px 24px 60px; }

/* Header */
.expl-header {
  display: flex; justify-content: space-between; align-items: flex-end;
  border-bottom: 2px solid #222; padding-bottom: 14px; margin-bottom: 24px;
  flex-wrap: wrap; gap: 16px;
}
.expl-title h1 { margin: 0; font-size: 26px; font-weight: 600; }
.expl-subtitle { color: #666; font-size: 13px; margin-top: 4px; }
.expl-kpis { display: flex; gap: 14px; }
.kpi {
  background: #fff; border: 1px solid #e0e0e0; border-radius: 6px;
  padding: 8px 14px; text-align: center; min-width: 100px;
}
.kpi-n { font-size: 20px; font-weight: 600; color: #222; }
.kpi-l { font-size: 10.5px; color: #777; text-transform: uppercase; letter-spacing: 0.5px; }
.back-link {
  background: #fff; border: 1px solid #e0e0e0; border-radius: 6px;
  padding: 6px 12px; text-decoration: none; color: #3060a0; font-size: 13px;
}
.back-link:hover { background: #f0f4ff; }

/* Sections */
.expl-section { margin-bottom: 36px; }
.expl-section h2, .lens-group-h {
  font-size: 17px; text-transform: uppercase; letter-spacing: 1px;
  color: #333; border-bottom: 1px solid #ddd; padding-bottom: 6px; margin: 0 0 14px;
}
.lens-group-h { margin-top: 28px; }
.lens-n { color: #999; font-weight: 400; font-size: 14px; }

/* Index */
.idx-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }
.idx-group {
  background: #fff; border: 1px solid #e0e0e0; border-radius: 6px;
  padding: 12px 14px;
}
.idx-group h3 { margin: 0 0 8px; font-size: 13px; text-transform: uppercase; color: #555; letter-spacing: 0.5px; }
.idx-count { color: #999; font-weight: 400; font-size: 12px; }
.idx-list { list-style: none; padding: 0; margin: 0; font-size: 12.5px; }
.idx-list li { padding: 2px 0; border-bottom: 1px dotted #eee; }
.idx-list li:last-child { border-bottom: none; }
.idx-list a { text-decoration: none; color: #1a1a1a; }
.idx-list a:hover { text-decoration: underline; }
.idx-list code { background: #f4f4f4; padding: 1px 5px; border-radius: 3px; font-size: 11.5px; }
.idx-name { color: #555; }
.idx-pg { color: #888; font-size: 11.5px; }
.no-data-mark { background: #f3f3f3; color: #999; font-size: 10px; padding: 0 5px; border-radius: 3px; margin-left: 6px; font-style: italic; }

/* Series card */
.series-card {
  background: #fff; border: 1px solid #e0e0e0; border-radius: 8px;
  padding: 16px 18px; margin-bottom: 16px;
  scroll-margin-top: 20px;  /* anchor jump visual breathing */
}
.series-card:target { border-color: #3060a0; box-shadow: 0 0 0 3px rgba(48,96,160,0.12); }
.series-card-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px; margin-bottom: 10px; border-bottom: 1px solid #eee; padding-bottom: 8px; }
.series-card-head h3 { margin: 0; font-size: 16px; font-weight: 600; }
.series-card-head code { font-family: 'Consolas', 'Monaco', monospace; background: #f4f4f4; padding: 2px 7px; border-radius: 3px; font-size: 13px; }
.series-card-title { color: #222; font-weight: 500; margin-left: 4px; }
.series-card-sub { display: flex; flex-wrap: wrap; gap: 12px; font-size: 11.5px; color: #666; flex: 1; }
.series-card-sub-item { }
.series-card-sub-item.en { font-style: italic; color: #888; }
.to-top { color: #999; font-size: 11px; text-decoration: none; margin-left: auto; }
.to-top:hover { color: #3060a0; text-decoration: underline; }

.series-card-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.sub { background: #fafafa; border: 1px solid #eee; border-radius: 6px; padding: 10px 12px; }
.sub h4 { font-size: 11.5px; text-transform: uppercase; color: #666; letter-spacing: 0.7px; margin: 0 0 8px; }
.sub-empty { color: #aaa; font-style: italic; font-size: 12px; }

/* Metadata panel */
.md-list { font-size: 12.5px; }
.md-row { display: flex; padding: 2px 0; border-bottom: 1px dotted #eee; }
.md-row:last-child { border-bottom: none; }
.md-l { min-width: 120px; color: #888; }
.md-v { color: #222; flex: 1; }
.md-hint { margin-top: 8px; padding-top: 8px; border-top: 1px solid #eee; font-size: 12px; color: #555; font-style: italic; line-height: 1.5; }
.rev-mark { color: #a06020; }
.tag { display: inline-block; font-size: 10.5px; padding: 1px 6px; border-radius: 3px; margin-right: 3px; background: #eef; color: #3060a0; font-family: monospace; }
.tag-ai_exposure { background: #f3e8ff; color: #6030a0; }
.tag-structural  { background: #e8f5e8; color: #306030; }
.tag-non_consensus { background: #fff3d6; color: #806020; }

/* Readings table */
.readings-table, .peer-table { width: 100%; border-collapse: collapse; font-size: 12px; background: #fff; border: 1px solid #eee; }
.readings-table th, .readings-table td,
.peer-table th, .peer-table td { padding: 4px 8px; text-align: left; border-bottom: 1px solid #eee; }
.readings-table th, .peer-table th { background: #fafafa; color: #666; font-weight: 500; font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.5px; }
.num { font-family: 'Consolas', 'Monaco', monospace; text-align: right; }

/* Sparkline */
.spark-wrap { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; }
.sparkline { display: block; width: 100%; max-width: 280px; height: auto; }
.sparkline polyline { stroke: #3060a0; }
.sparkline.spark-up polyline { stroke: #1e6b30; }
.sparkline.spark-dn polyline { stroke: #a02020; }
.spark-last { fill: #222; stroke: #fff; stroke-width: 1; }
.spark-max { fill: #a02020; opacity: 0.55; }
.spark-min { fill: #1e6b30; opacity: 0.55; }
.spark-caption { display: flex; justify-content: space-between; width: 100%; max-width: 280px; font-size: 10px; color: #888; font-family: monospace; }
.spark-stats { font-size: 10.5px; color: #666; font-family: monospace; display: flex; gap: 10px; flex-wrap: wrap; }

/* Peer table */
.peer-table code { font-size: 11px; }

.muted { color: #888; font-style: italic; font-size: 13px; }
.expl-footer { border-top: 1px solid #ddd; padding-top: 16px; margin-top: 30px; font-size: 12px; color: #666; }
.expl-footer p { margin: 6px 0; }

/* Series-ref tooltip — еднакъв layout като briefing-а */
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
  font-size: 12px;
}
.series-ref-unknown { font-family: monospace; background: #f4f4f4; padding: 1px 5px; border-radius: 3px; font-size: 12px; color: #888; }
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

@media (max-width: 880px) {
  .series-card-grid { grid-template-columns: 1fr; }
  .idx-grid { grid-template-columns: 1fr; }
  .series-ref .tooltip { width: 240px; }
}
"""
