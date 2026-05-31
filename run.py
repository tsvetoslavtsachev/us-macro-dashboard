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

# Windows конзолата по подразбиране е cp1252 → box-drawing/emoji хвърлят
# UnicodeEncodeError. Reconfigure към utf-8 преди всякакъв print.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Добавяме econ_v2/ в Python path
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)


def _bloomberg_bridge_snapshot() -> dict:
    """Bloomberg bridge серии — parquet (local dev) или committed JSON (CI), read-only.

    vrm-data-archive parquet не е достъпен в CI → adapter-ът чете
    data/bloomberg_bridge.json (committed). Локално чете freshest parquet.
    """
    try:
        from catalog.series import SERIES_CATALOG
        from sources.bloomberg_bridge_adapter import BloombergBridgeAdapter
        snap = BloombergBridgeAdapter(base_dir=BASE_DIR).get_snapshot(SERIES_CATALOG)
        if snap:
            print(f"📦 Bloomberg bridge: добавени {len(snap)} серии")
        return snap
    except Exception as e:
        logging.warning(f"Bloomberg bridge snapshot failed: {e}")
        return {}

# Shared config (лек import — няма network)
from config import (
    FRED_API_KEY,
    FIRECRAWL_API_KEY,
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
    from sources.external_loader import get_external_cache_status, UnifiedStatusAdapter
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

    # Build unified status adapter (FRED + external indicators)
    external_statuses = get_external_cache_status(SERIES_CATALOG, BASE_DIR)
    n_external_cached = sum(1 for s in external_statuses.values() if s.get("is_cached"))
    print(f"📦 External: {n_external_cached}/{len(external_statuses)} ISM/CB indicators в cache")
    unified_adapter = UnifiedStatusAdapter(adapter, external_statuses)

    # Генериране на HTML
    output_path = BASE_DIR / OUTPUT_DIR
    print("🎨 Генерирам Data Status HTML...")
    out_file = generate_data_status(unified_adapter, SERIES_CATALOG, output_path)
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
    from sources.external_loader import load_external_series
    from catalog.series import SERIES_CATALOG
    from export.weekly_briefing import generate_weekly_briefing
    from export.quick_briefing import generate_quick_briefing
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
    # Merge external indicators (ISM, CB LEI/CCI) — те имат отделни cache файлове
    external = load_external_series(SERIES_CATALOG, BASE_DIR)
    if external:
        snapshot.update(external)
        print(f"📦 External: добавени {len(external)} ISM/CB серии в snapshot")
    snapshot.update(_bloomberg_bridge_snapshot())
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
    quick_filename = f"briefing_quick_{today.isoformat()}.html"
    quick_path = output_dir / quick_filename
    explorer_path = output_dir / "explorer.html"
    explorer_dated = output_dir / f"explorer_{today.isoformat()}.html"
    state_dir = BASE_DIR / "data" / "state"

    # ─── Briefing (deep) ──────────────────────────────────────────
    print("📰 Генерирам Weekly Briefing (deep)...")
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

    # ─── Quick briefing (China-style scoreboard) ──────────────────
    print("⚡ Генерирам Quick Briefing (scoreboard)...")
    generate_quick_briefing(
        snapshot,
        str(quick_path),
        today=today,
        deep_link=briefing_filename,
    )
    print(f"  ✅ {quick_path.name} ({quick_path.stat().st_size // 1024} KB)")

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
# EXPORT-CONTEXT MODE (Claude-friendly Markdown)
# ============================================================

def main_export_context(args) -> str:
    """Генерира briefing_context_YYYY-MM-DD.md за LLM анализ.

    Чете snapshot от cache (или fetch-ва с --refresh), изчислява всички
    analytical layers (breadth, cross-lens, anomalies) и експортира
    Markdown с пълен контекст. Не генерира HTML.
    """
    from datetime import date as date_cls
    from sources.fred_adapter import FredAdapter
    from sources.external_loader import load_external_series
    from catalog.series import SERIES_CATALOG
    from analysis.breadth import compute_lens_breadth
    from analysis.divergence import compute_cross_lens_divergence
    from analysis.anomaly import compute_anomalies
    from export.briefing_context import generate_briefing_context

    today = date_cls.today()

    print("\n" + "═" * 60)
    print("  📝  Export Briefing Context (.md)  —  econ_v2")
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
            print(f"  ⚠ {len(failures)} fall-back към кеш: {', '.join(failures)}")
        print()
    else:
        stale_specs = adapter.find_stale_specs(fred_specs)
        if stale_specs:
            print(f"📦 Auto-refresh: {len(stale_specs)} stale серии...")
            adapter.fetch_many(stale_specs, force=False)
            failures = adapter.last_fetch_failures()
            refreshed_n = len(stale_specs) - len(failures)
            print(f"  ✅ {refreshed_n}/{len(stale_specs)} обновени\n")
        else:
            print(f"📦 Cache fresh — пропускам refresh.\n")

    # Build snapshot — FRED + external (ISM, CB LEI/CCI)
    snapshot = adapter.get_snapshot(SERIES_CATALOG.keys())
    external = load_external_series(SERIES_CATALOG, BASE_DIR)
    if external:
        snapshot.update(external)
        print(f"📦 External: добавени {len(external)} ISM/CB серии")
    snapshot.update(_bloomberg_bridge_snapshot())
    print(f"📊 Snapshot: {len(snapshot)}/{len(SERIES_CATALOG)} серии с данни\n")

    # Compute analysis layers
    print("🧮 Изчислявам breadth, cross-lens, anomalies...")
    lens_reports = {
        lens: compute_lens_breadth(lens, snapshot) for lens in
        ["labor", "growth", "inflation", "liquidity"]
    }
    cross_report = compute_cross_lens_divergence(snapshot)
    anomaly_report = compute_anomalies(snapshot, z_threshold=2.0, top_n=10, lookback_years=5)

    # Generate markdown
    output_dir = BASE_DIR / OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    print("📝 Генерирам briefing context...")
    md_path = generate_briefing_context(
        snapshot=snapshot,
        lens_reports=lens_reports,
        cross_report=cross_report,
        anomaly_report=anomaly_report,
        today=today,
        output_path=output_dir,
    )
    size_kb = Path(md_path).stat().st_size / 1024
    print(f"  ✅ {Path(md_path).name} ({size_kb:.1f} KB)")
    print(f"\n   Path: {md_path}")
    print("\n💡 Отвори файла или го закачи към Claude чат за дълбок анализ.\n")
    print("✅ Done!\n")
    return md_path


# ============================================================
# FETCH-ISM MODE
# ============================================================

def main_fetch_ism(args) -> None:
    """Scrape ISM Manufacturing + Services PMI през Firecrawl, кешира резултата.

    Free-tier Firecrawl ограничение: само латест месец (не historical series).
    Кешът е валиден 25 дни — обхваща един release cycle.
    """
    from sources.ism_adapter import ISMAdapter

    print("\n" + "═" * 60)
    print("  📊  Fetch ISM PMI  —  econ_v2")
    print("═" * 60)
    print(f"  {datetime.now().strftime('%A, %d %B %Y · %H:%M')}")
    print("═" * 60 + "\n")

    adapter = ISMAdapter(api_key=FIRECRAWL_API_KEY, base_dir=BASE_DIR)

    print("🌐 Scrape ISM (двустъпков: index → report)...")
    results = adapter.fetch_all(force=args.refresh)
    failures = adapter.last_fetch_failures()

    for key, entry in results.items():
        if not entry:
            print(f"  ❌ {key}: няма данни (fetch fail-на, няма cache)")
            continue
        current = entry.get("current") or {}
        headline = current.get("headline")
        month = current.get("month")
        n_sub = len(current.get("subindices", {}))
        quality = current.get("parse_quality", "?")
        n_hist = len(entry.get("history", {}))
        hist_src = entry.get("history_source") or "—"
        marker = "✅" if quality == "ok" else "⚠"
        print(f"  {marker} {key}: {headline}% ({month}) — {n_sub} sub-indices "
              f"[parse: {quality}] · history: {n_hist} obs ({hist_src})")

    if failures:
        print(f"\n⚠ Failures: {', '.join(failures)}")
        print("  Виж logs за детайли. Provider down / structure changed → debug markdown")
        print("  във data/ism_debug/.")

    print(f"\n📦 Cache: {adapter.cache_path}")
    print("\n✅ Done!\n")


# ============================================================
# FETCH-CONFBOARD MODE
# ============================================================

def main_fetch_confboard(args) -> None:
    """Scrape Conference Board LEI + Consumer Confidence през Firecrawl.

    Same pattern като main_fetch_ism — single-step fetch (CB topic pages
    embed-ват latest press release inline).
    """
    from sources.confboard_adapter import ConfBoardAdapter

    print("\n" + "═" * 60)
    print("  📊  Fetch Conference Board (LEI + CCI)  —  econ_v2")
    print("═" * 60)
    print(f"  {datetime.now().strftime('%A, %d %B %Y · %H:%M')}")
    print("═" * 60 + "\n")

    adapter = ConfBoardAdapter(api_key=FIRECRAWL_API_KEY, base_dir=BASE_DIR)
    print("🌐 Scrape Conference Board (single-step)...")
    results = adapter.fetch_all(force=args.refresh)
    failures = adapter.last_fetch_failures()

    for key, entry in results.items():
        if not entry:
            print(f"  ❌ {key}: няма данни (fetch fail-на, няма cache)")
            continue
        current = entry.get("current") or {}
        headline = current.get("headline")
        month = current.get("month")
        n_sub = len(current.get("subcomponents", {}))
        quality = current.get("parse_quality", "?")
        mom = current.get("mom_change")
        mom_str = f", MoM {mom:+}" if mom is not None else ""
        n_hist = len(entry.get("history", {}))
        hist_src = entry.get("history_source") or "—"
        marker = "✅" if quality == "ok" else "⚠"
        print(f"  {marker} {key}: {headline} ({month}{mom_str}) — "
              f"{n_sub} subcomponents [parse: {quality}] · "
              f"history: {n_hist} obs ({hist_src})")

    if failures:
        print(f"\n⚠ Failures: {', '.join(failures)}")
        print("  Debug markdown — data/confboard_debug/")

    print(f"\n📦 Cache: {adapter.cache_path}")
    print("\n✅ Done!\n")


# ============================================================
# FETCH-ZILLOW MODE
# ============================================================

def main_fetch_zillow(args) -> None:
    """Download Zillow CSV(s) и кешира резултата.

    CC0 licensed данни — свободно за republish.
    Refresh: monthly cycle (cache TTL 20 дни).
    """
    from sources.zillow_adapter import ZillowAdapter
    from catalog.series import SERIES_CATALOG

    print("\n" + "═" * 60)
    print("  📊  Fetch Zillow (CC0 public CSV)  —  econ_v2")
    print("═" * 60)
    print(f"  {datetime.now().strftime('%A, %d %B %Y · %H:%M')}")
    print("═" * 60 + "\n")

    # Извличаме всички zillow specs от каталога
    specs: list[dict] = []
    for key, meta in SERIES_CATALOG.items():
        if meta.get("source") != "external":
            continue
        if meta.get("cache_file") != "data/zillow_cache.json":
            continue
        url = meta.get("zillow_url")
        region = meta.get("zillow_region_name")
        if not url or not region:
            print(f"  ⚠ {key}: липсва zillow_url или zillow_region_name — skip")
            continue
        specs.append({"key": key, "url": url, "region_name": region})

    if not specs:
        print("⚠ Няма Zillow серии в каталога. Добави entry с source=external, "
              "cache_file=data/zillow_cache.json, zillow_url, zillow_region_name.")
        return

    adapter = ZillowAdapter(base_dir=BASE_DIR)
    print(f"🌐 Download Zillow CSVs ({len(specs)} серии)...")
    results = adapter.fetch_many(specs, force=args.refresh)

    for spec in specs:
        key = spec["key"]
        history = results.get(key) or {}
        if not history:
            print(f"  ❌ {key}: 0 obs (fetch fail-на, виж logs)")
            continue
        dates = sorted(history.keys())
        latest = dates[-1]
        latest_val = history[latest]
        print(f"  ✅ {key}: {latest_val:,.0f} ({latest}) — {len(history)} obs от {dates[0]}")

    print(f"\n📦 Cache: {adapter.cache_path}")
    print("\n✅ Done!\n")


# ============================================================
# FETCH-HOUSING-SCRAPERS MODE (NAHB, MBA, NAR)
# ============================================================

def main_fetch_housing_scrapers(args) -> None:
    """Scrape NAHB HMI + MBA Applications + NAR PHSI press releases.

    ⚠ Phase B/architecture-first: parse_html() е stubbed (returns "pending").
    Архитектурата е готова — adapter classes, cache structure, run.py wiring
    и catalog entries. Реалната parse logic се добавя per source при нужда.

    Когато се имплементира parse:
      1. Override parse_html() в NAHBAdapter / MBAAdapter / NARAdapter
      2. Промени catalog entries от source="pending" → source="external"
         + cache_file="data/<source>_cache.json"
    """
    from sources.press_release_scraper import (
        NAHBAdapter, MBAAdapter, NARAdapter,
    )

    print("\n" + "═" * 60)
    print("  📊  Fetch housing scrapers (NAHB + MBA + NAR)  —  econ_v2")
    print("═" * 60)
    print(f"  {datetime.now().strftime('%A, %d %B %Y · %H:%M')}")
    print("═" * 60 + "\n")

    for AdapterCls in (NAHBAdapter, MBAAdapter, NARAdapter):
        adapter = AdapterCls(base_dir=BASE_DIR)
        print(f"🌐 {AdapterCls.SOURCE_NAME.upper()}: fetch_all (force={args.refresh})...")
        results = adapter.fetch_all(force=args.refresh)
        for key, parsed in results.items():
            quality = parsed.get("parse_quality") or "—"
            headline = parsed.get("headline")
            month = parsed.get("month") or "—"
            if quality == "ok" and headline is not None:
                marker = "✅"
                val_str = f"{headline}"
            elif quality == "pending":
                marker = "🔧"
                val_str = "(parse stub — implement parse_html)"
            else:
                marker = "⚠"
                val_str = f"quality={quality}"
            print(f"  {marker} {key}: {val_str} [{month}]")
        print(f"     cache: {adapter.cache_path}\n")

    print("✅ Done!\n")


# ============================================================
# IMPORT-BLOOMBERG MODE
# ============================================================

def main_import_bloomberg(args) -> None:
    """Import historical data от Bloomberg Excel/CSV файл в cache history{}.

    Универсален importer — работи за всички indicators с history-aware
    cache (ism_*, cb_*). Виж scripts/import_bloomberg.py за detail.
    """
    if not args.indicator:
        print("❌ --import-bloomberg изисква --indicator <KEY>")
        print("   Пример: python run.py --import-bloomberg --indicator cb_lei --file data.xlsx")
        sys.exit(1)
    if not args.file:
        print("❌ --import-bloomberg изисква --file <PATH>")
        sys.exit(1)

    from scripts.import_bloomberg import run_import

    print("\n" + "═" * 60)
    print("  📥  Import Bloomberg History  —  econ_v2")
    print("═" * 60)
    print(f"  {datetime.now().strftime('%A, %d %B %Y · %H:%M')}")
    print(f"  Indicator: {args.indicator}")
    print(f"  File: {args.file}")
    print("═" * 60 + "\n")

    try:
        run_import(args, BASE_DIR)
        print("\n✅ Done!\n")
    except Exception as e:
        print(f"\n❌ Import се провали: {e}\n")
        sys.exit(1)


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
    mode.add_argument(
        "--export-context",
        dest="export_context",
        action="store_true",
        help="Експортира briefing_context_YYYY-MM-DD.md за LLM (Claude) анализ. "
             "Markdown файл с пълен analytical state + per-series fact cards "
             "(5y range, percentile, последни readings, narrative_hint).",
    )
    mode.add_argument(
        "--fetch-ism",
        dest="fetch_ism",
        action="store_true",
        help="Scrape ISM Manufacturing + Services PMI през Firecrawl. "
             "Free-tier ограничение: само латест месец. Кеш 25 дни. "
             "Изисква FIRECRAWL_API_KEY в .env.",
    )
    mode.add_argument(
        "--fetch-confboard",
        dest="fetch_confboard",
        action="store_true",
        help="Scrape Conference Board LEI + Consumer Confidence през Firecrawl. "
             "Същата free-tier логика като --fetch-ism. "
             "Изисква FIRECRAWL_API_KEY в .env.",
    )
    mode.add_argument(
        "--fetch-zillow",
        dest="fetch_zillow",
        action="store_true",
        help="Download Zillow ZHVI и сродни public CSV-та (CC0 licensed). "
             "Без API key. Cache TTL 20 дни. Refresh policy: monthly.",
    )
    mode.add_argument(
        "--fetch-housing-scrapers",
        dest="fetch_housing_scrapers",
        action="store_true",
        help="Scrape NAHB HMI + MBA Applications + NAR PHSI press releases. "
             "Phase B архитектура (parse_html() stub-нат — needs per-source impl).",
    )
    mode.add_argument(
        "--import-bloomberg",
        dest="import_bloomberg",
        action="store_true",
        help="Import historical data от Bloomberg Excel/CSV в cache history{}. "
             "Изисква --indicator <KEY> + --file <PATH>. Работи за всички indicators: "
             "manufacturing_pmi, services_pmi, cb_lei, cb_cci.",
    )

    # Args за --import-bloomberg (не са в mutex group защото са sub-args)
    parser.add_argument(
        "--indicator",
        default=None,
        help="(--import-bloomberg) Indicator key за import.",
    )
    parser.add_argument(
        "--file",
        default=None,
        help="(--import-bloomberg) Path към Bloomberg export file (.xlsx / .csv).",
    )
    parser.add_argument(
        "--date-col",
        default=None,
        help="(--import-bloomberg) Custom date column header (auto-detect ако липсва).",
    )
    parser.add_argument(
        "--value-col",
        default=None,
        help="(--import-bloomberg) Custom value column header (auto-detect ако липсва).",
    )
    parser.add_argument(
        "--no-month-snap",
        action="store_true",
        help="(--import-bloomberg) НЕ нормализирай датите към 1-ви на месеца.",
    )
    parser.add_argument(
        "--source-label",
        default=None,
        help="(--import-bloomberg) Audit label (default 'bloomberg_csv').",
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
    elif args.export_context:
        main_export_context(args)
    elif args.fetch_ism:
        main_fetch_ism(args)
    elif args.fetch_confboard:
        main_fetch_confboard(args)
    elif args.fetch_zillow:
        main_fetch_zillow(args)
    elif args.fetch_housing_scrapers:
        main_fetch_housing_scrapers(args)
    elif args.import_bloomberg:
        main_import_bloomberg(args)
    elif args.briefing:
        main_briefing(args)
    elif args.status:
        main_status(args)
    else:
        main()
