"""
catalog/cross_lens_pairs.py
===========================
Декларативен config на cross-lens divergence pairs.

Всяка pair представлява икономическа теза, която се проверява чрез съпоставка
на breadth между две "slot"-а — всеки slot е колекция от peer_groups, evenutally
с invert ако ↓ на peer_group трябва да се интерпретира като ↑ на темата
(напр. unemployment ↓ → labor tightness ↑).

Структура на pair:
  id: уникален идентификатор
  name_bg, question_bg: човешки етикети
  slot_a, slot_b: dict с {lens, peer_groups, invert, label}
    invert: {peer_group_name: True/False} — ако True, breadth се заменя с 1-breadth
  interpretations: dict с 5 стейта — both_up, both_down, a_up_b_down, a_down_b_up, transition

Икономически рамки на всяка pair: виж narrative поле на всеки запис.
"""
from __future__ import annotations


CROSS_LENS_PAIRS: list[dict] = [
    # ═══════════════════════════════════════════════════════
    # 1. Стагфлация тест — класическа
    # ═══════════════════════════════════════════════════════
    {
        "id": "stagflation_test",
        "name_bg": "Labor tightness × Inflation pressure",
        "question_bg": "Дали labor tightness потвърждава inflation pressure (стагфлация)?",
        "narrative": (
            "Когато и labor market е tight (wages растат, unemployment нисък) И "
            "inflation е hot, имаме стагфлация confirmation. Ако labor tightness "
            "е там, но inflation cools — soft landing. Обратното — policy dilemma."
        ),
        "slot_a": {
            "lens": "labor",
            "peer_groups": ["wage_dynamics", "unemployment"],
            "invert": {"unemployment": True},  # ниска безработица = labor tight
            "label": "Labor tightness",
        },
        "slot_b": {
            "lens": "inflation",
            "peer_groups": ["headline_measures", "core_measures"],
            "invert": {},
            "label": "Inflation pressure",
        },
        "interpretations": {
            "both_up": "Стагфлация confirmation — labor tight + inflation hot.",
            "both_down": "Joint cooling — labor охлажда, inflation cools (disinflation в ход).",
            "a_up_b_down": "Soft landing — labor tight, но inflation cools. Fed credibility holds.",
            "a_down_b_up": "Policy dilemma — labor loose, но inflation still hot.",
            "transition": "Transition — signals not aligned; watch next releases.",
        },
    },

    # ═══════════════════════════════════════════════════════
    # 2. Growth × Labor — leading/lagging check
    # ═══════════════════════════════════════════════════════
    {
        "id": "growth_labor_lead_lag",
        "name_bg": "Hard activity × Labor claims",
        "question_bg": "Дали hard activity и labor market следват едно тенденция?",
        "narrative": (
            "Labor claims обикновено лидират 1-2 месеца пред hard activity turns. "
            "Ако activity още силно, но claims вече растат — early crack сигнал. "
            "Обратното — activity cools, но claims стабилни — late-cycle decoupling."
        ),
        "slot_a": {
            "lens": "growth",
            "peer_groups": ["hard_activity"],
            "invert": {},
            "label": "Hard activity",
        },
        "slot_b": {
            "lens": "labor",
            "peer_groups": ["claims"],
            "invert": {"claims": True},  # claims ↑ = labor weakening
            "label": "Labor market (claims inverted)",
        },
        "interpretations": {
            "both_up": "Aligned expansion — activity растяща, claims низки. Healthy.",
            "both_down": "Synchronized slowdown — activity cools + claims spike.",
            "a_up_b_down": "Activity hot, но claims rise — early labor crack (watchlist).",
            "a_down_b_up": "Activity cools, labor stable — late-cycle decoupling.",
            "transition": "Mixed — waiting for clarification.",
        },
    },

    # ═══════════════════════════════════════════════════════
    # 3. Inflation anchoring check
    # ═══════════════════════════════════════════════════════
    {
        "id": "inflation_anchoring",
        "name_bg": "Realized CPI × Expectations",
        "question_bg": "Дали expectations следват realized inflation, или стоят anchored?",
        "narrative": (
            "Anchored expectations са ключов показател за Fed credibility. Ако "
            "realized inflation е hot, но expectations държат — Fed контролира "
            "narrative-а. Ако expectations следват realized — de-anchoring."
        ),
        "slot_a": {
            "lens": "inflation",
            "peer_groups": ["headline_measures", "core_measures"],
            "invert": {},
            "label": "Realized inflation",
        },
        "slot_b": {
            "lens": "inflation",
            "peer_groups": ["expectations"],
            "invert": {},
            "label": "Inflation expectations",
        },
        "interpretations": {
            "both_up": "De-anchoring in progress — expectations следват realized up.",
            "both_down": "Joint disinflation — expectations потвърждават cooling.",
            "a_up_b_down": "Anchored — realized hot, expectations stable. Credibility holds.",
            "a_down_b_up": "Rare — expectations rising while realized cools (stagflation fear narrative?).",
            "transition": "Monitoring.",
        },
    },

    # ═══════════════════════════════════════════════════════
    # 4. Credit × Policy — transmission check
    # ═══════════════════════════════════════════════════════
    {
        "id": "credit_policy_transmission",
        "name_bg": "Credit spreads × Policy rates",
        "question_bg": "Дали credit следва policy направление — transmission intact?",
        "narrative": (
            "Normally tightening rates → credit spreads widen (transmission). "
            "Ако rates up, но spreads tight — market пренебрегва Fed; либо "
            "rates down, но spreads wide — non-policy stress (credit event)."
        ),
        "slot_a": {
            "lens": "liquidity",
            "peer_groups": ["credit_spreads"],
            "invert": {},
            "label": "Credit stress",
        },
        "slot_b": {
            "lens": "liquidity",
            "peer_groups": ["policy_rates"],
            "invert": {},
            "label": "Policy tightening",
        },
        "interpretations": {
            "both_up": "Tightening transmits — rates up + credit widens.",
            "both_down": "Easing transmits — rates down + credit tightens.",
            "a_up_b_down": "Credit stress despite easing — non-policy stress signal.",
            "a_down_b_up": "Benign credit despite tightening — liquidity cushion intact.",
            "transition": "Mixed transmission.",
        },
    },

    # ═══════════════════════════════════════════════════════
    # 5. Sentiment × Hard data
    # ═══════════════════════════════════════════════════════
    {
        "id": "sentiment_vs_hard_data",
        "name_bg": "Consumer sentiment × Hard activity",
        "question_bg": "Дали sentiment потвърждава hard data, или има разминаване?",
        "narrative": (
            "Consumer sentiment може да разминава от hard activity при политически "
            "transitions (post-election bias), gas price shocks, medijen narrative. "
            "Типично activity lead-ва, sentiment follows. Sentiment без data confirm "
            "е ненадежден сигнал."
        ),
        "slot_a": {
            "lens": "growth",
            "peer_groups": ["consumer_sentiment"],
            "invert": {},
            "label": "Consumer sentiment",
        },
        "slot_b": {
            "lens": "growth",
            "peer_groups": ["hard_activity"],
            "invert": {},
            "label": "Hard activity",
        },
        "interpretations": {
            "both_up": "Aligned — sentiment и activity растат заедно.",
            "both_down": "Aligned weakness — sentiment потвърждава cooling.",
            "a_up_b_down": "Sentiment ahead of data — watch for confirmation.",
            "a_down_b_up": "Activity OK, sentiment крачка — strategic pessimism / political bias.",
            "transition": "Monitoring — divergence typical в political transitions.",
        },
    },

    # ═══════════════════════════════════════════════════════
    # 6. Model vs Market — inflation view mismatch
    # ═══════════════════════════════════════════════════════
    {
        "id": "model_vs_market",
        "name_bg": "Model-implied × Market-implied inflation",
        "question_bg": "Дали underlying persistence и market pricing-а са съгласни за инфлацията?",
        "narrative": (
            "Model view = sticky/median/trimmed-mean CPI — underlying persistent pressure. "
            "Market view = breakevens (5y, 5y5y forward) + 1Y Michigan survey — какво pricing-ва пазарът. "
            "Когато моделът казва persistent, а пазарът pricing-ва disinflation — contrarian hawkish setup. "
            "Обратното — market може да е overestimating, dovish contrarian."
        ),
        "slot_a": {
            "lens": "inflation",
            "peer_groups": ["sticky_measures"],
            "invert": {},
            "label": "Модел (sticky inflation)",
        },
        "slot_b": {
            "lens": "inflation",
            "peer_groups": ["expectations"],
            "invert": {},
            "label": "Пазар (breakevens + survey)",
        },
        "interpretations": {
            "both_up": "Съгласие — underlying persistent + пазар pricing-ва inflation. Fed зад кривата.",
            "both_down": "Съгласие — disinflation confirmation. Converging view.",
            "a_up_b_down": "Модел persistent, пазар разчита на disinflation — contrarian hawkish (моделът обикновено лидера).",
            "a_down_b_up": "Модел cools, пазар pricing-ва inflation — market overestimating; dovish contrarian setup.",
            "transition": "Без decisive сигнал — изчакай следващ CPI/breakeven print.",
        },
    },
]


# ============================================================
# VALIDATION
# ============================================================

REQUIRED_PAIR_FIELDS = frozenset({
    "id", "name_bg", "question_bg", "narrative",
    "slot_a", "slot_b", "interpretations",
})

REQUIRED_SLOT_FIELDS = frozenset({"lens", "peer_groups", "invert", "label"})

REQUIRED_INTERPRETATION_STATES = frozenset({
    "both_up", "both_down", "a_up_b_down", "a_down_b_up", "transition",
})


def validate_pairs(pairs: list[dict] = None) -> list[str]:
    """Валидира config-а. Връща списък с грешки (празен ако всичко OK)."""
    if pairs is None:
        pairs = CROSS_LENS_PAIRS

    errors: list[str] = []
    seen_ids: set[str] = set()

    for i, pair in enumerate(pairs):
        prefix = f"pair[{i}]"
        missing = REQUIRED_PAIR_FIELDS - set(pair.keys())
        if missing:
            errors.append(f"{prefix}: missing fields {missing}")
            continue

        pid = pair["id"]
        if pid in seen_ids:
            errors.append(f"{prefix}: duplicate id '{pid}'")
        seen_ids.add(pid)

        for slot_name in ("slot_a", "slot_b"):
            slot = pair[slot_name]
            missing_slot = REQUIRED_SLOT_FIELDS - set(slot.keys())
            if missing_slot:
                errors.append(f"{prefix}.{slot_name}: missing fields {missing_slot}")

        interp_states = set(pair["interpretations"].keys())
        missing_interp = REQUIRED_INTERPRETATION_STATES - interp_states
        if missing_interp:
            errors.append(f"{prefix}.interpretations: missing states {missing_interp}")

    return errors
