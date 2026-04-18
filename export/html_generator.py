"""
econ_v2 — HTML Dashboard Generator
=====================================
Генерира self-contained HTML файл с:
• Composite Macro Score (голям gauge)
• 3 модулни карти с sub-gauges
• Sparklines за ключови серии
• Исторически percentile badges
• Таблица с key readings

Дизайн: тъмна тема, Plotly.js (CDN), всичко embedded
"""

import json
from datetime import datetime
from pathlib import Path


def generate(modules_data: list, composite_score: float, composite_regime: str, composite_color: str) -> str:
    """
    Главна функция — взима list от module dicts, връща HTML string.
    """
    date_str = datetime.now().strftime("%d %B %Y, %H:%M")
    week_str = datetime.now().strftime("Week %V · %Y")

    # Serialize data for JS
    js_data = json.dumps({
        "composite": composite_score,
        "composite_regime": composite_regime,
        "composite_color": composite_color,
        "modules": modules_data,
        "generated": date_str,
    }, ensure_ascii=False, default=str)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Economic Intelligence Dashboard · {week_str}</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  :root {{
    --bg: #0d1117;
    --surface: #161b22;
    --surface2: #1c2128;
    --border: #30363d;
    --text: #e6edf3;
    --text-muted: #8b949e;
    --accent: #58a6ff;
    --green: #3fb950;
    --yellow: #d29922;
    --red: #f85149;
    --orange: #db6d28;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
  }}

  /* ─ Header ─────────────────────────────────────────────────── */
  .header {{
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 20px 32px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  .header-title {{ font-size: 1.3rem; font-weight: 700; color: var(--text); }}
  .header-title span {{ color: var(--accent); }}
  .header-meta {{ font-size: 0.8rem; color: var(--text-muted); text-align: right; line-height: 1.6; }}
  .header-badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    margin-top: 4px;
  }}

  /* ─ Layout ──────────────────────────────────────────────────── */
  .container {{ max-width: 1400px; margin: 0 auto; padding: 24px 32px; }}

  /* ─ Composite Hero ──────────────────────────────────────────── */
  .hero {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px 32px;
    margin-bottom: 24px;
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 24px;
    align-items: center;
  }}
  .hero-gauge {{ width: 240px; height: 200px; }}
  .hero-info h2 {{ font-size: 1.8rem; font-weight: 800; margin-bottom: 4px; }}
  .hero-info .regime-label {{
    font-size: 1.1rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin-bottom: 12px;
  }}
  .hero-info .desc {{ font-size: 0.9rem; color: var(--text-muted); line-height: 1.6; max-width: 500px; }}

  /* ─ Module Grid ─────────────────────────────────────────────── */
  .modules-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
    margin-bottom: 24px;
  }}

  .module-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    transition: border-color 0.2s;
  }}
  .module-card:hover {{ border-color: var(--accent); }}

  .module-header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 12px;
  }}
  .module-title {{ font-size: 0.9rem; font-weight: 700; }}
  .module-icon {{ font-size: 1.4rem; }}
  .regime-badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-top: 4px;
    color: #fff;
  }}

  .sub-gauges {{
    display: flex;
    gap: 4px;
    margin: 8px 0;
    flex-wrap: wrap;
  }}
  .sub-gauge {{ flex: 1; min-width: 80px; height: 100px; }}

  /* ─ Sparkline section ───────────────────────────────────────── */
  .sparkline-row {{
    margin-top: 12px;
    border-top: 1px solid var(--border);
    padding-top: 10px;
  }}
  .sparkline-label {{
    font-size: 0.7rem;
    color: var(--text-muted);
    margin-bottom: 4px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }}
  .sparkline-chart {{ height: 60px; width: 100%; }}

  /* ─ Key Readings Table ──────────────────────────────────────── */
  .readings-section {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 24px;
  }}
  .section-title {{
    font-size: 0.85rem;
    font-weight: 700;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 14px;
  }}
  .readings-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 12px;
  }}
  .reading-card {{
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 14px;
  }}
  .reading-name {{ font-size: 0.72rem; color: var(--text-muted); margin-bottom: 4px; }}
  .reading-value {{ font-size: 1.15rem; font-weight: 700; margin-bottom: 4px; }}
  .reading-meta {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
  .reading-yoy {{ font-size: 0.72rem; }}
  .reading-yoy.positive {{ color: var(--green); }}
  .reading-yoy.negative {{ color: var(--red); }}
  .reading-pct {{
    font-size: 0.65rem;
    color: var(--text-muted);
    background: var(--surface);
    padding: 1px 6px;
    border-radius: 10px;
    border: 1px solid var(--border);
  }}
  .reading-date {{ font-size: 0.65rem; color: var(--text-muted); margin-top: 2px; }}

  /* ─ Percentile bar ──────────────────────────────────────────── */
  .pct-bar-wrap {{ margin-top: 6px; }}
  .pct-bar-bg {{
    height: 4px;
    background: var(--border);
    border-radius: 2px;
    overflow: hidden;
  }}
  .pct-bar-fill {{
    height: 100%;
    border-radius: 2px;
    transition: width 0.4s;
  }}
  .pct-bar-label {{ font-size: 0.6rem; color: var(--text-muted); margin-top: 2px; }}

  /* ─ Footer ──────────────────────────────────────────────────── */
  .footer {{
    text-align: center;
    padding: 20px;
    font-size: 0.75rem;
    color: var(--text-muted);
    border-top: 1px solid var(--border);
    margin-top: 16px;
  }}

  /* ─ Responsive ─────────────────────────────────────────────── */
  @media (max-width: 900px) {{
    .modules-grid {{ grid-template-columns: 1fr; }}
    .hero {{ grid-template-columns: 1fr; }}
    .hero-gauge {{ width: 100%; }}
    .container {{ padding: 16px; }}
  }}
</style>
</head>
<body>

<div class="header">
  <div>
    <div class="header-title">⚡ <span>Economic Intelligence</span> Dashboard</div>
    <div style="font-size:0.75rem; color:var(--text-muted); margin-top:3px;">econ_v2 · FRED Data</div>
  </div>
  <div class="header-meta">
    <div>{week_str}</div>
    <div>Generated: {date_str}</div>
    <div id="regimeBadge" class="header-badge" style="background:#161b22; border:1px solid #30363d;">Loading...</div>
  </div>
</div>

<div class="container">

  <!-- ── Hero Composite ─────────────────────────────────────── -->
  <div class="hero">
    <div class="hero-gauge" id="compositeGauge"></div>
    <div class="hero-info">
      <h2 id="compositeScore">—</h2>
      <div class="regime-label" id="compositeRegime" style="color:#58a6ff;">—</div>
      <p class="desc" id="compositeDesc">Loading macro data from FRED...</p>
    </div>
  </div>

  <!-- ── Module Cards ───────────────────────────────────────── -->
  <div class="modules-grid" id="modulesGrid"></div>

  <!-- ── Key Readings ───────────────────────────────────────── -->
  <div class="readings-section">
    <div class="section-title">📋 Key Readings — All Modules</div>
    <div class="readings-grid" id="readingsGrid"></div>
  </div>

</div>

<div class="footer">
  Economic Intelligence v2.0 · Data: Federal Reserve Economic Data (FRED) ·
  Scores are percentile ranks since 2000 · Not investment advice
</div>

<script>
// ─── Embedded Data ────────────────────────────────────────────────────────
const DATA = {js_data};

// ─── Plotly theme ─────────────────────────────────────────────────────────
const PLOT_BG = '#161b22';
const PLOT_PAPER = '#161b22';
const FONT_COLOR = '#e6edf3';
const FONT_MUTED = '#8b949e';

// ─── Score → color ────────────────────────────────────────────────────────
function scoreColor(score) {{
  if (score >= 70) return '#3fb950';
  if (score >= 55) return '#69f0ae';
  if (score >= 40) return '#d29922';
  if (score >= 25) return '#db6d28';
  return '#f85149';
}}

// ─── Gauge chart ─────────────────────────────────────────────────────────
function makeGauge(divId, score, label, size='normal') {{
  const isLarge = size === 'large';
  const color = scoreColor(score);
  const layout = {{
    width: isLarge ? 240 : 120,
    height: isLarge ? 200 : 105,
    margin: {{ t: 20, b: 10, l: 10, r: 10 }},
    paper_bgcolor: PLOT_BG,
    font: {{ color: FONT_COLOR, family: 'system-ui, sans-serif' }},
  }};
  const data = [{{
    type: 'indicator',
    mode: 'gauge+number',
    value: score,
    number: {{ font: {{ size: isLarge ? 28 : 14, color: color }}, suffix: '' }},
    title: {{ text: label, font: {{ size: isLarge ? 11 : 9, color: FONT_MUTED }} }},
    gauge: {{
      axis: {{ range: [0, 100], tickcolor: '#30363d', tickfont: {{ size: 8, color: FONT_MUTED }}, nticks: 5 }},
      bar: {{ color: color, thickness: 0.25 }},
      bgcolor: '#1c2128',
      bordercolor: '#30363d',
      borderwidth: 1,
      steps: [
        {{ range: [0, 30],  color: 'rgba(248,81,73,0.12)' }},
        {{ range: [30, 50], color: 'rgba(210,153,34,0.10)' }},
        {{ range: [50, 70], color: 'rgba(63,185,80,0.08)' }},
        {{ range: [70, 100],color: 'rgba(63,185,80,0.15)' }},
      ],
      threshold: {{ line: {{ color: color, width: 2 }}, thickness: 0.7, value: score }},
    }},
  }}];
  Plotly.newPlot(divId, data, layout, {{ displayModeBar: false, responsive: true }});
}}

// ─── Sparkline ────────────────────────────────────────────────────────────
function makeSparkline(divId, dates, values, color) {{
  if (!dates || dates.length === 0) return;
  const layout = {{
    width: undefined,
    height: 60,
    margin: {{ t: 4, b: 4, l: 0, r: 0 }},
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    xaxis: {{ visible: false }},
    yaxis: {{ visible: false }},
    showlegend: false,
  }};
  const trace = {{
    x: dates,
    y: values,
    type: 'scatter',
    mode: 'lines',
    line: {{ color: color || '#58a6ff', width: 1.5, shape: 'spline' }},
    fill: 'tozeroy',
    fillcolor: (color || '#58a6ff') + '22',
  }};
  Plotly.newPlot(divId, [trace], layout, {{ displayModeBar: false, responsive: true }});
}}

// ─── Percentile bar ───────────────────────────────────────────────────────
function pctBar(pct, color) {{
  return `
    <div class="pct-bar-wrap">
      <div class="pct-bar-bg">
        <div class="pct-bar-fill" style="width:${{pct}}%;background:${{color}};"></div>
      </div>
      <div class="pct-bar-label">${{pct.toFixed(0)}}th percentile since 2000</div>
    </div>`;
}}

// ─── Main render ──────────────────────────────────────────────────────────
function render() {{
  const d = DATA;

  // Composite Hero
  document.getElementById('compositeScore').textContent = d.composite.toFixed(1);
  document.getElementById('compositeScore').style.color = scoreColor(d.composite);
  document.getElementById('compositeRegime').textContent = d.composite_regime;
  document.getElementById('compositeRegime').style.color = d.composite_color;
  document.getElementById('compositeDesc').textContent = macroDesc(d.composite, d.composite_regime);

  const badge = document.getElementById('regimeBadge');
  badge.textContent = d.composite_regime;
  badge.style.background = d.composite_color + '22';
  badge.style.color = d.composite_color;
  badge.style.border = '1px solid ' + d.composite_color + '44';

  makeGauge('compositeGauge', d.composite, 'MACRO COMPOSITE', 'large');

  // Module Cards
  const grid = document.getElementById('modulesGrid');
  d.modules.forEach((mod, mi) => {{
    const card = document.createElement('div');
    card.className = 'module-card';

    // Build sub-gauge placeholders
    const subScores = mod.scores ? Object.entries(mod.scores) : [];
    const subGaugeDivs = subScores.map((_, i) =>
      `<div class="sub-gauge" id="sg_${{mi}}_${{i}}"></div>`
    ).join('');

    // First sparkline
    const sparks = mod.sparklines ? Object.entries(mod.sparklines) : [];
    const firstSpark = sparks[0];
    const sparkHtml = firstSpark ? `
      <div class="sparkline-row">
        <div class="sparkline-label">${{firstSpark[0]}}</div>
        <div class="sparkline-chart" id="sp_${{mi}}_0"></div>
      </div>` : '';

    card.innerHTML = `
      <div class="module-header">
        <div>
          <div class="module-title">${{mod.icon}} ${{mod.label}}</div>
          <div class="regime-badge" style="background:${{mod.regime_color}}33; color:${{mod.regime_color}}; border:1px solid ${{mod.regime_color}}44;">
            ${{mod.regime}}
          </div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:1.4rem; font-weight:800; color:${{scoreColor(mod.composite)}}">${{mod.composite.toFixed(1)}}</div>
          <div style="font-size:0.65rem; color:#8b949e;">composite</div>
        </div>
      </div>
      <div class="sub-gauges">${{subGaugeDivs}}</div>
      ${{sparkHtml}}
    `;
    grid.appendChild(card);

    // Render sub-gauges after DOM insert
    setTimeout(() => {{
      subScores.forEach(([key, s], i) => {{
        makeGauge(`sg_${{mi}}_${{i}}`, s.score, s.label.toUpperCase(), 'small');
      }});
      if (firstSpark && firstSpark[1].dates.length > 0) {{
        makeSparkline(`sp_${{mi}}_0`, firstSpark[1].dates, firstSpark[1].values, scoreColor(mod.composite));
      }}
    }}, 50);
  }});

  // Key Readings
  const readingsGrid = document.getElementById('readingsGrid');
  d.modules.forEach(mod => {{
    (mod.key_readings || []).forEach(r => {{
      if (!r.value && r.value !== 0) return;
      const yoySign = r.yoy > 0 ? '+' : '';
      const yoyClass = r.yoy > 0 ? 'positive' : 'negative';
      const yoyHtml = r.yoy != null
        ? `<span class="reading-yoy ${{yoyClass}}">${{yoySign}}${{r.yoy.toFixed(2)}}% YoY</span>`
        : '';
      const color = scoreColor(r.score || 50);

      const div = document.createElement('div');
      div.className = 'reading-card';
      div.innerHTML = `
        <div class="reading-name">${{mod.icon}} ${{r.label}}</div>
        <div class="reading-value" style="color:${{color}}">${{formatValue(r.value)}}</div>
        <div class="reading-meta">
          ${{yoyHtml}}
          <span class="reading-pct">${{(r.percentile||50).toFixed(0)}}th pct</span>
        </div>
        ${{pctBar(r.percentile || 50, color)}}
        <div class="reading-date">${{r.date || ''}}</div>
      `;
      readingsGrid.appendChild(div);
    }});
  }});
}}

function formatValue(v) {{
  if (v === null || v === undefined) return '—';
  if (Math.abs(v) >= 100000) return (v/1000).toFixed(0) + 'k';
  if (Math.abs(v) >= 1000) return v.toFixed(0).replace(/\\B(?=(\\d{{3}})+(?!\\d))/g, ',');
  return v.toFixed(2);
}}

function macroDesc(score, regime) {{
  const descs = {{
    'EXPANSIONARY': 'Economy firing on all cylinders. Strong growth, healthy labor market, manageable inflation. Favorable environment for risk assets.',
    'HEALTHY': 'Balanced macro environment. Growth is solid, labor market resilient. Moderate risks. Standard positioning appropriate.',
    'MIXED': 'Conflicting signals across modules. Some areas of strength, others showing stress. Increased selectivity warranted.',
    'DETERIORATING': 'Multiple indicators pointing lower. Growth slowing, credit tightening or inflation elevated. Defensive lean appropriate.',
    'RECESSIONARY': 'Broad economic stress. High probability of recession or already in one. Maximum defensiveness. Monitor for turning points.',
  }};
  return descs[regime] || 'Macro data loading...';
}}

// Run
document.addEventListener('DOMContentLoaded', render);
</script>
</body>
</html>"""

    return html


def save(html: str, output_dir: str = "output") -> Path:
    """Записва HTML файла и връща пътя."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d_%H%M")
    filename = out / f"dashboard_{date_str}.html"
    filename.write_text(html, encoding="utf-8")
    # Актуализира и "latest" линк
    latest = out / "dashboard_latest.html"
    latest.write_text(html, encoding="utf-8")
    return filename
