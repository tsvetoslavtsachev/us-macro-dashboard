# Research Journal

This directory holds structured markdown notes about observations, hypotheses, and findings from the analysis workflow.

## Why is this directory mostly empty in the public repo?

By design. The public repo contains the **framework** — directory structure per topic, entry template, index generator. The actual journal entries are considered private research notes and are kept out of git (see `.gitignore`).

If you fork this project, your own `journal/credit/*.md`, `journal/labor/*.md` etc. stay on your machine.

## Structure

One subdirectory per topic:

- `labor/` — employment, wages, Sahm rule, JOLTS
- `inflation/` — CPI, PCE, expectations, stickiness
- `credit/` — HY/IG spreads, financial stress, lending standards
- `growth/` — GDP, industrial production, consumer activity
- `analogs/` — historical analog engine findings
- `regime/` — macro regime transitions
- `methodology/` — framework notes, calibration decisions

## Creating entries

Copy `_template.md` or use the helper:

```python
from scripts._utils import save_journal_entry

save_journal_entry(
    topic="credit",
    title="HY without VIX confirmation",
    body="## Question\n...\n## Finding\n...",
    tags=["hy_oas", "divergence"],
    status="open_question",  # or hypothesis / finding / decision
)
```

See `AGENT.md` in the repo root for the full Q&A workflow.

## Index

Build a local index (not committed):

```
python -m scripts.build_journal_index
```

This writes `journal/README.md` with a table of all entries grouped by topic. That file is `.gitignore`d because entry titles often contain context you would not want public.
