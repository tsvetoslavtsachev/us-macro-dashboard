# Economic Intelligence — The Economist's Lens
## Framework Document

**Създаден:** 2026-04-17
**Автор:** Цветослав Цачев + Claude (Opus 4.7)
**Статус:** Първоначална рамка, отворена за итерация

---

## 0. Предистория

Тази система замества концептуално `econ_stack` (v1, Streamlit) и надгражда `econ_v2` (Phase 1 MVP). Двата предишни опита построиха регим-класификатори с красиви gauges и composite 0-100 scores. Настоящият документ **изоставя** този подход и предлага фундаментално друга архитектура: не оценяваща, а **наблюдаваща** — аналитичен инструмент за икономист, не dashboard за преглед.

Предишните опити не се провалят в кода. Провалят се в рамката.

---

## 1. Философия — какво е и какво НЕ е

### Какво ЦЕЛИ системата
- Аналитичен мозък за макро-икономически анализ, интегриран в мисленето на потребителя
- Откриване на **тенденции, неравновесия, въпросителни, неизвестни**
- Осигуряване на **non-consensus** поглед — серии, които не са в mainstream наратива
- Подхранване на VRM с макро контекст (без override)
- Материал за Пазарен Пулс, семинари, YouTube съдържание
- Бъдещо разширение към Еврозоната за cross-region анализ

### Какво НЕ е системата
- **НЕ е регим-класификатор** — не произвежда "COOLING → HEALTHY → WEAK" етикети (VRM прави това)
- **НЕ е dashboard** с 0-100 composite score (методологически слабо, аналитично неинформативно)
- **НЕ е заместител на Bloomberg** (те имат visual polish; нашето е дълбочина на конкретни серии)
- **НЕ е прогностичен модел** — откровено наблюдава, не предсказва (аналозите предлагат прецеденти, не прогнози)

### Философски принцип
> "Данните вече ги има. Интелигентността е в какво ги питаш."

---

## 2. Архитектурна логика — четири лещи, три призми

### Вертикални лещи (тематични групи)
Всяка леща е колекция от серии, групирани по икономически смисъл, не по източник или тегло. Една серия може да участва в няколко лещи (напр. 30-year mortgage rate е в Liquidity **и** Housing).

Четирите лещи:
1. **Growth** — реална активност, производство, потребление, водещи индикатори
2. **Labor** — заетост, слак, заплати, структурни сдвигове
3. **Inflation** — ценови натиски, очаквания, market-implied, sticky components
4. **Liquidity & Credit** — финансови условия, Fed позиция, credit spreads

Подредбата отразява диагностичната йерархия: Growth задава контекст, Labor показва закъсняваща реалност, Inflation е реактивна, Liquidity задвижва пазарите.

### Хоризонтални призми (cross-cutting analyses)
Призмите не са серии. Те са **анализи върху лещите**.

1. **Breadth** — от колко серии в лещата идва сигналът (diffusion measure)
2. **Divergence** — кои серии си противоречат (вътре в лещата или между лещите)
3. **Non-consensus** — серии, които тихо се движат, но не са в headline наратива

### Матрицата
```
                Growth    Labor   Inflation   Liquidity
Breadth           ·         ·         ·           ·
Divergence        ·         ·         ·           ·
Non-consensus     ·         ·         ·           ·
```

Всяка клетка е анализ. Седмично се произвеждат 12 такива анализа.

---

## 3. Data Source Architecture

### Абстракция от първия ред
Никъде в аналитичния слой не се появява "fred". Серията е обект с `source` attribute. Това позволява безшевно добавяне на Eurostat (Фаза 5).

```python
# catalog/series.py — псевдокод
SERIES_CATALOG = {
    "UNRATE": {
        "source": "fred",
        "id": "UNRATE",
        "region": "US",
        "lens": ["labor"],
        "peer_group": "unemployment",
        "transform": "level",
        "historical_start": "1948-01-01",
        "release_schedule": "monthly",
        "typical_release": "first_friday",
        "narrative_hint": "Headline rate. Най-медийно коментираната серия. U-6 и CE16OV/CIVPART дават по-добра картина на real slack.",
    },
    "TRUCK_EMP": {
        "source": "fred",
        "id": "CES4348400001",
        "region": "US",
        "lens": ["labor", "growth"],
        "peer_group": "sectoral_employment",
        "transform": "yoy_pct",
        "historical_start": "1990-01-01",
        "release_schedule": "monthly",
        "typical_release": "first_friday",
        "narrative_hint": "Водещ sub-sector. Камионите усещат стопанския спад преди headline-а.",
        "tags": ["non_consensus"],
    },
    ...
}
```

### Adapters
- `sources/fred_adapter.py` — FredAPI заявки, кеш, retry
- `sources/eurostat_adapter.py` — Фаза 5+ (SDMX REST, без ключ)
- Общ интерфейс: `fetch(series_id) → DataFrame`

### Бележки за Eurostat
- Eurostat lagва FRED с 2-4 седмици за същия тип индикатор
- Това е **функция**, не бъг — cross-region lead/lag е аналитичен слой сам по себе си
- Кодировките са грозни (`une_rt_m`, `prc_hicp_manr`) — затова каталогът е решаващ

---

## 4. Series Catalog — дизайнерски решения

Всяка серия има пет типа полета:

**Идентичност:** `source`, `id`, `region`, `name_bg`, `name_en`
**Таксономия:** `lens` (може множество), `peer_group`, `tags` (standard / non_consensus / ai_exposure / structural)
**Обработка:** `transform` (level / yoy_pct / mom_pct / z_score / first_diff)
**Метаданни:** `historical_start`, `release_schedule`, `typical_release`, `revision_prone` (bool)
**Наратив:** `narrative_hint` (как се обяснява публично), `typical_misreadings` (опционално)

### Transform conventions
- Level series (UNRATE, FEDFUNDS, T10Y3M): използват се директно
- Index series (CPI, INDPRO, RSXFS): YoY% преди анализ
- Flow series (NFP change, housing starts): YoY или rolling 3m average
- Ratio series (PSAVERT): нивото е информативно

### Peer groups
Серия принадлежи към peer group за breadth изчисления. Пример: всички labor slack индикатори са един peer group. Когато 5 от 7 в групата отиват в една посока — breadth сигнал.

---

## 5. Analytical Primitives

Имплементирани в `core/primitives.py`. Всички анализи се строят върху тези базови операции.

### Ниво на серия
- `level(s)` — последно четене, форматирано
- `z_score(s, window)` — стандартизиране спрямо full-sample или rolling window
- `percentile(s, window)` — перцентил, използван като **референтна** информация, не като оценка
- `momentum(s, lookback)` — промяна спрямо N периода назад
- `acceleration(s)` — второ производно (промяна в momentum)
- `regime_duration(s, threshold)` — колко периода поредно стойността е над/под праг

### Ниво на peer group (breadth)
- `breadth_positive(group)` — % серии в група с positive momentum
- `breadth_extreme(group, threshold)` — % серии с `|z| > threshold`
- `diffusion_index(group)` — класически diffusion индекс (% increasing + 0.5 × % unchanged)

### Ниво на cross-group (divergence)
- `divergence(group_a, group_b)` — разлика между агрегатни сигнали
- `hard_soft_gap(hard_group, soft_group)` — специфичен divergence
- `leading_lagging_gap` — за Eurostat-US pairs (Фаза 5)

### Ниво на vector (analog matching — Фаза 4)
- `macro_vector(date)` — N-dimensional vector от текущи z-scores
- `cosine_similarity(v1, v2)`
- `nearest_analog(date, top_k)` — връща топ-3 най-близки исторически дати
- `forward_path(date, window)` — какво се е случило след N месеца

### Ниво на anomaly detection
- `anomaly_scan(date)` — всички серии с `|z| > 2` или ускорение в топ 5%
- `new_extreme(date, lookback)` — серии, които правят нов N-годишен extreme

---

## 6. Update Cadence & Event Awareness

### Cadence правило
- **Baseline:** седмично (обичайно петък вечер или понеделник сутрин)
- **Event-driven:** след NFP, CPI, PCE, Retail Sales, FOMC, JOLTS, Claims
- **On-demand:** по всяко време с `--force`

### Event calendar
Системата поддържа календар на очаквани releases:

```python
EVENT_CALENDAR = {
    "NFP":                 {"typical": "first_friday",     "affects": ["labor"]},
    "CPI":                 {"typical": "day_10_to_15",     "affects": ["inflation"]},
    "PCE":                 {"typical": "last_friday",      "affects": ["inflation"]},
    "Retail Sales":        {"typical": "day_15_to_17",     "affects": ["growth"]},
    "Industrial Production":{"typical": "day_15_to_17",    "affects": ["growth"]},
    "FOMC":                {"specific_dates": [...],        "affects": ["liquidity"]},
    "JOLTS":               {"typical": "first_tuesday",     "affects": ["labor"]},
    "Claims":              {"typical": "thursday_weekly",   "affects": ["labor"]},
}
```

### Cache strategy — адаптивен TTL
- Weekly series (Claims): TTL 3 дни
- Monthly series (NFP, CPI): TTL 10 дни
- Quarterly series (GDP): TTL 30 дни
- **Admin delay буфер:** при detection на забавяне в releases (като shutdown aftermath-а), системата **не** счита липсващ update за грешка — показва го в Data Status с бележка

### CLI интерфейс
```bash
python run.py                        # incremental update, briefing
python run.py --focus=labor          # force refresh labor, briefing за labor
python run.py --full-refresh         # свежи всичко
python run.py --status               # само data status screen
python run.py --export-json          # JSON за Пазарен Пулс
```

---

## 7. Output Products

Четири изходни продукта, приоритизирани.

### 7.1 Weekly Briefing — приоритет 1 (MVP)
HTML страница, организирана **lens-first** (не prism-first). Читателят чете една леща като блок, след това преминава към следващата. Cognitive flow над raw matrix.

**Структура:**

- **Executive Summary** (3-5 изречения, cross-lens)
- **Labor**
  - *Breadth* — колко серии потвърждават, в коя посока
  - *Divergence* — вътрешни противоречия в лещата
  - *Non-consensus* — non_consensus + ai_exposure + structural surfacing
- **Growth**
  - *Breadth*
  - *Divergence*
  - *Non-consensus*
- *(Inflation, Liquidity — добавят се от Фаза 3)*
- **Anomaly Feed** — cross-lens, топ 10 серии с `|z| > 2`
- **Cross-Lens Divergences** — напр. Labor vs Credit, hard vs soft
- **Fresh This Week** — какво беше освежено + обяснения на delays

Revision-prone серии с силен сигнал получават soft caveat (⚠ подлежи на ревизии). **Не показва всички серии** — показва **важното**. Това е ключовата разлика от Explorer-а.

### 7.2 Data Status Screen — приоритет 2 (operational + trust)
Отделна HTML страница със статут на всички серии:

| Series ID | Name (BG) | Lens | Last Obs | Last Refresh | Days Behind | Status |
|-----------|-----------|------|----------|--------------|-------------|--------|
| UNRATE    | Безработица headline | labor | 2026-02 | 2026-04-17 | 45 | ⏳ Delayed (shutdown) |

Status стойности:
- ✅ **Fresh** — в рамките на очаквания график
- ⏳ **Delayed (explained)** — лагва заради известна причина (shutdown, holiday)
- ⚠️ **Stale** — проблемно, нужно внимание
- 🔄 **Updated today**

Филтри по lens, source, status. Calendar view с предстоящи и излезли releases.

### 7.3 Explorer HTML — приоритет 3
Browseable страница с всички серии. Click на серия → details page със:
- Historical chart
- Z-score overlay
- Peer group context
- Narrative hint
- Related series

### 7.4 JSON Export за Пазарен Пулс — приоритет 4
Структуриран snapshot за нарация:

```json
{
  "as_of": "2026-04-17",
  "lenses": {
    "labor": {
      "signal_summary": "...",
      "breadth": 0.4,
      "notable_anomalies": [...]
    }
  },
  "anomaly_feed": [...],
  "divergences": [...],
  "non_consensus_picks": [...]
}
```

---

## 8. Non-Goals (изрично изключени)

**Не строим:**
- Composite 0-100 score на цялата икономика
- Режимни етикети HEALTHY / COOLING / STRESSED (VRM territory)
- Weighted averages на percentiles (mathematically unsound)
- Predictive modeling (forecasts, probability of recession и т.н.)
- Streamlit app (избрано: self-contained HTML)
- Hosted service (локално running, personal tool)
- "AI Displacement score" като first-class композитна метрика (слаба методология). Вместо това — `ai_exposure` peer group, който получава surfacing в Non-consensus **само** когато breadth в групата отиде в крайност

**Не оптимизираме за:**
- Скорост (кешът е 12h; приемлив latency)
- Visual polish (Bloomberg печели; ние сме за substance)
- Breadth of coverage (100+ серии не е цел; 30-50 качествени серии е)

---

## 9. Phase Roadmap

### Фаза 1 — Foundation (текуща, ~1 седмица)
- [x] FRAMEWORK.md (този документ)
- [ ] PHASES.md с детайлен breakdown
- [ ] Нова файлова структура (extending econ_v2)
- [ ] `catalog/series.py` с 30 серии за Labor + Growth
- [ ] `core/primitives.py` — z_score, momentum, breadth, anomaly_scan
- [ ] `sources/fred_adapter.py` — refactored, с event-aware cache
- [ ] Data Status Screen HTML generator
- [ ] Smoke test с реални данни

### Фаза 2 — Weekly Briefing MVP (~1 седмица)
- [ ] `analysis/anomaly_detector.py`
- [ ] `analysis/divergence_scanner.py`
- [ ] `analysis/non_consensus_finder.py`
- [ ] `export/weekly_briefing.py` — HTML generator
- [ ] Първо седмично използване → feedback loop

### Фаза 3 — Inflation + Liquidity + Explorer (~1-2 седмици)
- [ ] Добавяне на Inflation lens в каталога
- [ ] Liquidity & Credit lens
- [ ] Explorer HTML — browseable серия изглед

### Фаза 4 — Analog Engine (~2 седмици)
- [ ] `analysis/macro_vector.py`
- [ ] `analysis/analog_matcher.py`
- [ ] Integration в Weekly Briefing
- [ ] Forward path visualization (прилики И разлики)

### Фаза 5 — Eurostat Integration (~2 седмици, когато Фаза 4 е стабилна)
- [ ] `sources/eurostat_adapter.py`
- [ ] Добавяне на EU серии в каталога
- [ ] Cross-region divergence анализ
- [ ] US-EU analog matching

### Фаза 6 — JSON Export + VRM Bridge
- [ ] `export/json_snapshot.py`
- [ ] Пазарен Пулс integration
- [ ] VRM macro context bridge

---

## 10. Decision Log

Всяко нетривиално решение влиза тук с дата и мотивация.

### 2026-04-17 — Отказваме composite 0-100 score
**Причина:** Средното на percentile ranks не е percentile rank. Унищожава информация. Прикрива важни divergence signals.
**Алтернатива:** Signal density map — колко серии в лещата са в екстрем, в каква посока.

### 2026-04-17 — Отказваме регим-класификация
**Причина:** VRM вече го прави за пазарни цели. Дублирането би било конкурентно, не комплементарно. Икономическата регим-класификация е груба и губи нюанс.
**Алтернатива:** Дескриптивен сигнален поглед. Лещите са дескрипции, не класификации.

### 2026-04-17 — Weekly Briefing (B) е първи output
**Причина:** Той най-бързо показва дали системата вижда нещо интересно. Explorer е по-красив, но бавно revealing. JSON е derivative.
**~~Update 2026-04-17~~:** Ред на изпълнение променен — виж "Phase 2 restructure" по-долу. Briefing остава първият analyst-facing output, но се строи **след** catalog expansion (Phase 2), не паралелно с labor-only scope.

### 2026-04-17 — Full-sample 1970+ като референтен кадър
**Причина:** Без достатъчно история аналозите не работят. 2000+ е твърде скорошно.
**Компромис:** Серии, които започват по-късно (напр. T5YIE от 2003), се обслужват с truncated history — системата е прозрачна за това.

### 2026-04-17 — Data source абстракция от първия ред
**Причина:** Еврозоната идва. Ако я добавим retrofit, ще пренапишем всичко.

### 2026-04-17 — Data Status Screen е first-class продукт
**Причина:** Admin shutdown aftermath показва, че стабилността на данните не е даденост. Потребителят трябва да вижда какво е fresh, какво закъснява, защо.

### 2026-04-17 — Briefing структура е lens-first, не prism-first
**Причина:** Читателят (икономист) мисли по теми, не по анализни операции. Четирите лещи като блокове с трите призми под всяка дават по-добър cognitive flow от matrix 4×3.

### 2026-04-17 — AI Exposure Watch е peer group, не score
**Причина:** Тематиката "AI effect на заетост" е важна, но няма чиста метрика. Peer group с tag `ai_exposure` и surfacing **само** при breadth extreme дава видимост без да фабрикува false precision.

### 2026-04-17 — Wage dynamics получава собствен peer group
**Причина:** Заплатите са едновременно inflation driver и welfare метрика. Average Hourly Earnings (CES0500000003) страда от composition effects; ECIWAG и Atlanta Fed Wage Tracker контролират за това. Три серии заедно дават триангулация.

### 2026-04-17 — Labor share е `structural` tag, не cyclical
**Причина:** Capital-labor split е режимна величина, не cycle. Интерпретирай на 5-10 годишни хоризонти. Ако я третираме cyclically, тя ще шумим.

### 2026-04-17 — Revisions: минимален aware подход, без vintage tracking
**Причина:** Full revision tracking (ALFRED API) е собствен проект. За MVP: `revision_prone: true` флаг + soft caveat в briefing при силен сигнал. Aware-ност без разход.

### 2026-04-17 — Phase 2 restructure: catalog-first, not briefing-first
**Причина:** Лавалният briefing с labor-only сигнали създава двоен learning curve — първо се учим на labor-in-isolation, после пак на 4-lens briefing. Цветослав избра да изчакаме каталогът да покрие всичките 4 лещи (inflation + liquidity & credit, Phase 2) преди да строим briefing engine (нов Phase 3).
**Импликация:** PHASES.md актуализиран; стар Phase 2 (Weekly Briefing) се слива с Phase 3 (Inflation + Liquidity + Explorer) в нов Phase 3.

### 2026-04-17 — Executive Summary: пропуска се до Phase 6 (LLM)
**Причина:** Template-based summary с попълнени числа ("Labor lens: breadth 60% positive, 2 non-consensus сигнала...") е narratively тъп и с висок риск да звучи механично. По-добре briefing-ът да представя signals директно, а истинската нарация да дойде от LLM (Пазарен Пулс skill) в Phase 6.
**Импликация:** Phase 3 briefing няма Executive Summary секция. Читателят първо вижда lens блокове.

### 2026-04-17 — Briefing остава non-default entry point
**Причина:** Legacy dashboard работи и се ползва; смяната на default-а без потребителска валидация на briefing-а би било тиха счупване на workflow. Освен това legacy показва composite 0-100 score — философски противоречащ на новата рамка. Default switch е решение след 2-3 седмичен реален use на briefing-а.
**Импликация:** Phase 3 добавя `--briefing` flag; `python run.py` остава legacy до бъдещо решение.

---

## Приложение А — Стартов списък серии (Labor + Growth, ~38 серии)

**Означения:** ⭐ non_consensus | 🤖 ai_exposure | 🏗️ structural | ⚠ revision_prone

### Labor (23 серии, групирани по peer_group)

**unemployment (5):**
- UNRATE — headline unemployment
- U6RATE — broad slack
- EMRATIO — employment-population ratio
- CIVPART — labor force participation
- UEMPMEAN — mean duration of unemployment

**sectoral_employment (6):**
- PAYEMS — total NFP ⚠
- USPRIV — private payrolls ⚠
- MANEMP — manufacturing employment ⚠
- CES4348400001 — truck transport employment ⭐
- TEMPHELPS — temp help services ⭐ 🤖
- USINFO — information sector ⭐ 🤖

**ai_exposure (3, extra):**
- CES5415000001 — computer systems design 🤖
- CES6054000001 — professional/technical services 🤖
- CES5112100001 — software publishing 🤖 *(ако е достъпна)*

**claims (3):**
- ICSA — initial claims (weekly)
- ICSA4 — 4-week MA initial claims ⭐
- CCSA — continued claims

**flow (3):**
- JTSJOL — job openings
- JTSQUR — quits rate ⭐
- JTSLDL — layoffs & discharges

**wage_dynamics (3):**
- CES0500000003 — average hourly earnings ⚠
- ECIWAG — Employment Cost Index, wages *(quarterly, composition-controlled)*
- FRBATLWGT — Atlanta Fed Wage Growth Tracker *(median, matched-worker)*

**hours (1):**
- AWHAETP — average weekly hours

**labor_share (2, структурни):**
- W273RE1A156NBEA — compensation of employees / GDP 🏗️
- PRS85006173 — labor share nonfarm business 🏗️

### Growth (15 серии)

**hard_activity (5):**
- GDPC1 — real GDP (quarterly) ⚠
- INDPRO — industrial production ⚠
- RSXFS — retail sales ⚠
- PCEC96 — real PCE
- DGORDER — durable goods orders

**leading (4):**
- USSLIND — Philly Fed leading index
- CFNAI — Chicago Fed activity
- PERMIT — building permits (leading)
- HOUST — housing starts *(воден индикатор преди 2008; потвърждава PERMIT след 1-2 месечен lag)*

**surveys (4):**
- NAPMPMI — ISM manufacturing (ако е достъпна)
- NAPMNMI — ISM services (ако е достъпна)
- UMCSENT — Michigan sentiment
- CSCICP03USM665S — CB consumer confidence

**business_sentiment (1):**
- BSCICP03USM665S — OECD business confidence

*MANEMP е в Labor lens, но Growth я reference-ва за cross-lens анализ (hard activity consistency).*

### Tag legend

- ⭐ **non_consensus** — излиза в Non-consensus Watch при значимо движение
- 🤖 **ai_exposure** — peer group surfacing само при breadth extreme
- 🏗️ **structural** — не cyclical; показва режимни сдвигове (интерпретирай на 5-10 годишни хоризонти)
- ⚠ **revision_prone** — soft caveat в briefing при силен сигнал

---

## Приложение Б — Review cadence

Този FRAMEWORK.md подлежи на review:
- **Всяка завършена фаза:** мини-review — кои решения оцеляха, кои се промениха
- **Всеки 3 месеца:** пълен review
- **Ad-hoc:** когато нещо фундаментално се пречупи

Промените влизат в Decision Log (секция 10).

---

**Край на рамковия документ.**
**Следващ файл:** `PHASES.md` — детайлен план на Фаза 1.
