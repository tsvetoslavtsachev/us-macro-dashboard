"""
econ_v2 — Entry Point
======================
Три workflow-а:

    python run.py              # Legacy dashboard (Labor + Inflation + Growth)
    python run.py --status     # Phase 1: Data Status Screen
    python run.py --briefing   # Phase 3: Weekly Briefing + Explorer

Глобални опции (работят със --status и --briefing):
    --refresh        Force-fetch всички FRED серии преди генериране
    --no-browser     Не отваря HTML в браузъра (CI / headless)

Legacy workflow:
  1. Зарежда FRED данни (кеш 12h)
  2. Изчислява Labor, Inflation, Growth модули
  3. Генерира composite Macro Score
  4. Записва dashboard_YYYY-MM-DD.html в output/
  5. Отваря файла в браузъра

Status workflow (Phase 1):
  1. Чете cache от sources/fred_adapter.py
  2. Класифицира всяка серия (fresh / delayed / delayed_explained / stale / pending)
  3. Записва data_status_YYYY-MM-DD.html в output/
  4. Отваря файла в браузъра

Briefing workflow (Phase 3):
  1. Чете snapshot от cache (или fetch-ва с --refresh)
  2. Генерира briefing_YYYY-MM-DD.html (exec summary, regime, WoW delta,
     cross-lens, lens blocks, non-consensus, anomalies, falsifiers, flags)
  3. Генерира explorer.html (71 серии с sparkline + peer context)
  4. Записва WoW state в data/state/briefing_YYYY-MM-DD.json
  5. Отваря briefing-а в браузъра
"""

import argparse
import sys
import os
import logging
import webbrowser
from pathlib import Path
from datetime import datetime

# Добавяме econ_v2/ в Python path
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)

# Shared config (лек import — няма network)
from config import (
    FRED_API_KEY,
    CACHE_TTL_HOURS,
    MODULE_WEIGHTS,
    MACRO_REGIMES,
    OUTPUT_DIR,
)


def main():
    # Legacy imports — lazy, за да не пречат на --status при липсващ fredapi/etc
    from core.fred_client import FredClient
    from core.scorer import get_regime
    import modules.labor as labor_mod
    import modules.inflation as inflation_mod
    import modules.growth as growth_mod
    from export import html_generator

    print("\n" + "═" * 60)
    print("  ⚡  Economic Intelligence Dashboard  v2.0")
    print("═" * 60)
    print(f"  {datetime.now().strftime('%A, %d %B %Y · %H:%M')}")
    print("═" * 60 + "\n")

    # ── 1. FRED Client ────────────────────────────────────────────
    print("📡 Connecting to FRED...")
    client = FredClient(api_key=FRED_API_KEY, cache_ttl_hours=CACHE_TTL_HOURS)

    # ── 2. Run Modules ────────────────────────────────────────────
    print("\n🔬 Running modules...")
    modules_results = []

    for mod_name, mod, weight_key in [
        ("Labor Market",     labor_mod,     "labor"),
        ("Inflation",        inflation_mod, "inflation"),
        ("Growth & Activity",growth_mod,    "growth"),
    ]:
        try:
            result = mod.run(client)
            modules_results.append(result)
            score = result.get("composite", 50.0)
            regime = result.get("regime", "—")
            print(f"  ✅ {mod_name:20s} → score: {score:5.1f}  [{regime}]")
        except Exception as e:
            print(f"  ❌ {mod_name}: {e}")
            import traceback; traceback.print_exc()

    # ── 3. Composite Macro Score ──────────────────────────────────
    active_weights = {
        "labor":     MODULE_WEIGHTS["labor"],
        "inflation": MODULE_WEIGHTS["inflation"],
        "growth":    MODULE_WEIGHTS["growth"],
    }
    total_weight = sum(active_weights.values())

    composite = 0.0
    for r in modules_results:
        mod_key = r["module"]
        w = active_weights.get(mod_key, 0)
        composite += r.get("composite", 50.0) * w

    composite = round(composite / total_weight, 1)
    regime_label, regime_color = get_regime(composite, MACRO_REGIMES)

    print(f"\n{'═'*60}")
    print(f"  📊 MACRO COMPOSITE SCORE: {composite:.1f} / 100")
    print(f"  🏷  REGIME: {regime_label}")
    print(f"{'═'*60}\n")

    # ── 4. Save cache ─────────────────────────────────────────────
    client.save_cache()

    # ── 5. Generate HTML ──────────────────────────────────────────
    print("🎨 Generating dashboard HTML...")
    html = html_generator.generate(
        modules_data=modules_results,
        composite_score=composite,
        composite_regime=regime_label,
        composite_color=regime_color,
    )

    output_path = BASE_DIR / OUTPUT_DIR
    out_file = html_generator.save(html, str(output_path))
    print(f"  ✅ Saved: {out_file.name}")

    # ── 6. Open in browser ────────────────────────────────────────
    abs_path = out_file.resolve()
    url = abs_path.as_uri()
    print(f"\n🌐 Opening dashboard in browser...")
    print(f"   {abs_path}")
    webbrowser.open(url)

    print("\n✅ Done! Dashboard is ready.\n")
    return str(abs_path)


# ============================================================
# PHASE 1 — Data Status Screen path
# ============================================================

def main_status(args) -> str:
    """Phase 1: Генерира Data Status Screen чрез FredAdapter + catalog."""
    # Lazy imports — не пречи на legacy path ако новите модули имат import issue
    from sources.fred_adapter import FredAdapter
    from catalog.series import SERIES_CATALOG
    from export.data_status import generate_data_status

    print("\n" + "═" * 60)
    print("  📋  Data Status Screen  —  econ_v2 · Phase 1")
    print("═" * 60)
    print(f"  {datetime.now().strftime('%A, %d %B %Y · %H:%M')}")
    print("═" * 60 + "\n")

    adapter = FredAdapter(api_key=FRED_API_KEY, base_dir=BASE_DIR)

    if args.refresh:
        print("🔄 Refreshing FRED серии...")
        fred_specs = [
            {
                "key": key,
                "fred_id": meta["id"],
                "release_schedule": meta["release_schedule"],
            }
            for key, meta in SERIES_CATALOG.items()
            if meta.get("source") == "fred"
        ]
        results = adapter.fetch_many(fred_specs, force=True)
        ok = sum(1 for s in results.values() if not getattr(s, "empty", True))
        print(f"  ✅ Fetched {ok}/{len(fred_specs)} серии\n")
    else:
        # Без --refresh само проверяваме какво е в кеша
        cache_count = sum(
            1 for key in SERIES_CATALOG
            if adapter.get_cache_status(key).get("is_cached")
        )
        print(f"📦 Cache: {cache_count}/{len(SERIES_CATALOG)} серии налични")
        print("   (Използвай --refresh за да ги обновиш от FRED)\n")

    # Генериране на HTML
    output_path = BASE_DIR / OUTPUT_DIR
    print("🎨 Генерирам Data Status HTML...")
    out_file = generate_data_status(adapter, SERIES_CATALOG, output_path)
    print(f"  ✅ Saved: {out_file.name}")

    # Отваряне в браузъра
    if not args.no_browser:
        abs_path = out_file.resolve()
        url = abs_path.as_uri()
        print(f"\n🌐 Opening in browser...")
        print(f"   {abs_path}")
        webbrowser.open(url)

    print("\n✅ Done!\n")
    return str(out_file.resolve())


# ============================================================
# PHASE 3 — Weekly Briefing + Explorer path
# ============================================================

def main_briefing(args) -> str:
    """Phase 3: Генерира Weekly Briefing + Explorer от каталога.

    Ходът е паралелен на `main_status`:
      1. Ако --refresh → fetch_many(force=True)
         иначе → чете се само cache-а.
      2. snapshot = adapter.get_snapshot(SERIES_CATALOG.keys())
      3. generate_weekly_briefing → briefing_YYYY-MM-DD.html
         (persist-ва WoW state в data/state/)
      4. generate_explorer → explorer.html + explorer_YYYY-MM-DD.html копие
      5. webbrowser.open(briefing)  (ако не --no-browser)

    Връща абсолютния path към briefing-а.
    """
    # Lazy imports — не пречи на legacy path
    from datetime import date
    from sources.fred_adapter import FredAdapter
    from catalog.series import SERIES_CATALOG
    from export.weekly_briefing import generate_weekly_briefing
    from export.explorer import generate_explorer

    print("\n" + "═" * 60)
    print("  📰  Weekly Briefing  —  econ_v2 · Phase 3")
    print("═" * 60)
    print(f"  {datetime.now().strftime('%A, %d %B %Y · %H:%M')}")
    print("═" * 60 + "\n")

    adapter = FredAdapter(api_key=FRED_API_KEY, base_dir=BASE_DIR)

    fred_specs = [
        {
            "key": key,
            "fred_id": meta["id"],
            "release_schedule": meta["release_schedule"],
        }
        for key, meta in SERIES_CATALOG.items()
        if meta.get("source") == "fred"
    ]

    if args.refresh:
        print("🔄 Refreshing FRED серии (force, всички)...")
        adapter.fetch_many(fred_specs, force=True)
        failures = adapter.last_fetch_failures()
        fresh_n = len(fred_specs) - len(failures)
        print(f"  ✅ {fresh_n}/{len(fred_specs)} серии успешно обновени")
        if failures:
            print(f"  ⚠ {len(failures)} fall-back към кеш (FRED API недостъпен): "
                  f"{', '.join(failures)}")
        print()
    else:
        # Auto-refresh: fetch_many(force=False) skip-ва fresh-те (по TTL),
        # fetch-ва само stale-те. Тук пред-преброяваме за ясно UX-съобщение.
        stale_specs = adapter.find_stale_specs(fred_specs)
        fresh_count = len(fred_specs) - len(stale_specs)
        if stale_specs:
            print(f"📦 Cache: {fresh_count}/{len(fred_specs)} серии fresh; "
                  f"{len(stale_specs)} stale — auto-refresh от FRED...")
            adapter.fetch_many(stale_specs, force=False)
            failures = adapter.last_fetch_failures()
            refreshed_n = len(stale_specs) - len(failures)
            print(f"  ✅ {refreshed_n}/{len(stale_specs)} серии успешно обновени "
                  f"(--refresh за принудително презареждане на всички)")
            if failures:
                print(f"  ⚠ {len(failures)} fall-back към кеш (FRED API недостъпен): "
                      f"{', '.join(failures)}")
            print()
        else:
            print(f"📦 Cache: {fresh_count}/{len(fred_specs)} серии fresh — "
                  f"няма нужда от refresh.\n")

    # Build snapshot от cache (дори след refresh — unified path)
    snapshot = adapter.get_snapshot(SERIES_CATALOG.keys())
    print(f"📊 Snapshot: {len(snapshot)}/{len(SERIES_CATALOG)} серии с данни\n")

    # ─── Analog bundle (Phase 4, opt-in) ──────────────────────────
    analog_bundle = None
    if getattr(args, "with_analogs", False):
        import pandas as pd
        from analysis.macro_vector import ANALOG_FETCH_SPEC
        from analysis.analog_pipeline import compute_analog_bundle

        print("🔭 Fetch на ANALOG_* серии (deep history за Historical Analog Engine)...")
        analog_specs = [
            {
                "key": spec["key"],
                "fred_id": spec["fred_id"],
                "release_schedule": spec["schedule"],
            }
            for spec in ANALOG_FETCH_SPEC
        ]
        try:
            analog_fetched = adapter.fetch_many(analog_specs, force=args.refresh)
            ok_analog = sum(1 for s in analog_fetched.values() if not getattr(s, "empty", True))
            print(f"  ✅ Fetched {ok_analog}/{len(analog_specs)} analog серии")

            print("🧩 Изчислявам analog bundle (top-3, 1976+)...")
            analog_bundle = compute_analog_bundle(analog_fetched, today=pd.Timestamp(date.today()))
            if analog_bundle is None:
                print("  ⚠ analog bundle=None (недостиг на complete-case ред) — briefing ще пропусне секцията")
            else:
                print(f"  ✅ {len(analog_bundle.analogs)} analog-а избрани "
                      f"(as_of={analog_bundle.current_state.as_of.strftime('%Y-%m')})\n")
        except Exception as e:
            logging.warning(f"analog bundle компютирането се провали: {e}. "
                            "Briefing ще се генерира без 'Исторически аналог' секция.")
            analog_bundle = None

    today = date.today()
    output_dir = BASE_DIR / OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    # ─── Journal entries (Research Desk, opt-in) ──────────────────
    journal_entries = None
    if getattr(args, "with_journal", False):
        from scripts._utils import load_journal_entries
        try:
            all_entries = load_journal_entries()
            # Simple relevance ranking:
            #   1. Отворени въпроси и хипотези имат приоритет (undone work)
            #   2. Най-скорошните първи
            #   3. Cap на --journal-max
            status_priority = {"open_question": 0, "hypothesis": 1, "finding": 2, "decision": 3}
            all_entries.sort(key=lambda e: (status_priority.get(e.status, 9), -e.date.toordinal()))
            journal_entries = all_entries[:args.journal_max]
            print(f"📓 Journal: {len(journal_entries)} записа избрани "
                  f"(от {len(all_entries)} общо)")
        except Exception as e:
            logging.warning(f"Journal зареждането се провали: {e}. "
                            "Briefing ще се генерира без 'Свързани бележки' секция.")
            journal_entries = None

    briefing_filename = f"briefing_{today.isoformat()}.html"
    briefing_path = output_dir / briefing_filename
    explorer_path = output_dir / "explorer.html"
    explorer_dated = output_dir / f"explorer_{today.isoformat()}.html"
    state_dir = BASE_DIR / "data" / "state"

    # ─── Briefing ─────────────────────────────────────────────────
    print("📰 Генерирам Weekly Briefing...")
    generate_weekly_briefing(
        snapshot,
        str(briefing_path),
        today=today,
        state_dir=str(state_dir),
        persist_state=True,
        analog_bundle=analog_bundle,
        journal_entries=journal_entries,
    )
    print(f"  ✅ {briefing_path.name} ({briefing_path.stat().st_size // 1024} KB)")

    # ─── Explorer ─────────────────────────────────────────────────
    print("🔍 Генерирам Series Explorer...")
    generate_explorer(
        snapshot,
        str(explorer_path),
        today=today,
        briefing_href=briefing_filename,
    )
    # Dated копие за archive (undated name-ът остава stable за briefing-links)
    explorer_dated.write_bytes(explorer_path.read_bytes())
    print(f"  ✅ {explorer_path.name} + archive {explorer_dated.name}"
          f" ({explorer_path.stat().st_size // 1024} KB)")

    # ─── Browser ──────────────────────────────────────────────────
    if not args.no_browser:
        abs_path = briefing_path.resolve()
        url = abs_path.as_uri()
        print(f"\n🌐 Opening briefing in browser...")
        print(f"   {abs_path}")
        webbrowser.open(url)

    print("\n✅ Done!\n")
    return str(briefing_path.resolve())


# ============================================================
# REFRESH-ONLY MODE
# ============================================================

def main_refresh_only(args):
    """Refresh само на FRED данни — без HTML output.

    - Без --refresh: smart auto-refresh (само stale серии по TTL).
    - С --refresh: force-refresh на всички 69 FRED серии.
    """
    print("\n" + "═" * 60)
    print("  🔄  Refresh данни  —  econ_v2")
    print("═" * 60)
    print(f"  {datetime.now().strftime('%A, %d %B %Y · %H:%M')}")
    print("═" * 60 + "\n")

    from sources.fred_adapter import FredAdapter
    from catalog.series import SERIES_CATALOG
    adapter = FredAdapter(api_key=FRED_API_KEY, base_dir=BASE_DIR)

    fred_specs = [
        {
            "key": key,
            "fred_id": meta["id"],
            "release_schedule": meta["release_schedule"],
        }
        for key, meta in SERIES_CATALOG.items()
        if meta.get("source") == "fred"
    ]

    if args.refresh:
        print(f"🔄 Force-refresh: re-fetch на всички {len(fred_specs)} серии...")
        adapter.fetch_many(fred_specs, force=True)
        failures = adapter.last_fetch_failures()
        fresh_n = len(fred_specs) - len(failures)
        print(f"  ✅ {fresh_n}/{len(fred_specs)} серии успешно обновени")
        if failures:
            print(f"  ⚠ {len(failures)} fall-back към кеш (FRED API недостъпен): "
                  f"{', '.join(failures)}")
    else:
        stale_specs = adapter.find_stale_specs(fred_specs)
        fresh_count = len(fred_specs) - len(stale_specs)
        if not stale_specs:
            print(f"📦 Cache: {fresh_count}/{len(fred_specs)} серии fresh — "
                  f"няма нужда от refresh.")
            print("   (Използвай --refresh за принудителен re-fetch на всички.)")
        else:
            print(f"📦 Cache: {fresh_count}/{len(fred_specs)} серии fresh; "
                  f"{len(stale_specs)} stale — auto-refresh от FRED...")
            adapter.fetch_many(stale_specs, force=False)
            failures = adapter.last_fetch_failures()
            refreshed_n = len(stale_specs) - len(failures)
            print(f"  ✅ {refreshed_n}/{len(stale_specs)} серии успешно обновени")
            if failures:
                print(f"  ⚠ {len(failures)} fall-back към кеш (FRED API недостъпен): "
                      f"{', '.join(failures)}")

    print("\n✅ Done!\n")


# ============================================================
# CLI
# ============================================================

def _parse_args():
    parser = argparse.ArgumentParser(
        description="econ_v2 — Economic Intelligence",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--status",
        action="store_true",
        help="Phase 1: Генерирай Data Status Screen вместо legacy dashboard.",
    )
    mode.add_argument(
        "--briefing",
        action="store_true",
        help="Phase 3: Генерирай Weekly Briefing + Explorer.",
    )
    mode.add_argument(
        "--refresh-only",
        dest="refresh_only",
        action="store_true",
        help="Само refresh на данни от FRED — без HTML output. "
             "По default smart (само stale серии); с --refresh force-refresh на всички.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force-fetch всички FRED серии (игнорира TTL кеш). Работи със --status и --briefing.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Не отваря HTML в браузъра.",
    )
    parser.add_argument(
        "--with-analogs",
        action="store_true",
        help="Phase 4: Добавя 'Исторически аналог' секция в briefing-а. "
             "Изисква fetch на 11 ANALOG_* серии (1976+). Работи само със --briefing.",
    )
    parser.add_argument(
        "--with-journal",
        action="store_true",
        help="Research Desk: Добавя 'Свързани бележки' секция в briefing-а, "
             "link-ваща към релевантни journal/ записи. Работи само със --briefing.",
    )
    parser.add_argument(
        "--journal-max",
        type=int,
        default=5,
        help="Максимум брой journal записи в briefing-а (default: 5).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if args.refresh_only:
        main_refresh_only(args)
    elif args.briefing:
        main_briefing(args)
    elif args.status:
        main_status(args)
    else:
        main()
