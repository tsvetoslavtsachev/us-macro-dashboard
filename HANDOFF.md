# econ_v2 — Handoff Document
**Дата:** 17 Април 2026  
**Проект:** Economic Intelligence Dashboard v2.0

---

## Какво е проектът

Modular economic analysis система на Python — дърпа данни от FRED (Federal Reserve Economic Data), изчислява percentile scores за 7 макро модула, и генерира self-contained HTML dashboard. Крайната цел: един команд → HTML файл в браузъра → JSON за Claude нарация (Пазарен Пулс).

**Архитектурен избор:** Hybrid B+C — Analyst Lens Framework + Intelligence Brief Engine (препоръчан от предишна Opus сесия). Dashboard-ът е self-contained HTML, без Streamlit, без hosting, без разходи.

---

## Текущ статус — Фаза 1 ЗАВЪРШЕНА ✅

### Файлова структура
```
econ_v2/
├── run.py                  ← единствен entry point (python run.py)
├── config.py               ← FRED ключ, тегла, macro режими
├── core/
│   ├── fred_client.py      ← FRED API wrapper + 12h кеш в data/cache.json
│   ├── scorer.py           ← percentile_rank, z_score, sparkline, historical_context
│   └── __init__.py
├── modules/
│   ├── labor.py            ✅ 10 серии, 3 scores: Cyclical Health / AI Displacement / Fear Index
│   ├── inflation.py        ✅ 9 серии, 3 scores: Inflation Pulse / Expectations / Stickiness
│   ├── growth.py           ✅ 9 серии, 2 scores: Activity Pulse / Leading Signal
│   └── __init__.py
├── export/
│   ├── html_generator.py   ✅ self-contained HTML: composite gauge, module cards, sparklines, key readings table
│   └── __init__.py
├── output/
│   └── dashboard_YYYY-MM-DD_HHMM.html   ← генерира се при всяко стартиране
└── HANDOFF.md
```

### Как работи
1. `python run.py` — зарежда FRED данни (или кеш), изчислява модулите, генерира HTML, отваря в браузъра
2. Всеки модул връща: composite score (0-100), режим (напр. COOLING), sub-scores, sparklines, key readings
3. HTML е self-contained — само Plotly.js от CDN, всичко друго е embedded
4. Кешът е в `data/cache.json` — 12h TTL, не чака при всяко стартиране

### Инсталация (само веднъж)
```bash
pip install fredapi pandas numpy
```

### FRED API ключ
Read from `FRED_API_KEY` environment variable. See `README.md` and `.env.example`.

---

## Дизайн решения (важни)

- **Scoring методология:** percentile rank спрямо 2000–днес. Invert=True за серии, при които по-висока стойност = по-лошо (напр. UNRATE, ICSA).
- **YoY трансформация:** Level серии (INDPRO, RSXFS, CPI) се трансформират до YoY% преди scoring.
- **Потребителят НЕ е програмист** — всяко добавяне трябва да е self-contained в модула, без да пипа core логиката.

---

## Следващи фази

### Фаза 2 — Останалите 4 модула
Трябва да се добавят в `modules/` по същия pattern:
- `credit.py` — Credit & Financial Conditions (HY OAS, IG OAS, DRCCLACBS, MORTGAGE30US...)
- `housing.py` — Housing (HOUST, PERMIT, SPCS20RSA, NAHBMMI, MORTGAGE30US...)
- `fed.py` — Fed & Liquidity (FEDFUNDS, M2SL, WALCL, DGS2, DGS10...)
- `consumer.py` — Consumer & Sentiment (DSPIC96, PSAVERT, TDSP, NFIB...)

Плюс: radar chart в HTML-а с всичките 7 модула.

### Фаза 3 — Historical Analog Engine (STAR feature)
Файл: `core/analog_engine.py`  
Логика: взима текущия composite вектор (7 scores), сравнява с исторически периоди (1970-днес), връща top-3 closest episodes с "какво се е случило след 6/12 месеца".

### Фаза 4 — Integrations
- `export/json_export.py` → AI-ready JSON за Пазарен Пулс нарация
- VRM bridge → обновява VRM_STATE.md с macro data от системата

---

## Известни проблеми / бележки
- Sandbox-ът няма internet → тестван само с демо данни. На реалната машина работи.
- `RSXFS` може да е преименуван в FRED — провери при грешка (алтернатива: `RRSFS`)
- `JTSLDL` е Layoffs & Discharges — понякога е с лаг 2 месеца
