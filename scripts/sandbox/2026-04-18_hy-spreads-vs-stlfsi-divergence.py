"""
sandbox/2026-04-18_hy-spreads-vs-stlfsi-divergence.py
=====================================================
Ad hoc анализ — HY spreads vs STLFSI divergence

Създаден: 2026-04-18
Свързан journal запис: (попълни ръчно след save_journal_entry)

Това е worked example за Q&A workflow-а. Показва пълния цикъл:
въпрос → данни → анализ → форматиран извод → опционален journal запис.
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent  # econ_v2/
sys.path.insert(0, str(BASE))

import pandas as pd
import numpy as np

from scripts._utils import (
    load_briefing_snapshot,
    save_journal_entry,
)


# ============================================================
# 1. ВЪПРОС
# ============================================================

QUESTION = """
HY OAS (junk bond spreads) е по дефиниция по-волатилен от STLFSI (broad
financial stress index, включва VIX и rate spreads). В нормален режим двете
се движат заедно — стрес в кредита идва с общо финансово затягане.

Дивергенция в две посоки е интересна:
  (а) HY се разширява, а STLFSI е спокоен — credit market е напред на
      кривата; или HY реагира на микро (energy defaults, CCC tier), не на
      макро.
  (б) STLFSI се движи нагоре, а HY е стабилен — broad stress без credit
      confirmation; обикновено се решава с единия се присъедини към другия.

Въпросът: има ли в момента подобна дивергенция и ако да — в коя посока?
"""


# ============================================================
# 2. ДАННИ
# ============================================================

def load_data() -> dict:
    """Зарежда HY_OAS и STLFSI от briefing snapshot."""
    snap = load_briefing_snapshot()
    missing = [k for k in ("HY_OAS", "STLFSI") if k not in snap]
    if missing:
        raise RuntimeError(
            f"Липсват серии в snapshot-а: {missing}. "
            "Пусни `python run.py --briefing` за рефреш на cache-а."
        )
    hy = snap["HY_OAS"].dropna()
    stlfsi = snap["STLFSI"].dropna()

    # Align на общ индекс (inner join по дати)
    df = pd.concat({"HY_OAS": hy, "STLFSI": stlfsi}, axis=1).dropna()
    return {"df": df, "hy_last": hy.iloc[-1], "stlfsi_last": stlfsi.iloc[-1]}


# ============================================================
# 3. АНАЛИЗ
# ============================================================

def z_score(s: pd.Series, window: int | None = None) -> pd.Series:
    """Z-score. Ако window е зададен — rolling, иначе спрямо целия период."""
    if window is None:
        return (s - s.mean()) / s.std(ddof=0)
    return (s - s.rolling(window).mean()) / s.rolling(window).std(ddof=0)


def analyze(data: dict) -> dict:
    df = data["df"]

    # Z-scores спрямо пълната история (от 1996 за HY, от 1993 за STLFSI)
    hy_z = z_score(df["HY_OAS"])
    stlfsi_z = z_score(df["STLFSI"])

    hy_z_now = float(hy_z.iloc[-1])
    stlfsi_z_now = float(stlfsi_z.iloc[-1])
    gap = hy_z_now - stlfsi_z_now  # >0 → HY над STLFSI; <0 → обратно

    # Историческо разпределение на gap-а — за да кажем колко е необичайно
    gap_series = hy_z - stlfsi_z
    gap_pct = float((gap_series <= gap).mean() * 100)

    # Промяна за последните 60 търговски дни (~3 месеца)
    lookback = min(60, len(df) - 1)
    hy_chg = float(df["HY_OAS"].iloc[-1] - df["HY_OAS"].iloc[-1 - lookback])
    stlfsi_chg = float(df["STLFSI"].iloc[-1] - df["STLFSI"].iloc[-1 - lookback])

    # Rolling 252-дневна корелация — дали отношението е стабилно
    corr_1y = df["HY_OAS"].rolling(252).corr(df["STLFSI"]).iloc[-1]

    return {
        "hy_last": data["hy_last"],
        "stlfsi_last": data["stlfsi_last"],
        "hy_z": hy_z_now,
        "stlfsi_z": stlfsi_z_now,
        "gap_z": gap,
        "gap_percentile": gap_pct,
        "hy_chg_60d": hy_chg,
        "stlfsi_chg_60d": stlfsi_chg,
        "corr_1y": float(corr_1y) if pd.notna(corr_1y) else None,
        "as_of": df.index[-1].date(),
    }


# ============================================================
# 4. ИЗВОД
# ============================================================

def _direction(gap_z: float, gap_pct: float) -> str:
    """Четим етикет за текущото състояние на дивергенцията."""
    if abs(gap_z) < 0.5:
        return "Без значима дивергенция — HY и STLFSI в синхрон."
    if gap_z > 0:
        return (
            f"HY над STLFSI ({gap_pct:.0f}-ти percentile на gap-а): "
            "credit market сигнализира стрес преди broad conditions."
        )
    return (
        f"STLFSI над HY ({gap_pct:.0f}-ти percentile на gap-а): "
        "broad financial conditions се затягат без credit confirmation."
    )


def format_finding(result: dict) -> str:
    verdict = _direction(result["gap_z"], result["gap_percentile"])

    corr_line = (
        f"- Rolling 252d корелация: **{result['corr_1y']:.2f}**"
        if result["corr_1y"] is not None
        else "- Rolling 252d корелация: недостатъчно данни"
    )

    return f"""## Въпрос

{QUESTION.strip()}

## Данни

Към {result['as_of']}:
- HY OAS: **{result['hy_last']:.0f} bps** (z = {result['hy_z']:+.2f})
- STLFSI: **{result['stlfsi_last']:.2f}** (z = {result['stlfsi_z']:+.2f})

Промяна за последните ~60 търговски дни:
- HY OAS: {result['hy_chg_60d']:+.0f} bps
- STLFSI: {result['stlfsi_chg_60d']:+.2f}

## Анализ

- Gap (HY z − STLFSI z): **{result['gap_z']:+.2f}**
- Исторически percentile на gap-а: **{result['gap_percentile']:.0f}-ти** (1993–днес)
{corr_line}

## Извод

{verdict}

**За проследяване:** ако дивергенцията се задълбочи (gap z > 1.5 или < −1.5),
обикновено едната серия се присъединява към другата в рамките на 4–8 седмици.
Исторически примери за credit-first divergence: Q3 2007 (HY напред),
Q4 2015 (energy defaults), Q1 2020 (COVID week 1).
"""


def main() -> None:
    data = load_data()
    result = analyze(data)
    finding = format_finding(result)
    print(finding)

    # Ако дивергенцията е значима (|gap_z| >= 1.0) — това струва journal entry.
    # Ако не е — оставяме sandbox-а като scratch, не замърсяваме journal-а.
    #
    # Разкомeнтирай ръчно когато решиш да запишеш:
    #
    # if abs(result["gap_z"]) >= 1.0:
    #     save_journal_entry(
    #         topic="credit",
    #         title="HY vs STLFSI дивергенция",
    #         body=finding,
    #         tags=["hy_oas", "stlfsi", "divergence"],
    #         status="open_question",
    #         related_scripts=[Path(__file__).name],
    #     )


if __name__ == "__main__":
    main()
