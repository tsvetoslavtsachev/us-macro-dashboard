"""
catalog/polarity.py
===================
Полярностни решения за lens health scoring — ЕДИНЕН източник на истина (US).

Виж ../macro-satellite/LENS_SCORING_METHODOLOGY.md §3. Всеки знак тук е
ИЗРИЧНО ОБСЪДЕНО решение (Цветослав, 2026-06-04), не тих избор.

Типове:
  +1            → нагоре = по-здраво (заетост, активност, sentiment, заеми, темп на пари)
  -1            → нагоре = по-зле (безработица, молби, спредове, стрес, стягане)
  ("U","self")  → U около собствената 10-г. норма (отклонение в двете посоки = по-зле)
  ("U","target",X) → U около фиксирана цел X (инфлация: ~2%)

Multi-lens серии със различен смисъл по леща → override чрез (lens, key).
"""
from __future__ import annotations

from typing import Any

INFLATION_TARGET = 2.0  # % — Fed dual-mandate цел; U-център за инфлационните мерки

# ── Базова полярност (per серия) ─────────────────────────────────────────────
POLARITY: dict[str, Any] = {
    # LABOR / unemployment
    "UNRATE": -1, "U6RATE": -1, "UEMPMEAN": -1, "EMRATIO": +1, "CIVPART": +1,
    # LABOR / sectoral_employment
    "PAYEMS": +1, "USPRIV": +1, "MANEMP": +1, "USCONS": +1,
    "TRUCK_EMP": +1, "TEMPHELPS": +1, "USINFO": +1,
    # LABOR / ai_exposure
    "COMP_DESIGN": +1, "PROF_TECH_SERV": +1, "SOFT_PUB": +1,
    # LABOR / claims
    "ICSA": -1, "IC4WSA": -1, "CCSA": -1,
    # LABOR / flow
    "JTSJOL": +1, "JTSQUR": +1, "JTSLDL": -1,
    # LABOR / wage_dynamics (labor-смисъл: по-високи заплати = по-силен труд)
    "AHE": +1, "ECIWAG": +1,
    # LABOR / hours
    "AWHAETP": +1, "AWHMAN": +1, "AWOTMAN": +1,
    # LABOR / labor_share (структурно, ниско тегло)
    "COMP_GDP_SHARE": +1, "LABOR_SHARE_NBS": +1,

    # GROWTH / hard_activity
    "GDPC1": +1, "INDPRO": +1, "RSXFS": +1, "PCEC96": +1, "DGORDER": +1,
    # GROWTH / business_sentiment
    "CFNAI": +1, "PHILLY_FED": +1, "CFNAIMA3": +1,
    # GROWTH / consumer_sentiment
    "UMCSENT": +1, "CB_CCI": +1,
    "PSAVERT": ("U", "self"),   # U: твърде ниско (липса на доход) И твърде високо (свиване) = зле
    # GROWTH / diffusion + leading
    "ISM_MFG_PMI": +1, "ISM_SVCS_PMI": +1,
    "US_PMI_COMPOSITE": +1, "US_PMI_MFG": +1, "US_PMI_SVCS": +1, "CB_LEI": +1,
    # GROWTH+HOUSING / housing_supply
    "PERMIT": +1, "HOUST": +1, "COMPUTSA": +1, "TLRESCONS": +1,
    # GROWTH+LIQUIDITY / banking_credit
    "C_AND_I_LOANS": +1,

    # INFLATION (U около целта ~2%)
    "CPIAUCSL": ("U", "target", INFLATION_TARGET),
    "PCEPI": ("U", "target", INFLATION_TARGET),
    "PPIFIS": ("U", "target", INFLATION_TARGET),
    "CPILFESL": ("U", "target", INFLATION_TARGET),
    "PCEPILFE": ("U", "target", INFLATION_TARGET),
    "PPICORE": ("U", "target", INFLATION_TARGET),
    "STICKY_CPI": ("U", "target", INFLATION_TARGET),
    "MEDIAN_CPI": ("U", "target", INFLATION_TARGET),
    "TRIMMED_MEAN_CPI": ("U", "target", INFLATION_TARGET),
    "CPI_SERVICES": ("U", "target", INFLATION_TARGET),
    "CPI_GOODS": ("U", "target", INFLATION_TARGET),
    "CPI_SHELTER": ("U", "target", INFLATION_TARGET),
    "MICH_INFL_1Y": ("U", "target", INFLATION_TARGET),
    "BREAKEVEN_10Y": ("U", "target", INFLATION_TARGET),
    "BREAKEVEN_5Y5Y": ("U", "target", INFLATION_TARGET),

    # LIQUIDITY / policy_rates + term_structure
    "FED_FUNDS": -1, "SOFR": -1, "UST_2Y": -1, "UST_10Y": -1,
    # SOFR OIS (имплицирана Fed пътека) — по-висока ставка = стягане = по-зле, като FED_FUNDS/SOFR/UST
    "US_SOFR_OIS_3M": -1, "US_SOFR_OIS_6M": -1, "US_SOFR_OIS_1Y": -1, "US_SOFR_OIS_2Y": -1,
    "YC_10Y2Y": +1, "YC_10Y3M": +1,   # по-стръмна крива = по-здраво
    # LIQUIDITY / credit_spreads + financial_conditions
    "HY_OAS": -1, "IG_OAS": -1, "NFCI": -1, "STLFSI": -1,
    # LIQUIDITY / money_supply (темп; намалено тегло — виж PEER_GROUP_WEIGHT)
    "M2": +1, "FED_BS": +1, "TOTAL_RESERVES": +1,
    # LIQUIDITY / banking_credit
    "CC_DELINQUENCY": -1,

    # ── HOUSING ───────────────────────────────────────────────────────────────
    # Следва типовете от §3. Знаците ПОТВЪРДЕНИ от Цветослав 2026-06-05. Преди това
    # непосочените housing серии default-ваха +1 → ипотечни лихви/месеци предлагане
    # се четяха като „по-високо=по-здраво" (грешно). Тук са изрично заковани.
    # HOUSING / housing_prices (ръст на цените = по-силен пазар)
    "CSUSHPISA": +1, "SPCS20RSA": +1, "USSTHPI": +1, "HPIPONM226S": +1,
    "ZHVI_US_SFR_CONDO": +1,
    # HOUSING / housing_sales (повече сделки/договори = по-здраво)
    "HSN1F": +1, "EXHOSLUSM495S": +1, "NAR_PHSI": +1,
    # Inventory (yoy темп): U около собствената норма — и свръхбързо натрупване
    # (охлаждане/свръхпредлагане), и свръхбърз спад (недостиг) = по-нездраво.
    # Решение Цветослав 2026-06-05 (преди това default +1).
    "HOSINVUSM495N": ("U", "self"),
    # HOUSING / housing_financing
    "MORTGAGE30US": -1, "MORTGAGE15US": -1,   # по-висока ипотечна лихва = по-зле
    "MBA_PURCHASE_IDX": +1, "MBA_REFINANCE_IDX": +1,
    # HOUSING / housing_affordability
    "MSACSR": -1,        # повече месеци предлагане = свръхпредлагане/охлаждане
    "FIXHAI": +1,        # по-достъпно жилище = по-здраво
    "NAHB_HMI": +1,      # builder optimism > 50 = positive
}

# ── Per-(lens, key) overrides — multi-lens серии с различен смисъл ────────────
# Заплати/labor_share влизат и в inflation лещата като инфлационен натиск →
# там са U около собствена норма (runaway ИЛИ срив = нездраво за ценова стабилност).
POLARITY_BY_LENS: dict[tuple[str, str], Any] = {
    ("inflation", "AHE"): ("U", "self"),
    ("inflation", "ECIWAG"): ("U", "self"),
    ("inflation", "COMP_GDP_SHARE"): ("U", "self"),
    ("inflation", "LABOR_SHARE_NBS"): ("U", "self"),
}

# ── Тегла на peer-групи в lens агрегацията (default 1.0) ─────────────────────
PEER_GROUP_WEIGHT: dict[str, float] = {
    "money_supply": 0.5,   # M2/баланс на ЦБ — слаб сигнал (решение Цветослав)
    "labor_share": 0.5,    # структурно/бавно
}

# U-формата: толерантна лента (в σ) преди здравето да падне до неутрално.
U_BAND = 1.0


def polarity_for(key: str, lens: str | None = None) -> Any:
    """Полярност за серия (по избор в контекста на конкретна леща).

    Връща +1 / -1 / ("U","self") / ("U","target",X). Default +1 за непознати
    (консервативно: третира като "нагоре=здраво"), но всички каталожни серии
    в 4-те US лещи са изброени по-горе.
    """
    if lens is not None and (lens, key) in POLARITY_BY_LENS:
        return POLARITY_BY_LENS[(lens, key)]
    return POLARITY.get(key, +1)


def peer_group_weight(pg: str) -> float:
    return PEER_GROUP_WEIGHT.get(pg, 1.0)
