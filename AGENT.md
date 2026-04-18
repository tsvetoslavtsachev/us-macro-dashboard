# AGENT.md — Ориентация за Claude в тази сесия

Този файл обяснява как се ориентираш в проекта и как работи Q&A циклеът. Чети го **преди** да отговориш на въпрос, който изисква анализ на данни.

---

## Какво е econ_v2

Персонален research desk на Цветослав — economist и financial analyst. Дърпа макро серии от FRED, счита percentile scores и режими, генерира HTML briefing. Продуктът е **за лична употреба**, не за клиенти — пиши му като на колега-макроикономист, не за публика.

Езикът на анализите е български. Цифрите в стойности и percentile-ите са на английски (HY OAS, VIX, bp, pp), но коментарът и изводите са на български.

---

## Карта на проекта

```
econ_v2/
├── run.py                     ← единствен entry point
├── config.py                  ← FRED ключ, тегла, режими
├── catalog/series.py          ← регистър на всички FRED tickers
├── sources/fred_adapter.py    ← FRED fetch + cache
├── modules/                   ← 7 макро модула (labor, inflation, credit, ...)
├── analysis/
│   ├── macro_vector.py        ← 8-dim macro state + z-scoring
│   └── analog_engine.py       ← Historical Analog Engine
├── export/
│   ├── html_generator.py      ← dashboard
│   └── weekly_briefing.py     ← briefing + Свързани бележки секция
├── journal/                   ← markdown research notes (по тема)
│   ├── credit/ labor/ inflation/ growth/ analogs/ regime/ methodology/
│   └── _template.md
├── scripts/
│   ├── _utils.py              ← convenience loader layer (НЕ е публичен API)
│   ├── build_journal_index.py ← journal TOC
│   ├── sandbox/               ← ad hoc анализи (scratch)
│   └── saved/                 ← (резервирано за финализирани анализи)
├── data/cache.json            ← FRED cache
├── output/                    ← генерирани briefing/dashboard HTML-и
├── tests/                     ← pytest suite (399 теста)
├── FRAMEWORK.md               ← методология
├── PHASES.md                  ← развойен план
└── HANDOFF.md                 ← стар handoff doc (Фаза 1)
```

---

## Типични команди

```bash
# Ежедневен / седмичен briefing (с journal секция)
python run.py --briefing --with-journal

# Briefing + Historical Analogs (deep-history fetch)
python run.py --briefing --with-analogs --with-journal

# Рефреш на journal индекса (README.md в journal/)
python -m scripts.build_journal_index

# Тестове
pytest tests/ -q
```

Всички команди се изпълняват от `econ_v2/` root.

---

## Q&A Workflow — 5 стъпки

Когато Цветослав каже "прегледай X и ми кажи какво мислиш" или "провери дали Y е сигнал за Z", следвай това:

**1. Разбери въпроса.** Не бързай да пишеш код. Формулирай в един параграф какво питаме, защо е интересно и какво очакваме да видим. Това върви като `QUESTION` docstring в sandbox скрипта.

**2. Създай sandbox script.**
```python
from scripts._utils import new_sandbox_script
path = new_sandbox_script("HY spreads vs VIX divergence")
```
Създава `scripts/sandbox/YYYY-MM-DD_hy-spreads-vs-vix-divergence.py` с готов template със section markers.

**3. Зареди данните.** Никога не пипай FRED директно — минавай през loader-ите в `scripts/_utils.py`:
- `load_briefing_snapshot()` → dict[key, pd.Series] от cache-а
- `load_analog_series()` → deep-history серии за analog engine
- `load_current_briefing_html()` → текста на последния briefing

Ако серия липсва в snapshot-а, провери `catalog/series.py` — там са регистрирани всички tickers.

**4. Направи анализа.** Прости numpy/pandas трансформации — z-score, rolling correlation, percentile rank. Печатай междинни резултати. `core/scorer.py` има готови primitives: `percentile_rank`, `z_score`, `historical_context`.

**5. Ако струва — запиши journal entry.** В края на sandbox скрипта извикай:
```python
save_journal_entry(
    topic="credit",                    # един от VALID_TOPICS
    title="HY без VIX confirmation",
    body=finding,                      # markdown текст
    tags=["hy_oas", "vix", "divergence"],
    status="open_question",            # или hypothesis / finding / decision
    related_scripts=[str(Path(__file__).name)],
)
```

Записът ще се появи в следващия `python run.py --briefing --with-journal` в секцията "Свързани бележки". Ако анализът е негативен ("няма нищо там"), не записвай — sandbox-ът е scratch, изтрива се или се оставя без journal entry.

---

## Конвенции за journal entries

**Topic** — един от: `labor, inflation, credit, growth, analogs, regime, methodology`. Ако не пасва, обсъди с Цветослав преди да разширяваме листа.

**Status** — семантиката:
- `open_question` — забелязахме нещо, не знаем какво означава
- `hypothesis` — имаме обяснение, не е потвърдено
- `finding` — потвърдено наблюдение с данни
- `decision` — действие предприето (напр. влизане в позиция, промяна в рамката)

**Body** — markdown с секции: `## Въпрос`, `## Данни`, `## Анализ`, `## Извод`. Шаблонът е в `journal/_template.md`.

**Tags** — lowercase snake_case. FRED ticker-и малки (`hy_oas`, не `HY_OAS`). Концептуални тагове свободни (`divergence`, `regime_transition`, `sahm_rule`).

---

## Какво НЕ е задачата ти тук

- **Не е клиентски продукт.** Не пиши за "читателите", не правй executive summaries за външна аудитория. Цветослав е читателят.
- **Не измисляй данни.** Ако серия липсва — кажи го, не попълвай със syntetika.
- **Не пренаписвай core логика без нужда.** Sandbox скриптовете са scratch. Ако нещо се повтаря, извади го в `scripts/_utils.py`, а не в `modules/` или `analysis/`.
- **Не изтривай journal entries.** Ако запис е остарял, маркирай го със `status: decision` + бележка, или го премести в `journal/_archive/` (името с подчертавка → loader-ите го пропускат).

---

## Важни файлове за справка

- `FRAMEWORK.md` — пълната методология (analyst lens, intelligence brief)
- `PHASES.md` — кое е построено, кое остава
- `catalog/series.py` — всички FRED серии + какъв тип (level/yoy/mom)
- `config.py` — FRED ключ, teгла на модулите
- `journal/_template.md` — blueprint за нов запис

---

## Sandbox етикет

- `scripts/sandbox/` е scratch — пиши каквото искаш, commit-вай каквото искаш
- Ако анализ е завършен и си стойностен (reusable), премести го в `scripts/saved/` и направи го importable
- Ако sandbox скриптът има съответстващ journal entry, сложи reference-а в `related_scripts` на журналния entry
