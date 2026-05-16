"""
export/data_status.py
=====================
Data Status Screen — self-contained HTML страница.

Показва статута на всички серии в catalog:
  - Кое е fresh / delayed_explained / stale / updated_today
  - Last observation date спрямо today
  - Days behind schedule
  - Cache timestamps
  - Shutdown aware (KNOWN_DELAYS overrides "stale" → "delayed_explained")
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional


# ============================================================
# CONFIG — known delays (for shutdown aftermath и подобни)
# ============================================================

# Всяка известна причина за забавяне добавя status "delayed_explained"
# вместо "stale" за серии с last_observation в дадения прозорец.
KNOWN_DELAYS: list[dict[str, str]] = [
    {
        "start": "2025-10-01",
        "end":   "2026-03-15",
        "reason": "Admin shutdown aftermath — статистиките лагват ~2 месеца.",
    },
    # Допълвай тук при бъдещи delays
]

# Очакван максимален lag в дни от днес до last_observation
EXPECTED_LAG_DAYS = {
    "weekly":    14,    # claims: 1 седмица + buffer
    "monthly":   45,    # NFP, CPI: 1 месец + release + buffer
    "quarterly": 110,   # GDP: 1 квартал + buffer
    "annually":  400,   # annual series: 1 год + buffer
}

# Multiplier за "stale" прага (напр. 2× expected → stale)
STALE_MULTIPLIER = 2.0


# ============================================================
# CLASSIFICATION
# ============================================================

def classify_status(
    release_schedule: str,
    last_observation: Optional[str],
    today: Optional[date] = None,
) -> tuple[str, int, Optional[str]]:
    """Класифицира status на серия.

    Returns:
        (status, days_behind, explanation)
        status ∈ {"fresh", "updated_today", "delayed", "delayed_explained", "stale", "no_data"}
    """
    if today is None:
        today = date.today()

    if not last_observation:
        return ("no_data", -1, "Няма данни в кеша.")

    try:
        last_obs = datetime.fromisoformat(last_observation).date()
    except ValueError:
        return ("no_data", -1, f"Невалиден формат на дата: {last_observation}")

    days_behind = (today - last_obs).days
    expected = EXPECTED_LAG_DAYS.get(release_schedule, 45)

    # Normal classification first
    if days_behind == 0:
        return ("updated_today", 0, None)
    if days_behind <= expected:
        return ("fresh", days_behind, None)

    # Over expected lag — check if a documented delay explains it.
    # Известни забавяния override-ват "delayed"/"stale" САМО когато
    # серията действително изостава; не маскираме fresh releases.
    for delay in KNOWN_DELAYS:
        ds = datetime.fromisoformat(delay["start"]).date()
        de = datetime.fromisoformat(delay["end"]).date()
        if ds <= last_obs <= de:
            return ("delayed_explained", days_behind, delay["reason"])

    if days_behind <= expected * STALE_MULTIPLIER:
        return ("delayed", days_behind, f"Над очаквания lag ({expected} дни).")
    return ("stale", days_behind, f"Значително над нормалния lag ({expected} дни).")


# ============================================================
# ROW BUILDER
# ============================================================

def _build_row(
    series_key: str,
    meta: dict[str, Any],
    cache_status: dict[str, Any],
    today: date,
) -> dict[str, Any]:
    """Строи един ред за таблицата от meta + cache status."""
    source = meta.get("source", "unknown")
    last_obs = cache_status.get("last_observation")

    if source == "pending":
        status = "pending"
        days_behind = -1
        explanation = "Източникът ще бъде интегриран в Фаза 3+."
    else:
        status, days_behind, explanation = classify_status(
            meta["release_schedule"],
            last_obs,
            today=today,
        )

    return {
        "key": series_key,
        "fred_id": meta.get("id", ""),
        "source": source,
        "name_bg": meta.get("name_bg", ""),
        "name_en": meta.get("name_en", ""),
        "lens": "/".join(meta.get("lens", [])),
        "peer_group": meta.get("peer_group", ""),
        "tags": meta.get("tags", []),
        "release_schedule": meta.get("release_schedule", ""),
        "typical_release": meta.get("typical_release", ""),
        "last_observation": last_obs or "—",
        "last_fetched": cache_status.get("last_fetched", "—"),
        "n_obs": cache_status.get("n_observations", 0),
        "status": status,
        "days_behind": days_behind,
        "explanation": explanation or "",
        "revision_prone": meta.get("revision_prone", False),
        "narrative_hint": meta.get("narrative_hint", ""),
    }


# ============================================================
# HTML RENDERING
# ============================================================

def render_html(rows: list[dict[str, Any]], today: Optional[date] = None) -> str:
    """Генерира пълен self-contained HTML."""
    if today is None:
        today = date.today()

    # Summary counts
    counts = {
        "total":              len(rows),
        "updated_today":      sum(1 for r in rows if r["status"] == "updated_today"),
        "fresh":              sum(1 for r in rows if r["status"] == "fresh"),
        "delayed":            sum(1 for r in rows if r["status"] == "delayed"),
        "delayed_explained":  sum(1 for r in rows if r["status"] == "delayed_explained"),
        "stale":              sum(1 for r in rows if r["status"] == "stale"),
        "pending":            sum(1 for r in rows if r["status"] == "pending"),
        "no_data":            sum(1 for r in rows if r["status"] == "no_data"),
    }

    # Stale-fetch banner: ако повечето серии не са fetch-вани скоро,
    # значи fetch е fail-нал тихо (липсващ API ключ, мрежа, FRED downtime).
    # Без този banner потребителят гледа стари данни без да знае.
    fetch_dates: list[date] = []
    for r in rows:
        lf = r.get("last_fetched")
        if lf and lf != "—":
            try:
                fd = datetime.fromisoformat(lf).date()
                fetch_dates.append(fd)
            except ValueError:
                pass
    stale_banner_html = ""
    if fetch_dates:
        max_fetch_age = max((today - fd).days for fd in fetch_dates)
        n_stale_fetch = sum(1 for fd in fetch_dates if (today - fd).days > 7)
        n_total_fetch = len(fetch_dates)
        if max_fetch_age > 7 and n_stale_fetch / n_total_fetch > 0.5:
            stale_banner_html = (
                '<div class="stale-fetch-banner">'
                f'⚠️ ВНИМАНИЕ: {n_stale_fetch}/{n_total_fetch} серии не са обновявани от {max_fetch_age} дни. '
                'Пусни <code>python run.py --refresh-only</code> или провери дали FRED ключът е валиден.'
                '</div>'
            )

    # Recent releases: серии с last_observation в последните 7 дни
    week_ago = today - timedelta(days=7)
    recent = []
    for r in rows:
        lo = r["last_observation"]
        if lo and lo != "—":
            try:
                lod = datetime.fromisoformat(lo).date()
                if lod >= week_ago:
                    recent.append(r)
            except ValueError:
                pass
    recent.sort(key=lambda x: x["last_observation"], reverse=True)

    # Pre-compute rendered rows (HTML)
    rows_html = "".join(_render_row(r) for r in rows)
    recent_html = "".join(_render_recent_row(r) for r in recent[:15]) if recent else '<tr><td colspan="3" class="muted">Няма releases в последните 7 дни.</td></tr>'

    # JSON за client-side filtering
    rows_json = json.dumps([
        {k: v for k, v in r.items() if k in ("key", "lens", "source", "status")}
        for r in rows
    ], ensure_ascii=False)

    return _HTML_TEMPLATE.format(
        today=today.strftime("%A, %d %B %Y"),
        today_iso=today.isoformat(),
        counts=counts,
        rows_html=rows_html,
        recent_html=recent_html,
        rows_json=rows_json,
        known_delays_html=_render_known_delays(),
        stale_banner_html=stale_banner_html,
    )


def _render_row(r: dict[str, Any]) -> str:
    """HTML за един ред в главната таблица."""
    status_class = f"status-{r['status']}"
    status_label = {
        "updated_today":     "🔄 Днес",
        "fresh":             "✅ Fresh",
        "delayed":           "⚠ Delayed",
        "delayed_explained": "⏳ Delayed (обяснено)",
        "stale":             "❌ Stale",
        "pending":           "⏸ Pending",
        "no_data":           "—",
    }.get(r["status"], r["status"])

    tags_html = "".join(
        f'<span class="tag tag-{t}">{_tag_label(t)}</span>'
        for t in r["tags"]
    )
    if r["revision_prone"]:
        tags_html += '<span class="tag tag-revision">⚠ ревизии</span>'

    days_display = "—" if r["days_behind"] < 0 else f"{r['days_behind']} дни"

    explanation_html = f'<div class="explanation">{r["explanation"]}</div>' if r["explanation"] else ""

    return f"""
    <tr data-lens="{r['lens']}" data-source="{r['source']}" data-status="{r['status']}">
      <td class="col-key"><code>{r['key']}</code><div class="fred-id">{r['fred_id']}</div></td>
      <td class="col-name">
        <div class="name-bg">{r['name_bg']}</div>
        <div class="name-en">{r['name_en']}</div>
      </td>
      <td class="col-lens">{r['lens']}</td>
      <td class="col-peer">{r['peer_group']}</td>
      <td class="col-obs">{r['last_observation']}</td>
      <td class="col-days"><span class="days-pill">{days_display}</span></td>
      <td class="col-status"><span class="status-pill {status_class}">{status_label}</span>{explanation_html}</td>
      <td class="col-tags">{tags_html}</td>
    </tr>
    """


def _render_recent_row(r: dict[str, Any]) -> str:
    return f"""
    <tr>
      <td>{r['last_observation']}</td>
      <td><code>{r['key']}</code> — {r['name_bg']}</td>
      <td>{r['lens']}</td>
    </tr>
    """


def _render_known_delays() -> str:
    if not KNOWN_DELAYS:
        return "<p class='muted'>Няма документирани забавяния.</p>"
    items = "".join(
        f"<li><b>{d['start']} → {d['end']}</b>: {d['reason']}</li>"
        for d in KNOWN_DELAYS
    )
    return f"<ul class='delays-list'>{items}</ul>"


def _tag_label(tag: str) -> str:
    return {
        "non_consensus": "⭐ non-consensus",
        "ai_exposure":   "🤖 AI",
        "structural":    "🏗️ структурен",
    }.get(tag, tag)


# ============================================================
# PUBLIC API
# ============================================================

def generate_data_status(
    adapter,
    catalog: dict[str, dict[str, Any]],
    output_dir: Path,
    today: Optional[date] = None,
) -> Path:
    """Основна функция — връща path до generated HTML файл.

    Args:
        adapter: FredAdapter instance (или всеки обект с get_cache_status())
        catalog: SERIES_CATALOG dict
        output_dir: Къде да запише HTML
        today: За testing; иначе date.today()

    Returns:
        Path до записания HTML файл.
    """
    if today is None:
        today = date.today()

    rows = []
    for key, meta in catalog.items():
        cache_status = adapter.get_cache_status(key) if hasattr(adapter, "get_cache_status") else {}
        rows.append(_build_row(key, meta, cache_status, today))

    # Sort: по lens, после status priority, после key
    status_order = {
        "updated_today": 0, "fresh": 1, "delayed_explained": 2,
        "delayed": 3, "stale": 4, "no_data": 5, "pending": 6,
    }
    rows.sort(key=lambda r: (r["lens"], status_order.get(r["status"], 99), r["key"]))

    html = render_html(rows, today=today)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"data_status_{today.isoformat()}.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


# ============================================================
# HTML TEMPLATE
# ============================================================

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="bg">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Data Status — {today_iso}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    background: #f7f8fa;
    color: #1a202c;
    line-height: 1.5;
  }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 32px 24px; }}

  header {{ margin-bottom: 32px; }}
  h1 {{ font-size: 28px; font-weight: 700; color: #1a202c; margin-bottom: 4px; }}
  .subtitle {{ color: #718096; font-size: 14px; }}

  /* Summary cards */
  .summary-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px;
    margin-bottom: 32px;
  }}
  .card {{
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 16px;
  }}
  .card-value {{ font-size: 28px; font-weight: 700; color: #2d3748; }}
  .card-label {{ color: #718096; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 4px; }}
  .card.fresh   {{ border-left: 3px solid #10b981; }}
  .card.delayed {{ border-left: 3px solid #f59e0b; }}
  .card.delayed-explained {{ border-left: 3px solid #6366f1; }}
  .card.stale   {{ border-left: 3px solid #ef4444; }}
  .card.pending {{ border-left: 3px solid #9ca3af; }}

  /* Sections */
  section {{ margin-bottom: 40px; }}
  section h2 {{ font-size: 18px; font-weight: 600; margin-bottom: 16px; color: #2d3748; }}

  /* Filters */
  .filters {{
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 16px;
    padding: 12px;
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
  }}
  .filters label {{ font-size: 12px; color: #718096; display: flex; flex-direction: column; gap: 4px; }}
  .filters select {{
    padding: 6px 10px;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    background: #fff;
    font-size: 13px;
    color: #2d3748;
    cursor: pointer;
  }}

  /* Table */
  .table-wrap {{
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    overflow: auto;
    max-height: 70vh;
  }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  thead th {{
    position: sticky; top: 0;
    background: #f7fafc; z-index: 1;
    text-align: left;
    padding: 10px 12px;
    border-bottom: 1px solid #e2e8f0;
    font-weight: 600;
    color: #4a5568;
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 0.5px;
  }}
  tbody td {{ padding: 10px 12px; border-bottom: 1px solid #edf2f7; vertical-align: top; }}
  tbody tr:hover {{ background: #f7fafc; }}
  code {{ background: #edf2f7; padding: 2px 6px; border-radius: 4px; font-size: 12px; color: #2d3748; }}
  .fred-id {{ font-size: 11px; color: #a0aec0; margin-top: 2px; }}
  .name-bg {{ font-weight: 500; }}
  .name-en {{ font-size: 11px; color: #718096; margin-top: 2px; }}

  /* Status pills */
  .status-pill {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 500;
  }}
  .status-updated_today     {{ background: #dbeafe; color: #1e40af; }}
  .status-fresh             {{ background: #d1fae5; color: #065f46; }}
  .status-delayed           {{ background: #fed7aa; color: #9a3412; }}
  .status-delayed_explained {{ background: #e0e7ff; color: #3730a3; }}
  .status-stale             {{ background: #fecaca; color: #991b1b; }}
  .status-pending           {{ background: #e5e7eb; color: #374151; }}
  .status-no_data           {{ background: #f3f4f6; color: #6b7280; }}
  .days-pill {{ font-family: ui-monospace, monospace; color: #4a5568; }}
  .explanation {{ font-size: 11px; color: #718096; margin-top: 4px; }}

  /* Tags */
  .tag {{
    display: inline-block;
    margin: 2px 2px 0 0;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 500;
  }}
  .tag-non_consensus {{ background: #fef3c7; color: #92400e; }}
  .tag-ai_exposure   {{ background: #ede9fe; color: #5b21b6; }}
  .tag-structural    {{ background: #cffafe; color: #155e75; }}
  .tag-revision      {{ background: #fee2e2; color: #991b1b; }}

  /* Info boxes */
  .info-box {{
    background: #fffbeb;
    border-left: 3px solid #f59e0b;
    padding: 12px 16px;
    border-radius: 6px;
    margin-bottom: 16px;
  }}
  .info-box h3 {{ font-size: 14px; margin-bottom: 8px; }}
  .delays-list {{ margin-left: 20px; font-size: 13px; color: #4a5568; }}
  .delays-list li {{ margin-bottom: 4px; }}
  .muted {{ color: #a0aec0; font-size: 12px; padding: 12px; text-align: center; }}

  footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #e2e8f0; color: #a0aec0; font-size: 12px; text-align: center; }}

  .stale-fetch-banner {{
    background: #fff3cd; border: 1px solid #f0c674; border-left: 4px solid #d97706;
    color: #7c4a03; padding: 14px 18px; border-radius: 6px;
    margin-bottom: 20px; font-size: 14px; line-height: 1.5;
  }}
  .stale-fetch-banner code {{ background: rgba(0,0,0,0.08); padding: 1px 6px; border-radius: 3px; font-family: 'Consolas', 'Monaco', monospace; }}
</style>
</head>
<body>
  <div class="container">
    <header>
      <h1>Data Status Screen</h1>
      <p class="subtitle">{today} · econ_v2 · The Economist's Lens</p>
    </header>

    {stale_banner_html}

    <!-- Summary -->
    <div class="summary-grid">
      <div class="card"><div class="card-value">{counts[total]}</div><div class="card-label">Общо серии</div></div>
      <div class="card fresh"><div class="card-value">{counts[fresh]}</div><div class="card-label">Fresh</div></div>
      <div class="card"><div class="card-value">{counts[updated_today]}</div><div class="card-label">Днес</div></div>
      <div class="card delayed"><div class="card-value">{counts[delayed]}</div><div class="card-label">Delayed</div></div>
      <div class="card delayed-explained"><div class="card-value">{counts[delayed_explained]}</div><div class="card-label">Обяснени</div></div>
      <div class="card stale"><div class="card-value">{counts[stale]}</div><div class="card-label">Stale</div></div>
      <div class="card pending"><div class="card-value">{counts[pending]}</div><div class="card-label">Pending</div></div>
    </div>

    <!-- Known delays -->
    <section>
      <div class="info-box">
        <h3>📋 Документирани забавяния</h3>
        {known_delays_html}
      </div>
    </section>

    <!-- Recent releases -->
    <section>
      <h2>🆕 Releases в последните 7 дни</h2>
      <div class="table-wrap" style="max-height: 280px;">
        <table>
          <thead><tr><th>Last obs</th><th>Серия</th><th>Lens</th></tr></thead>
          <tbody>{recent_html}</tbody>
        </table>
      </div>
    </section>

    <!-- Filter bar + Main table -->
    <section>
      <h2>📊 Всички серии</h2>
      <div class="filters">
        <label>Тема
          <select id="filter-lens">
            <option value="">Всички</option>
            <option value="labor">Labor</option>
            <option value="growth">Growth</option>
            <option value="housing">Housing</option>
            <option value="inflation">Inflation</option>
          </select>
        </label>
        <label>Статус
          <select id="filter-status">
            <option value="">Всички</option>
            <option value="fresh">Fresh</option>
            <option value="updated_today">Днес</option>
            <option value="delayed">Delayed</option>
            <option value="delayed_explained">Delayed (обяснено)</option>
            <option value="stale">Stale</option>
            <option value="pending">Pending</option>
            <option value="no_data">No data</option>
          </select>
        </label>
        <label>Източник
          <select id="filter-source">
            <option value="">Всички</option>
            <option value="fred">FRED</option>
            <option value="pending">Pending</option>
          </select>
        </label>
      </div>

      <div class="table-wrap">
        <table id="main-table">
          <thead>
            <tr>
              <th>Key / FRED ID</th>
              <th>Наименование</th>
              <th>Lens</th>
              <th>Peer group</th>
              <th>Last obs</th>
              <th>Days behind</th>
              <th>Status</th>
              <th>Tags</th>
            </tr>
          </thead>
          <tbody>{rows_html}</tbody>
        </table>
      </div>
    </section>

    <footer>
      econ_v2 · Data Status · Phase 1 · <span id="updated-timestamp">{today_iso}</span>
    </footer>
  </div>

<script>
(function() {{
  const rows = document.querySelectorAll('#main-table tbody tr');
  const filterLens = document.getElementById('filter-lens');
  const filterStatus = document.getElementById('filter-status');
  const filterSource = document.getElementById('filter-source');

  function applyFilters() {{
    const lens = filterLens.value;
    const status = filterStatus.value;
    const source = filterSource.value;

    rows.forEach(row => {{
      const rowLens = row.dataset.lens || '';
      const rowStatus = row.dataset.status || '';
      const rowSource = row.dataset.source || '';

      const lensMatch = !lens || rowLens.includes(lens);
      const statusMatch = !status || rowStatus === status;
      const sourceMatch = !source || rowSource === source;

      row.style.display = (lensMatch && statusMatch && sourceMatch) ? '' : 'none';
    }});
  }}

  filterLens.addEventListener('change', applyFilters);
  filterStatus.addEventListener('change', applyFilters);
  filterSource.addEventListener('change', applyFilters);
}})();
</script>
</body>
</html>
"""
