"""
analysis/executive.py
=====================
Executive Summary + Regime synthesis.

Агрегира cross-lens + breadth + anomaly + non-consensus в:
  1. Regime label — кратка икономическа диагноза (8 възможни режима)
  2. Lens таблица — 4 реда × {direction, breadth%, anomaly count, NEW-5Y count}
  3. Supporting signals — 3-5 tight bullet facts
  4. Narrative — template-based 2-4 изречения (без LLM)

Философия:
  - Primary regime driver е stagflation_test (labor tightness × inflation pressure),
    защото тази двойка има най-много policy-relevant state-ове.
  - Credit stress override: ако кредитни spread-ове се разширяват въпреки easing,
    това е non-policy сигнал, който прескача стандартната regime логика.
  - Без magic — ясни if/elif правила върху вече класифицираните cross-lens states.

Dependencies:
  - analysis.breadth.LensBreadthReport
  - analysis.divergence.CrossLensDivergenceReport
  - analysis.anomaly.AnomalyReport
  - analysis.non_consensus.NonConsensusReport
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np


# ============================================================
# REGIME TAXONOMY
# ============================================================

REGIME_LABELS = (
    "stagflation_confirmed",     # labor tight + inflation hot
    "soft_landing",              # labor tight + inflation cools
    "disinflation_cooling",      # labor loose + inflation cools
    "policy_dilemma",            # labor loose + inflation hot
    "expansion",                 # growth + labor aligned up, inflation non-diagnostic
    "slowdown",                  # growth + labor aligned down
    "credit_stress",             # credit widens despite easing (override)
    "transition",                # nothing aligned
)

REGIME_LABELS_BG = {
    "stagflation_confirmed": "Стагфлация (потвърдена)",
    "soft_landing": "Soft landing",
    "disinflation_cooling": "Дезинфлация и охлаждане",
    "policy_dilemma": "Policy dilemma",
    "expansion": "Разширяване",
    "slowdown": "Синхронно забавяне",
    "credit_stress": "Кредитен стрес",
    "transition": "Преходно / смесено",
}

REGIME_CSS_CLASS = {
    "stagflation_confirmed": "regime-stag",
    "soft_landing": "regime-soft",
    "disinflation_cooling": "regime-cool",
    "policy_dilemma": "regime-dilem",
    "expansion": "regime-exp",
    "slowdown": "regime-slow",
    "credit_stress": "regime-stress",
    "transition": "regime-trans",
}

LENS_ORDER = ("labor", "growth", "inflation", "liquidity")
LENS_LABEL_BG = {
    "labor": "Labor",
    "growth": "Growth",
    "inflation": "Inflation",
    "liquidity": "Liquidity",
}


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class LensRegimeRow:
    lens: str
    direction: str                # "expanding" | "contracting" | "mixed" | "insufficient_data"
    breadth_agg: float            # mean breadth_positive across peer_groups (excluding NaN)
    n_peer_groups: int            # брой peer_groups с валиден breadth
    anomaly_count: int
    new_extreme_count: int

    def to_dict(self) -> dict:
        d = asdict(self)
        if isinstance(d["breadth_agg"], float) and np.isnan(d["breadth_agg"]):
            d["breadth_agg"] = None
        return d


@dataclass
class RegimeSnapshot:
    as_of: Optional[str]
    regime_label: str                       # key in REGIME_LABELS
    regime_label_bg: str
    regime_css_class: str
    primary_driver: str                     # pair_id или "none"
    narrative_bg: str                       # 2-4 изречения
    lens_rows: list[LensRegimeRow] = field(default_factory=list)
    supporting_signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "regime_label": self.regime_label,
            "regime_label_bg": self.regime_label_bg,
            "regime_css_class": self.regime_css_class,
            "primary_driver": self.primary_driver,
            "narrative_bg": self.narrative_bg,
            "lens_rows": [r.to_dict() for r in self.lens_rows],
            "supporting_signals": list(self.supporting_signals),
        }


# ============================================================
# PUBLIC API
# ============================================================

def compute_executive_summary(
    cross_report,
    lens_reports: dict,
    anomaly_report,
    nc_report,
) -> RegimeSnapshot:
    """Синтезира regime snapshot от всички analysis reports.

    Args:
        cross_report: CrossLensDivergenceReport (analysis.divergence).
        lens_reports: {lens_name → LensBreadthReport} за labor/growth/inflation/liquidity.
        anomaly_report: AnomalyReport (analysis.anomaly).
        nc_report: NonConsensusReport (analysis.non_consensus).

    Returns:
        RegimeSnapshot с класификиран режим, lens таблица и нарация.
    """
    states = {p.pair_id: p.state for p in cross_report.pairs}

    regime_key, driver = _classify_regime(states)

    lens_rows = _build_lens_rows(lens_reports, anomaly_report)

    supporting_signals = _extract_supporting_signals(
        anomaly_report, nc_report, cross_report,
    )

    narrative = _build_narrative(
        regime_key, lens_rows, cross_report, anomaly_report, nc_report,
    )

    # Предпочитаме cross_report.as_of; fallback към anomaly_report
    as_of = cross_report.as_of or anomaly_report.as_of

    return RegimeSnapshot(
        as_of=as_of,
        regime_label=regime_key,
        regime_label_bg=REGIME_LABELS_BG[regime_key],
        regime_css_class=REGIME_CSS_CLASS[regime_key],
        primary_driver=driver,
        narrative_bg=narrative,
        lens_rows=lens_rows,
        supporting_signals=supporting_signals,
    )


# ============================================================
# INTERNAL — CLASSIFICATION
# ============================================================

def _classify_regime(states: dict[str, str]) -> tuple[str, str]:
    """Връща (regime_label, primary_driver_pair_id).

    Логика:
      1. stagflation_test е primary — четирите му state-а директно mapp-ват в режим.
      2. Ако stag е transition/insufficient:
         - credit stress (credit_policy_transmission = a_up_b_down) override-ва.
         - growth_labor_lead_lag е secondary — мапва към expansion/slowdown.
      3. Default: transition.
    """
    stag = states.get("stagflation_test")
    growth_labor = states.get("growth_labor_lead_lag")
    credit = states.get("credit_policy_transmission")

    # Primary path — stagflation_test е диагностика
    if stag == "both_up":
        return "stagflation_confirmed", "stagflation_test"
    if stag == "a_up_b_down":
        return "soft_landing", "stagflation_test"
    if stag == "both_down":
        return "disinflation_cooling", "stagflation_test"
    if stag == "a_down_b_up":
        return "policy_dilemma", "stagflation_test"

    # Fallback 1 — credit stress е по-силен сигнал от transition
    if credit == "a_up_b_down":
        return "credit_stress", "credit_policy_transmission"

    # Fallback 2 — growth × labor alignment
    if growth_labor == "both_up":
        return "expansion", "growth_labor_lead_lag"
    if growth_labor == "both_down":
        return "slowdown", "growth_labor_lead_lag"

    return "transition", "none"


# ============================================================
# INTERNAL — LENS ROWS
# ============================================================

def _build_lens_rows(lens_reports: dict, anomaly_report) -> list[LensRegimeRow]:
    """Изгражда по един ред на всяка леща."""
    rows: list[LensRegimeRow] = []
    for lens in LENS_ORDER:
        report = lens_reports.get(lens)
        if report is None:
            rows.append(LensRegimeRow(
                lens=lens,
                direction="insufficient_data",
                breadth_agg=float("nan"),
                n_peer_groups=0,
                anomaly_count=0,
                new_extreme_count=0,
            ))
            continue

        # Directions от всички peer_groups с валиден breadth
        peer_dirs = [
            pg.direction for pg in report.peer_groups
            if pg.direction != "insufficient_data"
        ]
        agg_dir = _aggregate_direction(peer_dirs)

        # Aggregate breadth — mean exclude NaN
        bps = [
            pg.breadth_positive for pg in report.peer_groups
            if isinstance(pg.breadth_positive, (int, float))
            and not (isinstance(pg.breadth_positive, float) and np.isnan(pg.breadth_positive))
        ]
        breadth_agg = float(np.mean(bps)) if bps else float("nan")

        # Anomalies в тази леща
        lens_anoms = anomaly_report.by_lens.get(lens, [])
        anom_count = len(lens_anoms)
        ne_count = sum(1 for a in lens_anoms if a.is_new_extreme)

        rows.append(LensRegimeRow(
            lens=lens,
            direction=agg_dir,
            breadth_agg=round(breadth_agg, 3) if not np.isnan(breadth_agg) else float("nan"),
            n_peer_groups=len(bps),
            anomaly_count=anom_count,
            new_extreme_count=ne_count,
        ))
    return rows


def _aggregate_direction(peer_directions: list[str]) -> str:
    """Majority rule: >50% expanding → expanding, >50% contracting → contracting, иначе mixed."""
    if not peer_directions:
        return "insufficient_data"
    total = len(peer_directions)
    expanding = sum(1 for d in peer_directions if d == "expanding")
    contracting = sum(1 for d in peer_directions if d == "contracting")
    if expanding / total > 0.5:
        return "expanding"
    if contracting / total > 0.5:
        return "contracting"
    return "mixed"


# ============================================================
# INTERNAL — SUPPORTING SIGNALS
# ============================================================

def _extract_supporting_signals(
    anomaly_report,
    nc_report,
    cross_report,
) -> list[str]:
    """Tight bullet list — най-силните факти, готови за UI."""
    signals: list[str] = []

    # 1. Top anomaly
    if anomaly_report.top:
        top = anomaly_report.top[0]
        ne_str = ""
        if top.is_new_extreme and top.new_extreme_direction:
            ne_str = f" · NEW-{top.lookback_years}Y-{top.new_extreme_direction.upper()}"
        signals.append(
            f"Най-силна аномалия: {top.series_key} z={top.z_score:+.2f}{ne_str}"
        )

    # 2. NEW-5Y count в top
    ne_in_top = [a for a in anomaly_report.top if a.is_new_extreme]
    if len(ne_in_top) >= 2:
        signals.append(
            f"{len(ne_in_top)} нови екстремуми в top-{len(anomaly_report.top)} "
            f"(lookback {anomaly_report.lookback_years}г.)"
        )

    # 3. HIGH non-consensus
    high_nc = [r for r in nc_report.highlights if r.signal_strength == "high"]
    if high_nc:
        keys = ", ".join(r.series_key for r in high_nc[:3])
        more = f" +{len(high_nc) - 3}" if len(high_nc) > 3 else ""
        signals.append(f"{len(high_nc)} HIGH non-consensus: {keys}{more}")

    # 4. Pair state digest — non-neutral двойки
    pair_label = {
        "stagflation_test": "Stagflation test",
        "growth_labor_lead_lag": "Growth × Labor",
        "inflation_anchoring": "Inflation anchoring",
        "credit_policy_transmission": "Credit × Policy",
        "sentiment_vs_hard_data": "Sentiment × Hard",
    }
    non_neutral = []
    for p in cross_report.pairs:
        if p.state in ("transition", "insufficient_data"):
            continue
        label = pair_label.get(p.pair_id, p.pair_id)
        non_neutral.append(f"{label}={p.state}")
    if non_neutral:
        signals.append("Активни двойки: " + "; ".join(non_neutral[:3]))

    return signals[:5]


# ============================================================
# INTERNAL — NARRATIVE
# ============================================================

_REGIME_OPENINGS = {
    "stagflation_confirmed": (
        "Картината показва потвърдена стагфлационна конфигурация — трудовият пазар "
        "остава tight, а инфлационният натиск е broad-based."
    ),
    "soft_landing": (
        "Конфигурацията подкрепя soft landing — labor остава tight, но инфлацията "
        "се охлажда. Fed credibility за момента издържа."
    ),
    "disinflation_cooling": (
        "Синхронно охлаждане — labor и инфлация отстъпват заедно. "
        "Рискът се мести към overshooting, ако claims ускорят."
    ),
    "policy_dilemma": (
        "Policy dilemma — labor market е loose, но инфлацията remains hot. "
        "Fed е заклещен между двата мандата."
    ),
    "expansion": (
        "Експанзионен режим — growth и labor сигналите сочат нагоре синхронно. "
        "Инфлацията остава фокус за наблюдение без да е диагностично hot."
    ),
    "slowdown": (
        "Синхронно забавяне — hard activity и labor claims сочат в посока "
        "на отслабване. Late-cycle риск е активен."
    ),
    "credit_stress": (
        "Кредитен стрес — spread-овете се разширяват въпреки policy easing. "
        "Това е non-policy signal, не е резултат от Fed tightening."
    ),
    "transition": (
        "Сигналите са в преход — няма доминираща конфигурация. "
        "Следващите 2-3 релиза ще ориентират посоката."
    ),
}


def _build_narrative(
    regime_key: str,
    lens_rows: list[LensRegimeRow],
    cross_report,
    anomaly_report,
    nc_report,
) -> str:
    """Template-based нарация — 2-4 изречения."""
    parts: list[str] = []

    # Opening — фиксиран per regime
    parts.append(_REGIME_OPENINGS.get(regime_key, f"Режим: {REGIME_LABELS_BG.get(regime_key, regime_key)}."))

    # Най-силно движеща се леща (по breadth дистанция от 0.5)
    diagnostic = _most_diagnostic_lens(lens_rows)
    if diagnostic is not None:
        lens_bg = LENS_LABEL_BG.get(diagnostic.lens, diagnostic.lens)
        bp = diagnostic.breadth_agg
        dir_bg = {
            "expanding": "разширяване",
            "contracting": "свиване",
            "mixed": "смесено",
            "insufficient_data": "—",
        }.get(diagnostic.direction, diagnostic.direction)
        parts.append(
            f"Най-отклонена леща: {lens_bg} — breadth {bp:.0%} ({dir_bg}), "
            f"{diagnostic.anomaly_count} аномалии, {diagnostic.new_extreme_count} нови екстремума."
        )

    # Counter-signal или confirmation
    counter = _find_counter_signal(regime_key, cross_report)
    if counter:
        parts.append(counter)

    # Какво да следим
    watch = _build_watch_sentence(regime_key, anomaly_report, nc_report)
    if watch:
        parts.append(watch)

    return " ".join(parts)


def _most_diagnostic_lens(lens_rows: list[LensRegimeRow]) -> Optional[LensRegimeRow]:
    """Лещата с най-голяма дистанция на breadth от 0.5 (най-посоченият сигнал).

    Пренебрегва редове с NaN breadth или insufficient_data.
    """
    candidates = [
        r for r in lens_rows
        if r.direction != "insufficient_data"
        and isinstance(r.breadth_agg, (int, float))
        and not (isinstance(r.breadth_agg, float) and np.isnan(r.breadth_agg))
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda r: abs(r.breadth_agg - 0.5))


def _find_counter_signal(regime_key: str, cross_report) -> Optional[str]:
    """Ако има pair state, който противоречи на доминиращия режим — surface-ва го."""
    states = {p.pair_id: p.state for p in cross_report.pairs}
    # Inflation anchoring като confirm/counter на stagflation режими
    if regime_key in ("stagflation_confirmed", "policy_dilemma"):
        anchor = states.get("inflation_anchoring")
        if anchor == "a_up_b_down":
            return "Обаче inflation expectations остават anchored — Fed narrative-ът за момента държи."
        if anchor == "both_up":
            return "Expectations също нагоре — de-anchoring в ход, рискът ескалира."

    if regime_key == "soft_landing":
        credit = states.get("credit_policy_transmission")
        if credit == "a_up_b_down":
            return "Предупредителен сигнал: credit spreads се разширяват въпреки easing."

    if regime_key == "disinflation_cooling":
        sentiment = states.get("sentiment_vs_hard_data")
        if sentiment == "a_down_b_up":
            return "Противоречие: hard data още държи, докато sentiment вече се срина."

    if regime_key == "expansion":
        anchor = states.get("inflation_anchoring")
        if anchor == "both_up":
            return "Watch: expectations започват да се разкотвят — late-cycle риск расте."

    return None


def _build_watch_sentence(regime_key: str, anomaly_report, nc_report) -> Optional[str]:
    """Какво да следим в следващия релиз — базирано на active signals."""
    # Ако имаме NEW-5Y екстремуми в top — те са фокусът
    ne_top = [a for a in anomaly_report.top[:5] if a.is_new_extreme]
    if ne_top:
        keys = ", ".join(a.series_key for a in ne_top[:3])
        return f"За наблюдение следващия релиз: {keys} (нови 5-годишни екстремуми)."

    # Иначе — top anomaly
    if anomaly_report.top:
        top = anomaly_report.top[0]
        return f"За наблюдение: {top.series_key} (z={top.z_score:+.2f}) — най-силното отклонение."

    # Ако няма аномалии, но има high non-consensus
    high_nc = [r for r in nc_report.highlights if r.signal_strength == "high"]
    if high_nc:
        keys = ", ".join(r.series_key for r in high_nc[:3])
        return f"За наблюдение: non-consensus HIGH сигнали в {keys}."

    return None
