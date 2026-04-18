# us-macro-dashboard

A Python framework for weekly US macro briefings. Pulls data from FRED, scores 70+ series across seven analytical lenses (labor, inflation, credit, growth, housing, fed, consumer), and generates a self-contained HTML briefing with executive summary, cross-lens divergences, anomaly detection, and historical analog matching.

Built as a personal research desk, designed to be forkable. The public repo ships the framework; your own research journal stays local.

## What it produces

```bash
python run.py --briefing --with-analogs --with-journal
```

A single `output/briefing_YYYY-MM-DD.html` file with:

- **Executive Summary** — composite macro regime + per-lens regime table
- **Week-over-week delta** — which series moved materially in the last 7 days
- **Cross-Lens divergence** — pairs where lenses disagree (e.g. labor cooling while credit tightening)
- **Non-consensus readings** — series in the tails of their historical distribution
- **Anomaly detection** — statistical outliers in recent data
- **Historical Analogs** — top-3 nearest historical episodes (cosine similarity on 8-dim macro state vector) with forward-path statistics
- **Linked journal notes** — your personal research observations surfaced alongside the machine analysis

The HTML is self-contained (only Plotly.js from CDN). No hosting required, no Streamlit, no dashboards server.

## Quick start

### 1. Clone and install

```bash
git clone https://github.com/<your-username>/us-macro-dashboard.git
cd us-macro-dashboard
pip install -r requirements.txt
```

### 2. Get a FRED API key

Free, instant. Register at <https://fred.stlouisfed.org/docs/api/api_key.html>.

### 3. Configure

```bash
cp .env.example .env
# edit .env and paste your key
```

Or export it in your shell:

```bash
export FRED_API_KEY=your_key_here
```

### 4. Run

```bash
# Quick health check — which series are fresh, which are stale
python run.py --status

# Weekly briefing
python run.py --briefing

# Briefing + historical analog engine (deep-history fetch, slower first time)
python run.py --briefing --with-analogs

# Briefing + analogs + your local journal notes
python run.py --briefing --with-analogs --with-journal
```

Generated HTML lands in `output/` and opens automatically in your default browser.

## Architecture

```
us-macro-dashboard/
├── config.py                 # FRED key, weights, regime thresholds
├── catalog/series.py         # 71 registered FRED series with metadata
├── sources/fred_adapter.py   # FRED fetch + JSON cache (12h TTL)
├── core/                     # primitives: percentile_rank, z_score, regime labels
├── modules/                  # per-lens scoring (labor.py, inflation.py, ...)
├── analysis/
│   ├── breadth.py            # per-lens breadth (share of series in each regime)
│   ├── divergence.py         # cross-lens pair readings
│   ├── non_consensus.py      # tail-of-distribution flag
│   ├── anomaly.py            # statistical outlier detection
│   ├── macro_vector.py       # 8-dim macro state vector + z-scoring
│   ├── analog_matcher.py     # cosine similarity over historical states
│   ├── analog_comparison.py  # dimension-by-dimension delta
│   ├── forward_path.py       # what happened after the analog period
│   └── executive.py          # composite score + regime summary
├── export/
│   ├── weekly_briefing.py    # HTML briefing generator
│   ├── html_generator.py     # dashboard alternative
│   └── explorer.py           # series drill-down pages
├── scripts/
│   ├── _utils.py             # journal layer + sandbox scaffolding
│   └── build_journal_index.py
├── journal/                  # your research notes (framework in git, content local)
├── tests/                    # 399 tests, pytest
├── FRAMEWORK.md              # full methodology
├── PHASES.md                 # build history + decision log
└── AGENT.md                  # contributor orientation (also: guide for Claude agents)
```

## Research journal

The `journal/` directory is a structured markdown notebook for your own observations. The framework is public; the notes are not — see `.gitignore`. This is by design: the idea is to fork this repo, keep your research private, and share the method.

Each entry is markdown with YAML frontmatter:

```yaml
---
date: 2026-04-18
topic: credit              # labor / inflation / credit / growth / analogs / regime / methodology
title: HY widening without VIX confirmation
tags: [hy_oas, divergence]
status: open_question      # open_question / hypothesis / finding / decision
---
```

Entries appear in the next briefing when run with `--with-journal`. For the full Q&A workflow (question → sandbox analysis → journal entry → briefing surface), see `AGENT.md`.

## Testing

```bash
pytest tests/ -q
```

399 tests covering series catalog validation, scoring primitives, cross-lens analytics, macro vector construction, analog matching, forward-path statistics, briefing generation, and journal layer.

## What this is not

This is not an investment product, not financial advice, not a trading signal generator. It is an analytical framework for organizing how you look at US macro data. The outputs are yours to interpret.

Data sources are FRED only; no equity, options, or crypto feeds. Extend at will — the series catalog in `catalog/series.py` is the single source of truth for new data.

## License

[MIT](LICENSE).

## Acknowledgements

Built on top of the [fredapi](https://github.com/mortada/fredapi) library and the generosity of the Federal Reserve Bank of St. Louis in providing [FRED](https://fred.stlouisfed.org).
