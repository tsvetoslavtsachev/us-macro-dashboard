"""
catalog/series.py
=================
Декларативен каталог на икономическите серии.

Всяка серия е self-contained запис с идентичност, таксономия, обработка,
метаданни и narrative hint. Системата е построена, за да може тук да се
добавят серии, без да се пипа аналитичен код.

За референция на полетата — FRAMEWORK.md, секция 4.
"""
from __future__ import annotations

from typing import Any

# ============================================================
# ALLOWED VALUES (за validation)
# ============================================================

ALLOWED_SOURCES = {"fred", "eurostat", "pending"}  # "pending" = Phase 3+ integration
ALLOWED_REGIONS = {"US", "EU", "GLOBAL"}
ALLOWED_LENSES = {"labor", "growth", "inflation", "liquidity", "housing"}
ALLOWED_TRANSFORMS = {"level", "yoy_pct", "mom_pct", "z_score", "first_diff"}
ALLOWED_TAGS = {"non_consensus", "ai_exposure", "structural"}
ALLOWED_SCHEDULES = {"weekly", "monthly", "quarterly", "annually"}


# ============================================================
# SERIES CATALOG
# ============================================================
# Структура на запис:
#   source: "fred" | "eurostat" | "pending"
#   id: FRED код (или вътрешен идентификатор)
#   region: "US" | "EU" | "GLOBAL"
#   name_bg, name_en
#   lens: list[str]
#   peer_group: str
#   tags: list[str]
#   transform: str
#   historical_start: "YYYY-MM-DD"
#   release_schedule: "weekly" | "monthly" | "quarterly"
#   typical_release: свободен текст
#   revision_prone: bool
#   narrative_hint: str
# ============================================================

SERIES_CATALOG: dict[str, dict[str, Any]] = {

    # ───────────────────────────────────────────────────────
    # LABOR / unemployment
    # ───────────────────────────────────────────────────────

    "UNRATE": {
        "source": "fred",
        "id": "UNRATE",
        "region": "US",
        "name_bg": "Безработица (headline, U-3)",
        "name_en": "Unemployment Rate",
        "lens": ["labor"],
        "peer_group": "unemployment",
        "tags": [],
        "transform": "level",
        "historical_start": "1948-01-01",
        "release_schedule": "monthly",
        "typical_release": "first_friday",
        "revision_prone": False,
        "narrative_hint": "Headline rate. Най-медийно коментираната серия. U-6 и EMRATIO дават по-добра картина на real slack.",
    },
    "U6RATE": {
        "source": "fred",
        "id": "U6RATE",
        "region": "US",
        "name_bg": "Безработица (U-6, broad slack)",
        "name_en": "U-6 Total Unemployed + Underemployed",
        "lens": ["labor"],
        "peer_group": "unemployment",
        "tags": [],
        "transform": "level",
        "historical_start": "1994-01-01",
        "release_schedule": "monthly",
        "typical_release": "first_friday",
        "revision_prone": False,
        "narrative_hint": "Включва разочаровани и частично заети. По-честна мярка на реалния slack.",
    },
    "EMRATIO": {
        "source": "fred",
        "id": "EMRATIO",
        "region": "US",
        "name_bg": "Заетост/население (prime-age proxy)",
        "name_en": "Employment-Population Ratio",
        "lens": ["labor"],
        "peer_group": "unemployment",
        "tags": [],
        "transform": "level",
        "historical_start": "1948-01-01",
        "release_schedule": "monthly",
        "typical_release": "first_friday",
        "revision_prone": False,
        "narrative_hint": "Не зависи от definition на 'active labor force'. По-стабилен индикатор на дълбоката заетост.",
    },
    "CIVPART": {
        "source": "fred",
        "id": "CIVPART",
        "region": "US",
        "name_bg": "Коефициент на участие (LFPR)",
        "name_en": "Labor Force Participation Rate",
        "lens": ["labor"],
        "peer_group": "unemployment",
        "tags": [],
        "transform": "level",
        "historical_start": "1948-01-01",
        "release_schedule": "monthly",
        "typical_release": "first_friday",
        "revision_prone": False,
        "narrative_hint": "Структурни сдвигове (демография, ранно пенсиониране). Пост-COVID не се възстанови напълно.",
    },
    "UEMPMEAN": {
        "source": "fred",
        "id": "UEMPMEAN",
        "region": "US",
        "name_bg": "Средна продължителност на безработицата",
        "name_en": "Mean Duration of Unemployment",
        "lens": ["labor"],
        "peer_group": "unemployment",
        "tags": [],
        "transform": "level",
        "historical_start": "1948-01-01",
        "release_schedule": "monthly",
        "typical_release": "first_friday",
        "revision_prone": False,
        "narrative_hint": "Когато расте, сигнализира структурни проблеми (quality of labor market).",
    },

    # ───────────────────────────────────────────────────────
    # LABOR / sectoral_employment
    # ───────────────────────────────────────────────────────

    "PAYEMS": {
        "source": "fred",
        "id": "PAYEMS",
        "region": "US",
        "name_bg": "NFP (общо заети извън селско стопанство)",
        "name_en": "All Employees, Total Nonfarm",
        "lens": ["labor"],
        "peer_group": "sectoral_employment",
        "tags": [],
        "transform": "yoy_pct",
        "historical_start": "1939-01-01",
        "release_schedule": "monthly",
        "typical_release": "first_friday",
        "revision_prone": True,
        "narrative_hint": "Headline NFP. Подлежи на значителни ревизии — особено в turning points. Преглеждай и 3-месечно MA.",
    },
    "USPRIV": {
        "source": "fred",
        "id": "USPRIV",
        "region": "US",
        "name_bg": "Заети в частния сектор",
        "name_en": "All Employees, Total Private",
        "lens": ["labor"],
        "peer_group": "sectoral_employment",
        "tags": [],
        "transform": "yoy_pct",
        "historical_start": "1939-01-01",
        "release_schedule": "monthly",
        "typical_release": "first_friday",
        "revision_prone": True,
        "narrative_hint": "Без държавния сектор — по-добра мярка на пазарната икономика.",
    },
    "MANEMP": {
        "source": "fred",
        "id": "MANEMP",
        "region": "US",
        "name_bg": "Заети в производството",
        "name_en": "All Employees, Manufacturing",
        "lens": ["labor", "growth"],
        "peer_group": "sectoral_employment",
        "tags": [],
        "transform": "yoy_pct",
        "historical_start": "1939-01-01",
        "release_schedule": "monthly",
        "typical_release": "first_friday",
        "revision_prone": True,
        "narrative_hint": "Цикличен сектор; често води другите по downturn.",
    },
    "TRUCK_EMP": {
        "source": "fred",
        "id": "CES4348400001",
        "region": "US",
        "name_bg": "Заети: автомобилен транспорт (камиони)",
        "name_en": "Truck Transportation Employment",
        "lens": ["labor", "growth"],
        "peer_group": "sectoral_employment",
        "tags": ["non_consensus"],
        "transform": "yoy_pct",
        "historical_start": "1990-01-01",
        "release_schedule": "monthly",
        "typical_release": "first_friday",
        "revision_prone": False,
        "narrative_hint": "Камионите усещат стопанския спад преди headline-а. Freight recession през 2023-2024 се виждаше тук месеци по-рано.",
    },
    "TEMPHELPS": {
        "source": "fred",
        "id": "TEMPHELPS",
        "region": "US",
        "name_bg": "Temp help services (заетост)",
        "name_en": "Temporary Help Services Employment",
        "lens": ["labor"],
        "peer_group": "sectoral_employment",
        "tags": ["non_consensus", "ai_exposure"],
        "transform": "yoy_pct",
        "historical_start": "1990-01-01",
        "release_schedule": "monthly",
        "typical_release": "first_friday",
        "revision_prone": False,
        "narrative_hint": "Ранна жертва на автоматизация и recession. Работодатели първо спират temp преди permanent.",
    },
    "USINFO": {
        "source": "fred",
        "id": "USINFO",
        "region": "US",
        "name_bg": "Информационен сектор (заетост)",
        "name_en": "Information Sector Employment",
        "lens": ["labor"],
        "peer_group": "sectoral_employment",
        "tags": ["non_consensus", "ai_exposure"],
        "transform": "yoy_pct",
        "historical_start": "1990-01-01",
        "release_schedule": "monthly",
        "typical_release": "first_friday",
        "revision_prone": False,
        "narrative_hint": "Tech-тежък сектор. AI tooling може да го свие — следи за layoffs в пъти на стабилна икономика.",
    },

    # ───────────────────────────────────────────────────────
    # LABOR / ai_exposure (extra sub-sectors)
    # ───────────────────────────────────────────────────────

    "COMP_DESIGN": {
        "source": "fred",
        "id": "CES6054150001",
        "region": "US",
        "name_bg": "Компютърен дизайн и услуги (заетост)",
        "name_en": "Computer Systems Design Employment",
        "lens": ["labor"],
        "peer_group": "ai_exposure",
        "tags": ["ai_exposure"],
        "transform": "yoy_pct",
        "historical_start": "1990-01-01",
        "release_schedule": "monthly",
        "typical_release": "first_friday",
        "revision_prone": False,
        "narrative_hint": "Ironic: сектор, който строи AI, но също може да бъде rationalized от него. Следи за юнoри-нива.",
    },
    "PROF_TECH_SERV": {
        "source": "fred",
        "id": "CES6054000001",
        "region": "US",
        "name_bg": "Професионални и технически услуги (заетост)",
        "name_en": "Professional & Technical Services Employment",
        "lens": ["labor"],
        "peer_group": "ai_exposure",
        "tags": ["ai_exposure"],
        "transform": "yoy_pct",
        "historical_start": "1990-01-01",
        "release_schedule": "monthly",
        "typical_release": "first_friday",
        "revision_prone": False,
        "narrative_hint": "Консултанти, адвокати, счетоводители — бели якички. Високо AI exposure за middle-office функции.",
    },
    "SOFT_PUB": {
        "source": "fred",
        "id": "CES5051200001",
        "region": "US",
        "name_bg": "Софтуерни компании (заетост)",
        "name_en": "Software Publishers Employment",
        "lens": ["labor"],
        "peer_group": "ai_exposure",
        "tags": ["ai_exposure"],
        "transform": "yoy_pct",
        "historical_start": "1990-01-01",
        "release_schedule": "monthly",
        "typical_release": "first_friday",
        "revision_prone": False,
        "narrative_hint": "Тясна категория. Ако е недостъпна на FRED, fallback към USINFO.",
    },

    # ───────────────────────────────────────────────────────
    # LABOR / claims
    # ───────────────────────────────────────────────────────

    "ICSA": {
        "source": "fred",
        "id": "ICSA",
        "region": "US",
        "name_bg": "Нови молби за помощи (седмично)",
        "name_en": "Initial Claims for Unemployment Insurance",
        "lens": ["labor"],
        "peer_group": "claims",
        "tags": [],
        "transform": "level",
        "historical_start": "1967-01-01",
        "release_schedule": "weekly",
        "typical_release": "thursday",
        "revision_prone": False,
        "narrative_hint": "Високочестотен early-warning сигнал. Шумни weekly data — предпочитай IC4WSA за тренд.",
    },
    "IC4WSA": {
        "source": "fred",
        "id": "IC4WSA",
        "region": "US",
        "name_bg": "Нови молби — 4-седмично MA",
        "name_en": "Initial Claims, 4-Week Moving Average",
        "lens": ["labor"],
        "peer_group": "claims",
        "tags": ["non_consensus"],
        "transform": "level",
        "historical_start": "1967-01-01",
        "release_schedule": "weekly",
        "typical_release": "thursday",
        "revision_prone": False,
        "narrative_hint": "По-устойчив от weekly claims. Използва се за turning point detection в labor market.",
    },
    "CCSA": {
        "source": "fred",
        "id": "CCSA",
        "region": "US",
        "name_bg": "Продължителни молби за помощи",
        "name_en": "Continued Claims",
        "lens": ["labor"],
        "peer_group": "claims",
        "tags": [],
        "transform": "level",
        "historical_start": "1967-01-01",
        "release_schedule": "weekly",
        "typical_release": "thursday",
        "revision_prone": False,
        "narrative_hint": "Ако continued claims растат, докато initial claims са стабилни — hiring се е забавил.",
    },

    # ───────────────────────────────────────────────────────
    # LABOR / flow (JOLTS)
    # ───────────────────────────────────────────────────────

    "JTSJOL": {
        "source": "fred",
        "id": "JTSJOL",
        "region": "US",
        "name_bg": "Свободни работни места (JOLTS)",
        "name_en": "Job Openings Total",
        "lens": ["labor"],
        "peer_group": "flow",
        "tags": [],
        "transform": "level",
        "historical_start": "2000-12-01",
        "release_schedule": "monthly",
        "typical_release": "first_tuesday",
        "revision_prone": False,
        "narrative_hint": "Vacancy rate е labor demand proxy. Gap с unemployed е Beveridge curve.",
    },
    "JTSQUR": {
        "source": "fred",
        "id": "JTSQUR",
        "region": "US",
        "name_bg": "Quits rate — напускания",
        "name_en": "Quits Rate",
        "lens": ["labor"],
        "peer_group": "flow",
        "tags": ["non_consensus"],
        "transform": "level",
        "historical_start": "2000-12-01",
        "release_schedule": "monthly",
        "typical_release": "first_tuesday",
        "revision_prone": False,
        "narrative_hint": "Работническа увереност. Ако quits rate пада — хората задържат работата си (pre-recession pattern).",
    },
    "JTSLDL": {
        "source": "fred",
        "id": "JTSLDL",
        "region": "US",
        "name_bg": "Освобождавания (layoffs)",
        "name_en": "Layoffs and Discharges",
        "lens": ["labor"],
        "peer_group": "flow",
        "tags": [],
        "transform": "level",
        "historical_start": "2000-12-01",
        "release_schedule": "monthly",
        "typical_release": "first_tuesday",
        "revision_prone": False,
        "narrative_hint": "Директна мярка за преход към reducing employment. Преди 2008 и 2020 ясно скача.",
    },

    # ───────────────────────────────────────────────────────
    # LABOR / wage_dynamics
    # ───────────────────────────────────────────────────────

    "AHE": {
        "source": "fred",
        "id": "CES0500000003",
        "region": "US",
        "name_bg": "Средна почасова заплата (AHE, all employees)",
        "name_en": "Average Hourly Earnings, Total Private",
        "lens": ["labor", "inflation"],
        "peer_group": "wage_dynamics",
        "tags": [],
        "transform": "yoy_pct",
        "historical_start": "2006-03-01",
        "release_schedule": "monthly",
        "typical_release": "first_friday",
        "revision_prone": True,
        "narrative_hint": "Headline wage метрика. Страда от composition effects (при fires в low-wage сектори — привидно ръст).",
    },
    "ECIWAG": {
        "source": "fred",
        "id": "ECIWAG",
        "region": "US",
        "name_bg": "Employment Cost Index — заплати",
        "name_en": "Employment Cost Index: Wages and Salaries",
        "lens": ["labor", "inflation"],
        "peer_group": "wage_dynamics",
        "tags": [],
        "transform": "yoy_pct",
        "historical_start": "1980-01-01",
        "release_schedule": "quarterly",
        "typical_release": "last_friday_of_month_post_quarter",
        "revision_prone": False,
        "narrative_hint": "По-добра от AHE — контролира за composition. Fed предпочита ECI за wage pressure readings.",
    },
    # ───────────────────────────────────────────────────────
    # LABOR / hours
    # ───────────────────────────────────────────────────────

    "AWHAETP": {
        "source": "fred",
        "id": "AWHAETP",
        "region": "US",
        "name_bg": "Средно отработени часове",
        "name_en": "Average Weekly Hours, Total Private",
        "lens": ["labor"],
        "peer_group": "hours",
        "tags": [],
        "transform": "level",
        "historical_start": "2006-03-01",
        "release_schedule": "monthly",
        "typical_release": "first_friday",
        "revision_prone": False,
        "narrative_hint": "Работодатели първо режат часове, после хора. Falling hours е early weakness signal.",
    },
    "AWHMAN": {
        "source": "fred",
        "id": "AWHMAN",
        "region": "US",
        "name_bg": "Средно отработени часове — производство",
        "name_en": "Average Weekly Hours, Manufacturing",
        "lens": ["labor"],
        "peer_group": "hours",
        "tags": [],
        "transform": "level",
        "historical_start": "1939-01-01",
        "release_schedule": "monthly",
        "typical_release": "first_friday",
        "revision_prone": False,
        "narrative_hint": "Цикличен индикатор. Manufacturing hours реагират първи в цикъла.",
    },
    "AWOTMAN": {
        "source": "fred",
        "id": "AWOTMAN",
        "region": "US",
        "name_bg": "Overtime часове — производство",
        "name_en": "Average Weekly Overtime Hours, Manufacturing",
        "lens": ["labor"],
        "peer_group": "hours",
        "tags": [],
        "transform": "level",
        "historical_start": "1956-01-01",
        "release_schedule": "monthly",
        "typical_release": "first_friday",
        "revision_prone": False,
        "narrative_hint": "Най-цикличният hours компонент. Overtime пада 6+ месеца преди recession.",
    },

    # ───────────────────────────────────────────────────────
    # LABOR / labor_share (structural)
    # ───────────────────────────────────────────────────────

    "COMP_GDP_SHARE": {
        "source": "fred",
        "id": "W273RE1A156NBEA",
        "region": "US",
        "name_bg": "Заплати като дял от БВП",
        "name_en": "Compensation of Employees as % of GDP",
        "lens": ["labor", "inflation"],
        "peer_group": "labor_share",
        "tags": ["structural"],
        "transform": "level",
        "historical_start": "1947-01-01",
        "release_schedule": "annually",
        "typical_release": "end_of_year",
        "revision_prone": False,
        "narrative_hint": "Капитал-труд разпределение. Интерпретирай на 10-год. хоризонт. Низходящ от 1970-те — inequality driver.",
    },
    "LABOR_SHARE_NBS": {
        "source": "fred",
        "id": "PRS85006173",
        "region": "US",
        "name_bg": "Labor share — нефермерски бизнес",
        "name_en": "Labor Share, Nonfarm Business Sector",
        "lens": ["labor", "inflation"],
        "peer_group": "labor_share",
        "tags": ["structural"],
        "transform": "level",
        "historical_start": "1947-01-01",
        "release_schedule": "quarterly",
        "typical_release": "quarterly_productivity_release",
        "revision_prone": False,
        "narrative_hint": "BLS productivity data. Cyclical fluctuations, но структурният trend е низходящ.",
    },

    # ───────────────────────────────────────────────────────
    # GROWTH / hard_activity
    # ───────────────────────────────────────────────────────

    "GDPC1": {
        "source": "fred",
        "id": "GDPC1",
        "region": "US",
        "name_bg": "Реален БВП (QoQ annualized)",
        "name_en": "Real Gross Domestic Product",
        "lens": ["growth"],
        "peer_group": "hard_activity",
        "tags": [],
        "transform": "yoy_pct",
        "historical_start": "1947-01-01",
        "release_schedule": "quarterly",
        "typical_release": "month_after_quarter_end",
        "revision_prone": True,
        "narrative_hint": "Headline growth. 3 releases: advance → second → third. Ревизиите могат да сменят sign.",
    },
    "INDPRO": {
        "source": "fred",
        "id": "INDPRO",
        "region": "US",
        "name_bg": "Индустриално производство",
        "name_en": "Industrial Production Index",
        "lens": ["growth"],
        "peer_group": "hard_activity",
        "tags": [],
        "transform": "yoy_pct",
        "historical_start": "1919-01-01",
        "release_schedule": "monthly",
        "typical_release": "day_15_to_17",
        "revision_prone": True,
        "narrative_hint": "Includes manufacturing + mining + utilities. Утилити се влияят от времето (зима/лято шум).",
    },
    "RSXFS": {
        "source": "fred",
        "id": "RSXFS",
        "region": "US",
        "name_bg": "Продажби на дребно (без храна)",
        "name_en": "Advance Retail Sales: Ex Food Services",
        "lens": ["growth"],
        "peer_group": "hard_activity",
        "tags": [],
        "transform": "yoy_pct",
        "historical_start": "1992-01-01",
        "release_schedule": "monthly",
        "typical_release": "day_15_to_17",
        "revision_prone": True,
        "narrative_hint": "Не е inflation-adjusted — внимавай при висока inflation (номинален ръст подвеждащ).",
    },
    "PCEC96": {
        "source": "fred",
        "id": "PCEC96",
        "region": "US",
        "name_bg": "Реално лично потребление",
        "name_en": "Real Personal Consumption Expenditures",
        "lens": ["growth"],
        "peer_group": "hard_activity",
        "tags": [],
        "transform": "yoy_pct",
        "historical_start": "1959-01-01",
        "release_schedule": "monthly",
        "typical_release": "last_friday",
        "revision_prone": False,
        "narrative_hint": "Real PCE — inflation-adjusted consumer spending. Около 70% от GDP.",
    },
    "DGORDER": {
        "source": "fred",
        "id": "DGORDER",
        "region": "US",
        "name_bg": "Нови поръчки за дълготрайни стоки",
        "name_en": "Durable Goods New Orders",
        "lens": ["growth"],
        "peer_group": "hard_activity",
        "tags": [],
        "transform": "yoy_pct",
        "historical_start": "1992-01-01",
        "release_schedule": "monthly",
        "typical_release": "day_25_to_28",
        "revision_prone": True,
        "narrative_hint": "Aircraft orders са шумни (Boeing cycles). Preferred view: ex-transportation.",
    },

    # ───────────────────────────────────────────────────────
    # GROWTH / leading
    # ───────────────────────────────────────────────────────
    # 2026-04-28: USSLIND (Philly Fed Leading Index) премахнат — FRED спира
    # публикация на 2020-02-01 (discontinued). Заменен с CFNAI в leading basket.

    "CFNAI": {
        "source": "fred",
        "id": "CFNAI",
        "region": "US",
        "name_bg": "Chicago Fed National Activity Index",
        "name_en": "Chicago Fed National Activity Index",
        "lens": ["growth"],
        "peer_group": "business_sentiment",
        "tags": [],
        "transform": "level",
        "historical_start": "1967-03-01",
        "release_schedule": "monthly",
        "typical_release": "end_of_month",
        "revision_prone": True,
        "narrative_hint": "Композит от 85 индикатора в 4 категории. Zero = trend growth. Класически recession trigger: CFNAIMA3 < -0.7 → recession probable.",
    },
    "PERMIT": {
        "source": "fred",
        "id": "PERMIT",
        "region": "US",
        "name_bg": "Разрешения за строителство",
        "name_en": "New Private Housing Units Authorized by Building Permits",
        "lens": ["growth", "housing"],
        "peer_group": "leading",
        "tags": [],
        "transform": "yoy_pct",
        "historical_start": "1960-01-01",
        "release_schedule": "monthly",
        "typical_release": "day_15_to_17",
        "revision_prone": False,
        "narrative_hint": "Leading housing + growth. Permits водят starts с 1-2 месечен lag.",
    },
    "HOUST": {
        "source": "fred",
        "id": "HOUST",
        "region": "US",
        "name_bg": "Жилищни старт-ове",
        "name_en": "Housing Starts",
        "lens": ["growth", "housing"],
        "peer_group": "leading",
        "tags": [],
        "transform": "yoy_pct",
        "historical_start": "1959-01-01",
        "release_schedule": "monthly",
        "typical_release": "day_15_to_17",
        "revision_prone": False,
        "narrative_hint": "Колапсва преди ипотечната криза 2006-2007 — класически leading signal.",
    },

    # ───────────────────────────────────────────────────────
    # GROWTH / business_sentiment + consumer_sentiment (Phase 2.5)
    # Секцията `surveys` разтворена в две по-фокусирани peer_groups.
    # Бележка: ISM PMI-ите (NAPMPMI/NAPMNMI) са изцяло покрити от VRM
    # системата; не дублираме тук. Business sentiment разчита на
    # US-native FRED серии: PHILLY_FED + CFNAI + CFNAIMA3.
    # ───────────────────────────────────────────────────────

    "UMCSENT": {
        "source": "fred",
        "id": "UMCSENT",
        "region": "US",
        "name_bg": "Michigan Sentiment Index",
        "name_en": "University of Michigan Consumer Sentiment",
        "lens": ["growth"],
        "peer_group": "consumer_sentiment",
        "tags": [],
        "transform": "level",
        "historical_start": "1978-01-01",
        "release_schedule": "monthly",
        "typical_release": "mid_and_end_of_month",
        "revision_prone": False,
        "narrative_hint": "Known за dramatic bottoms. Силно корелира с election cycles, gas prices и post-2024 показва политически bias (D vs R) — гледай breadth с Conference Board/OECD proxy, не individual прочит.",
    },
    # 2026-04-28: CONS_CONF_OECD (CSCICP03USM665S) премахнат — FRED има само
    # до 2024-01-01 (discontinued OECD series). UMCSENT покрива consumer
    # sentiment lens.

    # ───────────────────────────────────────────────────────
    # GROWTH / business_sentiment
    # ───────────────────────────────────────────────────────
    # Phase 2.5 (2026-04-17): BUS_CONF_OECD премахнат (too broad, OECD composite
    # не е U.S.-native). Заменен с PHILLY_FED + CFNAI + CFNAIMA3 — истинска
    # US-focused business health triangulation. ISM сигналът е покрит от VRM.
    # Phase 2.5 update (2026-04-18): NFIB Optimism Index премахнат — FRED не
    # хоства top-line композита като свободна серия (NFIBOPTISM не съществува;
    # само sub-questions са публични). Заменен с Philly Fed BOS General Activity
    # Diffusion Index — similar sentiment character, free, monthly, от 1968.

    "PHILLY_FED": {
        "source": "fred",
        "id": "GACDFSA066MSFRBPHI",
        "region": "US",
        "name_bg": "Philly Fed Business Outlook — текуща активност",
        "name_en": "Philadelphia Fed Manufacturing BOS: Current General Activity, Diffusion Index (SA)",
        "lens": ["growth"],
        "peer_group": "business_sentiment",
        "tags": [],
        "transform": "level",
        "historical_start": "1968-05-01",
        "release_schedule": "monthly",
        "typical_release": "third_thursday",
        "revision_prone": False,
        "narrative_hint": "Водещ manufacturing sentiment индикатор от 3-ти Fed district. Diffusion index: % отговарящи за ръст − % за спад. Zero е neutral; > 0 = expansion. Силен leading signal за ISM Manufacturing PMI и корпоративен capex cycle. Често media reference заедно с NY Fed Empire State.",
    },
    "CFNAIMA3": {
        "source": "fred",
        "id": "CFNAIMA3",
        "region": "US",
        "name_bg": "Chicago Fed National Activity Index (3-mo MA)",
        "name_en": "Chicago Fed National Activity Index, 3 Month MA",
        "lens": ["growth"],
        "peer_group": "business_sentiment",
        "tags": [],
        "transform": "level",
        "historical_start": "1967-05-01",
        "release_schedule": "monthly",
        "typical_release": "end_month",
        "revision_prone": True,
        "narrative_hint": "Smoothed CFNAI. Класическо recession trigger: CFNAIMA3 < -0.7 → recession probability spike.",
    },

    # ───────────────────────────────────────────────────────
    # GROWTH / consumer_sentiment (Phase 2.5)
    # ───────────────────────────────────────────────────────

    "PSAVERT": {
        "source": "fred",
        "id": "PSAVERT",
        "region": "US",
        "name_bg": "Personal Savings Rate",
        "name_en": "Personal Saving Rate",
        "lens": ["growth"],
        "peer_group": "consumer_sentiment",
        "tags": [],
        "transform": "level",
        "historical_start": "1959-01-01",
        "release_schedule": "monthly",
        "typical_release": "end_month",
        "revision_prone": True,
        "narrative_hint": "Hard data компонент. Скочи >30% в COVID — когато survey и hard data разминават, сигналът укрепва.",
    },

    # ═══════════════════════════════════════════════════════
    # INFLATION LENS (Phase 2 — 2026-04-17)
    # ═══════════════════════════════════════════════════════

    # ───────────────────────────────────────────────────────
    # INFLATION / headline_measures
    # ───────────────────────────────────────────────────────

    "CPIAUCSL": {
        "source": "fred",
        "id": "CPIAUCSL",
        "region": "US",
        "name_bg": "CPI — headline (всички стоки и услуги)",
        "name_en": "Consumer Price Index — All Items",
        "lens": ["inflation"],
        "peer_group": "headline_measures",
        "tags": [],
        "transform": "yoy_pct",
        "historical_start": "1947-01-01",
        "release_schedule": "monthly",
        "typical_release": "second_wednesday",
        "revision_prone": False,
        "narrative_hint": "Най-медийно коментирана inflation серия. Шумна от храни+енергия — използвай заедно с CPILFESL.",
    },
    "PCEPI": {
        "source": "fred",
        "id": "PCEPI",
        "region": "US",
        "name_bg": "PCE ценови индекс — headline (предпочитан от ФЕД)",
        "name_en": "Personal Consumption Expenditures Price Index",
        "lens": ["inflation"],
        "peer_group": "headline_measures",
        "tags": [],
        "transform": "yoy_pct",
        "historical_start": "1959-01-01",
        "release_schedule": "monthly",
        "typical_release": "last_friday",
        "revision_prone": True,
        "narrative_hint": "Fed target inflation. Различна методология от CPI (chain-weighted, по-широк услуги scope). Разликата CPI-PCE обикновено 0.3-0.5 pp.",
    },
    "PPIFIS": {
        "source": "fred",
        "id": "PPIFIS",
        "region": "US",
        "name_bg": "PPI — Final Demand (производствени цени)",
        "name_en": "Producer Price Index — Final Demand",
        "lens": ["inflation"],
        "peer_group": "headline_measures",
        "tags": ["non_consensus"],
        "transform": "yoy_pct",
        "historical_start": "2009-11-01",
        "release_schedule": "monthly",
        "typical_release": "day_10_to_15",
        "revision_prone": True,
        "narrative_hint": "Производствени цени → consumer prices с 1-3 месечен lag. Водещ за CPI при трендови промени.",
    },

    # ───────────────────────────────────────────────────────
    # INFLATION / core_measures
    # ───────────────────────────────────────────────────────

    "CPILFESL": {
        "source": "fred",
        "id": "CPILFESL",
        "region": "US",
        "name_bg": "Core CPI (без храни и енергия)",
        "name_en": "CPI — All Items Less Food and Energy",
        "lens": ["inflation"],
        "peer_group": "core_measures",
        "tags": [],
        "transform": "yoy_pct",
        "historical_start": "1957-01-01",
        "release_schedule": "monthly",
        "typical_release": "second_wednesday",
        "revision_prone": False,
        "narrative_hint": "Основният core signal. Fed внимателно гледа core CPI/PCE — headline е шум.",
    },
    "PCEPILFE": {
        "source": "fred",
        "id": "PCEPILFE",
        "region": "US",
        "name_bg": "Core PCE (основният Fed мандат)",
        "name_en": "Core PCE Price Index",
        "lens": ["inflation"],
        "peer_group": "core_measures",
        "tags": [],
        "transform": "yoy_pct",
        "historical_start": "1959-01-01",
        "release_schedule": "monthly",
        "typical_release": "last_friday",
        "revision_prone": True,
        "narrative_hint": "ТОВА е 2%-таргетът на ФЕД. Всички policy-решения се въртят около тази серия.",
    },
    "PPICORE": {
        "source": "fred",
        "id": "WPSFD4131",
        "region": "US",
        "name_bg": "PPI Core (Final Demand без храни и енергия)",
        "name_en": "PPI Final Demand Less Foods and Energy",
        "lens": ["inflation"],
        "peer_group": "core_measures",
        "tags": ["non_consensus"],
        "transform": "yoy_pct",
        "historical_start": "2009-11-01",
        "release_schedule": "monthly",
        "typical_release": "day_10_to_15",
        "revision_prone": True,
        "narrative_hint": "PPI core води CPI core с 1-3 месеца. Недостатъчно проследяван — силен индикатор при конвергенция или дивергенция с CPI core.",
    },

    # ───────────────────────────────────────────────────────
    # INFLATION / sticky_measures (persistence signals)
    # ───────────────────────────────────────────────────────

    "STICKY_CPI": {
        "source": "fred",
        "id": "CORESTICKM159SFRBATL",
        "region": "US",
        "name_bg": "Atlanta Fed Sticky CPI (без храни и енергия)",
        "name_en": "Atlanta Fed Sticky-Price CPI Less Food and Energy",
        "lens": ["inflation"],
        "peer_group": "sticky_measures",
        "tags": ["non_consensus"],
        "transform": "level",
        "historical_start": "1967-02-01",
        "release_schedule": "monthly",
        "typical_release": "after_cpi_release",
        "revision_prone": False,
        "narrative_hint": "Серии с rigid pricing (ренти, медицински услуги). Когато sticky CPI се вдигне, инфлацията има инертност. Ключов сигнал за Fed.",
    },
    "MEDIAN_CPI": {
        "source": "fred",
        "id": "MEDCPIM158SFRBCLE",
        "region": "US",
        "name_bg": "Median CPI (Cleveland Fed)",
        "name_en": "Cleveland Fed Median CPI",
        "lens": ["inflation"],
        "peer_group": "sticky_measures",
        "tags": ["non_consensus"],
        "transform": "level",
        "historical_start": "1967-01-01",
        "release_schedule": "monthly",
        "typical_release": "after_cpi_release",
        "revision_prone": False,
        "narrative_hint": "Медиана на component inflation rates. По-устойчива на outlier категории отколкото headline. Силен signal при noisy периоди.",
    },
    "TRIMMED_MEAN_CPI": {
        "source": "fred",
        "id": "TRMMEANCPIM158SFRBCLE",
        "region": "US",
        "name_bg": "Trimmed-Mean CPI (Cleveland Fed, 16%)",
        "name_en": "Cleveland Fed 16% Trimmed-Mean CPI",
        "lens": ["inflation"],
        "peer_group": "sticky_measures",
        "tags": [],
        "transform": "level",
        "historical_start": "1983-01-01",
        "release_schedule": "monthly",
        "typical_release": "after_cpi_release",
        "revision_prone": False,
        "narrative_hint": "Орязва 8% в опашките (топ и долу). По-стабилна от median при многоизмерен shock.",
    },

    # ───────────────────────────────────────────────────────
    # INFLATION / goods_services (2022-2024 story)
    # ───────────────────────────────────────────────────────

    "CPI_SERVICES": {
        "source": "fred",
        "id": "CUSR0000SAS",
        "region": "US",
        "name_bg": "CPI — услуги (всички)",
        "name_en": "CPI Services",
        "lens": ["inflation"],
        "peer_group": "goods_services",
        "tags": [],
        "transform": "yoy_pct",
        "historical_start": "1967-01-01",
        "release_schedule": "monthly",
        "typical_release": "second_wednesday",
        "revision_prone": False,
        "narrative_hint": "Услугите са 60%+ от CPI. По-инертни от goods. Post-COVID инфлацията мигрира от стоки към услуги.",
    },
    "CPI_GOODS": {
        "source": "fred",
        "id": "CUSR0000SAC",
        "region": "US",
        "name_bg": "CPI — стоки (commodities)",
        "name_en": "CPI Commodities (Goods)",
        "lens": ["inflation"],
        "peer_group": "goods_services",
        "tags": [],
        "transform": "yoy_pct",
        "historical_start": "1947-01-01",
        "release_schedule": "monthly",
        "typical_release": "second_wednesday",
        "revision_prone": False,
        "narrative_hint": "Goods inflation реагира бързо на supply shocks. 2022 peak след доставъчните кризи. Сега често е в deflation/близо до 0.",
    },
    "CPI_SHELTER": {
        "source": "fred",
        "id": "CUSR0000SAH1",
        "region": "US",
        "name_bg": "CPI — жилища (shelter)",
        "name_en": "CPI Shelter",
        "lens": ["inflation"],
        "peer_group": "goods_services",
        "tags": ["non_consensus"],
        "transform": "yoy_pct",
        "historical_start": "1953-01-01",
        "release_schedule": "monthly",
        "typical_release": "second_wednesday",
        "revision_prone": False,
        "narrative_hint": "Shelter е ~1/3 от CPI. OER методология lag-ва market rents с 12-18 месеца. При сривове на пазарни ренти shelter CPI упорито остава висок — дебатен signal.",
    },

    # ───────────────────────────────────────────────────────
    # INFLATION / expectations (forward-looking)
    # ───────────────────────────────────────────────────────

    "MICH_INFL_1Y": {
        "source": "fred",
        "id": "MICH",
        "region": "US",
        "name_bg": "Инфлационни очаквания (Michigan, 1 година)",
        "name_en": "University of Michigan 1-Year Inflation Expectations",
        "lens": ["inflation"],
        "peer_group": "expectations",
        "tags": [],
        "transform": "level",
        "historical_start": "1978-01-01",
        "release_schedule": "monthly",
        "typical_release": "second_and_fourth_friday",
        "revision_prone": False,
        "narrative_hint": "Household очаквания. По-шумни от market-based, но по-ранни. Extreme movements сигнализират de-anchoring risk.",
    },
    "BREAKEVEN_10Y": {
        "source": "fred",
        "id": "T10YIE",
        "region": "US",
        "name_bg": "10-годишни инфлационни очаквания (пазарни, TIPS)",
        "name_en": "10-Year Breakeven Inflation Rate",
        "lens": ["inflation"],
        "peer_group": "expectations",
        "tags": [],
        "transform": "level",
        "historical_start": "2003-01-02",
        "release_schedule": "weekly",
        "typical_release": "daily_aggregated",
        "revision_prone": False,
        "narrative_hint": "Market-based измерение = 10y Treasury yield - 10y TIPS yield. Daily-released; агрегираме седмично. Високо ликвидна метрика.",
    },
    "BREAKEVEN_5Y5Y": {
        "source": "fred",
        "id": "T5YIFR",
        "region": "US",
        "name_bg": "5y5y forward инфлационни очаквания",
        "name_en": "5-Year, 5-Year Forward Inflation Expectation Rate",
        "lens": ["inflation"],
        "peer_group": "expectations",
        "tags": ["non_consensus"],
        "transform": "level",
        "historical_start": "2003-01-02",
        "release_schedule": "weekly",
        "typical_release": "daily_aggregated",
        "revision_prone": False,
        "narrative_hint": "Forward expectation от година 5 до 10 — филтрира краткосрочен shock. ЦБ предпочитан метрик за de-anchoring surveillance.",
    },

    # ═══════════════════════════════════════════════════════
    # LIQUIDITY & CREDIT LENS (Phase 2 — 2026-04-17)
    # ═══════════════════════════════════════════════════════

    # ───────────────────────────────────────────────────────
    # LIQUIDITY / policy_rates
    # ───────────────────────────────────────────────────────

    "FED_FUNDS": {
        "source": "fred",
        "id": "DFF",
        "region": "US",
        "name_bg": "Федерален лихвен процент (effective)",
        "name_en": "Federal Funds Effective Rate",
        "lens": ["liquidity"],
        "peer_group": "policy_rates",
        "tags": [],
        "transform": "level",
        "historical_start": "1954-07-01",
        "release_schedule": "weekly",
        "typical_release": "daily_aggregated",
        "revision_prone": False,
        "narrative_hint": "Effective Fed funds — ежедневно публикуван. Policy stance. За hike/cut cycles следи посоката, не абсолюта.",
    },
    "SOFR": {
        "source": "fred",
        "id": "SOFR",
        "region": "US",
        "name_bg": "SOFR — овърнайт REPO ставка",
        "name_en": "Secured Overnight Financing Rate",
        "lens": ["liquidity"],
        "peer_group": "policy_rates",
        "tags": [],
        "transform": "level",
        "historical_start": "2018-04-03",
        "release_schedule": "weekly",
        "typical_release": "daily_aggregated",
        "revision_prone": False,
        "narrative_hint": "Пост-LIBOR benchmark. Spikes в SOFR спрямо Fed funds → liquidity stress в repo пазара (виж 2019 repo crisis).",
    },

    # ───────────────────────────────────────────────────────
    # LIQUIDITY / term_structure
    # ───────────────────────────────────────────────────────

    "UST_2Y": {
        "source": "fred",
        "id": "DGS2",
        "region": "US",
        "name_bg": "2-годишна US доходност",
        "name_en": "2-Year Treasury Constant Maturity",
        "lens": ["liquidity"],
        "peer_group": "term_structure",
        "tags": [],
        "transform": "level",
        "historical_start": "1976-06-01",
        "release_schedule": "weekly",
        "typical_release": "daily_aggregated",
        "revision_prone": False,
        "narrative_hint": "Доминирана от Fed policy expectations. Най-реактивна към policy surprise-и.",
    },
    "UST_10Y": {
        "source": "fred",
        "id": "DGS10",
        "region": "US",
        "name_bg": "10-годишна US доходност",
        "name_en": "10-Year Treasury Constant Maturity",
        "lens": ["liquidity"],
        "peer_group": "term_structure",
        "tags": [],
        "transform": "level",
        "historical_start": "1962-01-02",
        "release_schedule": "weekly",
        "typical_release": "daily_aggregated",
        "revision_prone": False,
        "narrative_hint": "Бенчмарк за растеж + инфлационни очаквания. 10Y - real yield (DFII10) ≈ breakeven.",
    },
    "YC_10Y2Y": {
        "source": "fred",
        "id": "T10Y2Y",
        "region": "US",
        "name_bg": "Yield curve: 10Y - 2Y спред",
        "name_en": "10-Year minus 2-Year Treasury Spread",
        "lens": ["liquidity"],
        "peer_group": "term_structure",
        "tags": ["non_consensus"],
        "transform": "level",
        "historical_start": "1976-06-01",
        "release_schedule": "weekly",
        "typical_release": "daily_aggregated",
        "revision_prone": False,
        "narrative_hint": "Класически recession predictor. Инверсия (< 0) предхожда рецесия с 6-24 месеца. 2022-2023 инверсия → 2024/25 recession debate.",
    },
    "YC_10Y3M": {
        "source": "fred",
        "id": "T10Y3M",
        "region": "US",
        "name_bg": "Yield curve: 10Y - 3M спред (Fed-preferred)",
        "name_en": "10-Year minus 3-Month Treasury Spread",
        "lens": ["liquidity"],
        "peer_group": "term_structure",
        "tags": ["non_consensus"],
        "transform": "level",
        "historical_start": "1982-01-04",
        "release_schedule": "weekly",
        "typical_release": "daily_aggregated",
        "revision_prone": False,
        "narrative_hint": "Fed-preferred recession indicator (NY Fed модел). 3M reflecstва текущата policy; по-точен сигнал от 10Y-2Y според Estrella/Mishkin.",
    },

    # ───────────────────────────────────────────────────────
    # LIQUIDITY / credit_spreads
    # ───────────────────────────────────────────────────────

    "HY_OAS": {
        "source": "fred",
        "id": "BAMLH0A0HYM2",
        "region": "US",
        "name_bg": "High Yield спред (HY OAS)",
        "name_en": "ICE BofA US High Yield Index OAS",
        "lens": ["liquidity"],
        "peer_group": "credit_spreads",
        "tags": ["non_consensus"],
        "transform": "level",
        "historical_start": "1996-12-31",
        "release_schedule": "weekly",
        "typical_release": "daily_aggregated",
        "revision_prone": False,
        "narrative_hint": "Risk premium на junk bonds. Spikes предхождат equity volatility и рецесионен стрес. < 300 bps = risk-on; > 800 bps = distress.",
    },
    "IG_OAS": {
        "source": "fred",
        "id": "BAMLC0A0CM",
        "region": "US",
        "name_bg": "Investment Grade спред (IG OAS)",
        "name_en": "ICE BofA US Corporate Index OAS",
        "lens": ["liquidity"],
        "peer_group": "credit_spreads",
        "tags": [],
        "transform": "level",
        "historical_start": "1996-12-31",
        "release_schedule": "weekly",
        "typical_release": "daily_aggregated",
        "revision_prone": False,
        "narrative_hint": "IG credit stress — по-бавна реакция от HY, но по-близо до real economy funding costs.",
    },

    # ───────────────────────────────────────────────────────
    # LIQUIDITY / financial_conditions (aggregate indices)
    # ───────────────────────────────────────────────────────

    "NFCI": {
        "source": "fred",
        "id": "NFCI",
        "region": "US",
        "name_bg": "NFCI — Chicago Fed финансови условия",
        "name_en": "Chicago Fed National Financial Conditions Index",
        "lens": ["liquidity"],
        "peer_group": "financial_conditions",
        "tags": [],
        "transform": "level",
        "historical_start": "1971-01-08",
        "release_schedule": "weekly",
        "typical_release": "wednesday",
        "revision_prone": False,
        "narrative_hint": "Централизиран измерител на risk, credit и leverage. Zero-mean standardized (> 0 = tight; < 0 = loose).",
    },
    "STLFSI": {
        "source": "fred",
        "id": "STLFSI4",
        "region": "US",
        "name_bg": "St. Louis Financial Stress Index",
        "name_en": "St. Louis Fed Financial Stress Index (v4)",
        "lens": ["liquidity"],
        "peer_group": "financial_conditions",
        "tags": [],
        "transform": "level",
        "historical_start": "1993-12-31",
        "release_schedule": "weekly",
        "typical_release": "thursday",
        "revision_prone": False,
        "narrative_hint": "Complementary към NFCI. Засилена тежест на rates и credit. Използвай като втори мнение — divergence между двете е сигнал.",
    },

    # ───────────────────────────────────────────────────────
    # LIQUIDITY / money_supply
    # ───────────────────────────────────────────────────────

    "M2": {
        "source": "fred",
        "id": "M2SL",
        "region": "US",
        "name_bg": "M2 паричен агрегат",
        "name_en": "M2 Money Stock (Seasonally Adjusted)",
        "lens": ["liquidity"],
        "peer_group": "money_supply",
        "tags": [],
        "transform": "yoy_pct",
        "historical_start": "1959-01-01",
        "release_schedule": "monthly",
        "typical_release": "fourth_tuesday",
        "revision_prone": True,
        "narrative_hint": "M2 YoY → исторически корелира със inflation с 12-24 месечен lag. Но velocity-то варира; не е automatic signal.",
    },
    "FED_BS": {
        "source": "fred",
        "id": "WALCL",
        "region": "US",
        "name_bg": "ФЕД баланс — общи активи",
        "name_en": "Federal Reserve Total Assets",
        "lens": ["liquidity"],
        "peer_group": "money_supply",
        "tags": [],
        "transform": "yoy_pct",
        "historical_start": "2002-12-18",
        "release_schedule": "weekly",
        "typical_release": "thursday",
        "revision_prone": False,
        "narrative_hint": "QE/QT monitor. Промяна в баланса → директен liquidity impact. Реагира преди rate changes.",
    },
    "TOTAL_RESERVES": {
        "source": "fred",
        "id": "TOTRESNS",
        "region": "US",
        "name_bg": "Общи банкови резерви във ФЕД",
        "name_en": "Total Reserves of Depository Institutions",
        "lens": ["liquidity"],
        "peer_group": "money_supply",
        "tags": [],
        "transform": "yoy_pct",
        "historical_start": "1959-01-01",
        "release_schedule": "monthly",
        "typical_release": "end_of_month",
        "revision_prone": False,
        "narrative_hint": "Банковата ликвидност директно. При QT рязко пада — 2019 repo stress се случи когато резервите паднаха < $1.5T.",
    },

    # ───────────────────────────────────────────────────────
    # LIQUIDITY / banking_credit
    # ───────────────────────────────────────────────────────

    "C_AND_I_LOANS": {
        "source": "fred",
        "id": "BUSLOANS",
        "region": "US",
        "name_bg": "Търговски и индустриални кредити (C&I)",
        "name_en": "Commercial and Industrial Loans",
        "lens": ["liquidity", "growth"],
        "peer_group": "banking_credit",
        "tags": ["non_consensus"],
        "transform": "yoy_pct",
        "historical_start": "1947-01-01",
        "release_schedule": "weekly",
        "typical_release": "friday",
        "revision_prone": True,
        "narrative_hint": "Бизнес заемане от банки. Water сигнал за capex intentions + credit supply. YoY crash често предхожда рецесия.",
    },
    "CC_DELINQUENCY": {
        "source": "fred",
        "id": "DRCCLACBS",
        "region": "US",
        "name_bg": "Просрочия по кредитни карти",
        "name_en": "Delinquency Rate on Credit Card Loans",
        "lens": ["liquidity"],
        "peer_group": "banking_credit",
        "tags": ["non_consensus"],
        "transform": "level",
        "historical_start": "1991-01-01",
        "release_schedule": "quarterly",
        "typical_release": "after_quarter_end_45_days",
        "revision_prone": False,
        "narrative_hint": "Consumer credit stress. Вдигането предхожда labor market weakness. След 2022 ускорена тенденция нагоре.",
    },
}


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def get_series(key: str) -> dict[str, Any]:
    """Връща конкретна серия по ключ. Хвърля KeyError ако липсва."""
    if key not in SERIES_CATALOG:
        raise KeyError(f"Серия '{key}' не съществува в catalog.")
    return SERIES_CATALOG[key]


def series_by_lens(lens: str) -> list[dict[str, Any]]:
    """Всички серии, принадлежащи към дадена леща (вкл. multi-lens)."""
    return [
        {**meta, "_key": k}
        for k, meta in SERIES_CATALOG.items()
        if lens in meta.get("lens", [])
    ]


def series_by_peer_group(group: str) -> list[dict[str, Any]]:
    """Всички серии в конкретна peer group."""
    return [
        {**meta, "_key": k}
        for k, meta in SERIES_CATALOG.items()
        if meta.get("peer_group") == group
    ]


def series_by_tag(tag: str) -> list[dict[str, Any]]:
    """Всички серии със специфичен tag (напр. 'non_consensus')."""
    return [
        {**meta, "_key": k}
        for k, meta in SERIES_CATALOG.items()
        if tag in meta.get("tags", [])
    ]


def all_series_ids() -> list[str]:
    """Всички каталожни ключове."""
    return list(SERIES_CATALOG.keys())


def series_by_source(source: str) -> list[dict[str, Any]]:
    """Всички серии от конкретен източник ('fred', 'eurostat', 'pending')."""
    return [
        {**meta, "_key": k}
        for k, meta in SERIES_CATALOG.items()
        if meta.get("source") == source
    ]


# ============================================================
# VALIDATION
# ============================================================

def validate_catalog() -> list[str]:
    """Проверява, че всички записи имат задължителните полета с валидни стойности.

    Returns:
        list of error messages (празен = всичко е наред).
    """
    required_fields = {
        "source", "id", "region", "name_bg", "name_en",
        "lens", "peer_group", "tags", "transform",
        "historical_start", "release_schedule", "typical_release",
        "revision_prone", "narrative_hint",
    }

    errors: list[str] = []

    for key, meta in SERIES_CATALOG.items():
        missing = required_fields - set(meta.keys())
        if missing:
            errors.append(f"{key}: липсват полета {missing}")
            continue

        if meta["source"] not in ALLOWED_SOURCES:
            errors.append(f"{key}: невалиден source '{meta['source']}'")
        if meta["region"] not in ALLOWED_REGIONS:
            errors.append(f"{key}: невалиден region '{meta['region']}'")
        if meta["transform"] not in ALLOWED_TRANSFORMS:
            errors.append(f"{key}: невалиден transform '{meta['transform']}'")
        if meta["release_schedule"] not in ALLOWED_SCHEDULES:
            errors.append(f"{key}: невалиден release_schedule '{meta['release_schedule']}'")
        for lens in meta["lens"]:
            if lens not in ALLOWED_LENSES:
                errors.append(f"{key}: невалидна lens '{lens}'")
        for tag in meta["tags"]:
            if tag not in ALLOWED_TAGS:
                errors.append(f"{key}: невалиден tag '{tag}'")
        if not isinstance(meta["revision_prone"], bool):
            errors.append(f"{key}: revision_prone трябва да е bool")

    return errors


# ============================================================
# MODULE LOAD-TIME VALIDATION
# ============================================================

_validation_errors = validate_catalog()
if _validation_errors:
    import warnings
    warnings.warn(
        "Catalog validation failed:\n  " + "\n  ".join(_validation_errors),
        UserWarning,
        stacklevel=2,
    )
