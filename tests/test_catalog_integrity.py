"""
tests/test_catalog_integrity.py
================================
Guardrails за SERIES_CATALOG. Предпазват от тихи регресии при разширяване.

Целта: когато някой (Claude, бъдещ contributor, ти) добави нова серия
или разбие peer_group, тестовете да fail-нат веднага — не месец по-късно
когато briefing engine-ът почне да произвежда неправилен текст.
"""
from __future__ import annotations

import sys
from pathlib import Path
from collections import Counter

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from catalog.series import (  # noqa: E402
    SERIES_CATALOG,
    ALLOWED_LENSES,
    ALLOWED_SCHEDULES,
)


# ============================================================
# Global invariants
# ============================================================

class TestCatalogSize:
    """Очакван размер — пази срещу silent drift (случайни изтрити серии)."""

    def test_minimum_total_count(self):
        """Каталогът не трябва да пада под очаквания размер (68).

        Upper bound — intentionally open (можем да добавяме)."""
        assert len(SERIES_CATALOG) >= 68, (
            f"Каталогът има само {len(SERIES_CATALOG)} серии — очаквахме ≥68. "
            "Някой е изтрил серии без обновяване на теста?"
        )

    def test_unique_series_keys(self):
        """Ключовете в dict са уникални по дефиниция, но тестваме expected count."""
        # Dict duplicate detection е невъзможно runtime — но количеството трябва
        # да съвпада с броя FRED+pending source entries.
        n_fred = sum(1 for m in SERIES_CATALOG.values() if m["source"] == "fred")
        n_pending = sum(1 for m in SERIES_CATALOG.values() if m["source"] == "pending")
        assert n_fred + n_pending == len(SERIES_CATALOG)

    def test_no_duplicate_fred_ids(self):
        """Два ключа с един FRED ID → data duplication + cache confusion."""
        fred_ids = [
            m["id"] for m in SERIES_CATALOG.values()
            if m["source"] == "fred"
        ]
        duplicates = [fid for fid, c in Counter(fred_ids).items() if c > 1]
        assert not duplicates, f"Дублирани FRED IDs: {duplicates}"


# ============================================================
# Lens invariants — всяка леща има достатъчно покритие
# ============================================================

class TestLensCoverage:
    """Всяка леща трябва да има смислено покритие за да генерира сигнали."""

    MIN_SERIES_PER_LENS = 3

    def test_all_main_lenses_have_coverage(self):
        """Главните 4 лещи (growth/labor/inflation/liquidity) имат ≥3 серии."""
        lens_counter: Counter[str] = Counter()
        for meta in SERIES_CATALOG.values():
            for l in meta.get("lens", []):
                lens_counter[l] += 1

        for main_lens in ("growth", "labor", "inflation", "liquidity"):
            assert lens_counter[main_lens] >= self.MIN_SERIES_PER_LENS, (
                f"Lens '{main_lens}' има само {lens_counter[main_lens]} серии — "
                f"очаквахме ≥{self.MIN_SERIES_PER_LENS}"
            )

    def test_all_lens_values_in_allowed(self):
        """Всяка лензова стойност е в whitelist."""
        for key, meta in SERIES_CATALOG.items():
            for l in meta.get("lens", []):
                assert l in ALLOWED_LENSES, (
                    f"{key}: invalid lens '{l}' (not in {ALLOWED_LENSES})"
                )

    def test_no_orphan_lens_series(self):
        """Всяка серия има поне 1 lens."""
        for key, meta in SERIES_CATALOG.items():
            assert meta.get("lens"), f"{key}: няма lens"


# ============================================================
# Peer group invariants — breadth primitives изискват ≥2 членове
# ============================================================

class TestPeerGroupSizes:
    """Breadth primitives изискват ≥2 членове за смислени резултати.

    Known debt: два peer_group-а от Phase 1 са singletons — документирани
    тук с цел да не се допускат НОВИ singletons. Преди Phase 3 briefing
    engine да стартира, се очаква да добавим companions и да махнем от
    allowlist-а. Тестът ще се обиди ако някой добави companion, но allowlist-
    ът не е актуализиран (forces maintenance).
    """

    # Phase 2.5 (2026-04-17): двата оригинални singleton-а са разширени
    # (hours, business_sentiment). Allowlist-ът е празен — ако бъдещ peer_group
    # стане singleton, или ще добави companion, или ще го впише тук явно.
    KNOWN_SINGLETON_PEER_GROUPS: frozenset[str] = frozenset()

    def test_all_peer_groups_have_min_members(self):
        """Всеки peer_group има ≥2 серии — с изключение на known singletons."""
        pg_counter: Counter[str] = Counter()
        for meta in SERIES_CATALOG.values():
            pg = meta.get("peer_group")
            if pg:
                pg_counter[pg] += 1

        too_small = {pg for pg, c in pg_counter.items() if c < 2}
        unexpected = too_small - self.KNOWN_SINGLETON_PEER_GROUPS
        assert not unexpected, (
            f"Нови peer_groups с <2 членове: {unexpected}. "
            "Breadth primitives изискват ≥2 членове. Или добави companion, "
            "или впиши в KNOWN_SINGLETON_PEER_GROUPS с TODO."
        )

    def test_known_singleton_allowlist_is_still_needed(self):
        """Ако known singleton вече има ≥2 серии — махни от allowlist-а."""
        pg_counter: Counter[str] = Counter()
        for meta in SERIES_CATALOG.values():
            pg = meta.get("peer_group")
            if pg:
                pg_counter[pg] += 1

        obsolete = {
            pg for pg in self.KNOWN_SINGLETON_PEER_GROUPS
            if pg_counter[pg] >= 2
        }
        assert not obsolete, (
            f"Тези peer_groups вече имат ≥2 членове — махни ги от "
            f"KNOWN_SINGLETON_PEER_GROUPS: {obsolete}"
        )

    def test_every_series_has_peer_group(self):
        """Всяка серия е в peer_group (иначе не участва в breadth)."""
        missing = [
            key for key, meta in SERIES_CATALOG.items()
            if not meta.get("peer_group")
        ]
        assert not missing, f"Серии без peer_group: {missing}"


# ============================================================
# Schema invariants — структурна консистентност
# ============================================================

class TestSchema:
    """Всяка серия има задължителните полета."""

    REQUIRED_FIELDS = frozenset({
        "source", "region", "name_bg", "name_en", "lens", "peer_group",
        "tags", "transform", "release_schedule", "revision_prone", "narrative_hint",
    })

    def test_required_fields_present(self):
        for key, meta in SERIES_CATALOG.items():
            missing = self.REQUIRED_FIELDS - set(meta.keys())
            assert not missing, f"{key}: missing fields {missing}"

    def test_fred_source_has_id(self):
        for key, meta in SERIES_CATALOG.items():
            if meta["source"] == "fred":
                assert meta.get("id"), f"{key}: source=fred но няма 'id'"

    def test_schedule_values_allowed(self):
        for key, meta in SERIES_CATALOG.items():
            sch = meta.get("release_schedule")
            assert sch in ALLOWED_SCHEDULES, (
                f"{key}: release_schedule '{sch}' not in {ALLOWED_SCHEDULES}"
            )

    def test_narrative_hint_non_empty(self):
        """Narrative hint е важен за Phase 6 LLM prompt-ите."""
        for key, meta in SERIES_CATALOG.items():
            hint = meta.get("narrative_hint", "")
            assert hint and len(hint) > 10, (
                f"{key}: narrative_hint е празен или тривиален ('{hint}')"
            )


# ============================================================
# Expected peer_group composition (Phase 2 закотвяне)
# ============================================================

class TestExpectedPeerGroups:
    """Локва очакваните peer_groups от Phase 2. Това е intentional anchor —
    ако бъдещ разработчик (или ти) преструктурира, тестът ще pинъят промяната
    за да бъде обмислено решение."""

    EXPECTED_INFLATION_GROUPS = frozenset({
        "headline_measures",
        "core_measures",
        "sticky_measures",
        "goods_services",
        "expectations",
        "wage_dynamics",    # multi-lens labor+inflation
        "labor_share",      # multi-lens labor+inflation
    })

    EXPECTED_LIQUIDITY_GROUPS = frozenset({
        "policy_rates",
        "term_structure",
        "credit_spreads",
        "financial_conditions",
        "money_supply",
        "banking_credit",
    })

    def test_inflation_peer_groups_present(self):
        actual = {
            m["peer_group"] for m in SERIES_CATALOG.values()
            if "inflation" in m.get("lens", [])
        }
        missing = self.EXPECTED_INFLATION_GROUPS - actual
        assert not missing, f"Липсващи inflation peer_groups: {missing}"

    def test_liquidity_peer_groups_present(self):
        actual = {
            m["peer_group"] for m in SERIES_CATALOG.values()
            if "liquidity" in m.get("lens", [])
        }
        missing = self.EXPECTED_LIQUIDITY_GROUPS - actual
        assert not missing, f"Липсващи liquidity peer_groups: {missing}"
