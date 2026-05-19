"""
scripts/import_bloomberg.py
===========================
Generic Bloomberg history importer за external (non-FRED) indicators.

Чете Excel/CSV file (Bloomberg export или manual prep), извлича (date, value)
двойки, нормализира датите до първи ден на месеца, и merge-ва в history{}
полето на съответния adapter cache.

Работи за всеки adapter с история-aware cache shape:
  - sources.ism_adapter.ISMAdapter (manufacturing_pmi, services_pmi)
  - sources.confboard_adapter.ConfBoardAdapter (cb_lei, cb_cci)

Файлов формат (минимален contract):
  - Първи ред = headers
  - Една колона с дата (auto-detect, или --date-col NAME)
  - Една колона със стойност (auto-detect, или --value-col NAME)
  - Допълнителни колони се игнорират
  - Bloomberg style "PX_DATE" + "PX_LAST" — auto-detect работи

Дата нормализация:
  - Bloomberg често дава end-of-month или release date.
  - За monthly indicators normalize-ваме към YYYY-MM-01.
  - --no-month-snap изключва нормализацията (запазва оригиналната дата).

Употреба от run.py:
  python run.py --import-bloomberg --indicator cb_lei --file lei_history.xlsx
  python run.py --import-bloomberg --indicator cb_cci --file cci.csv --date-col PX_DATE --value-col PX_LAST
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ============================================================
# Indicator → Adapter routing
# ============================================================

ISM_INDICATORS = {"manufacturing_pmi", "services_pmi"}
CB_INDICATORS = {"cb_lei", "cb_cci"}

ALL_INDICATORS = ISM_INDICATORS | CB_INDICATORS


def _get_adapter(indicator_key: str, base_dir: Path):
    """Връща инстанция на правилния adapter за този indicator.

    Адаптерът се инициализира с празен API key — fetch ще fail-не, но
    add_history_observations() и save_cache() работят (нямат network нужда).
    """
    if indicator_key in ISM_INDICATORS:
        from sources.ism_adapter import ISMAdapter
        return ISMAdapter(api_key="", base_dir=base_dir)
    if indicator_key in CB_INDICATORS:
        from sources.confboard_adapter import ConfBoardAdapter
        return ConfBoardAdapter(api_key="", base_dir=base_dir)
    raise ValueError(
        f"Unknown indicator '{indicator_key}'. "
        f"Available: {sorted(ALL_INDICATORS)}"
    )


# ============================================================
# File reading — pandas-based за лесна Excel/CSV универсалност
# ============================================================

def _read_file(path: Path):
    """Чете CSV или XLSX file, връща pandas DataFrame."""
    import pandas as pd  # lazy import
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls", ".xlsm"):
        return pd.read_excel(path, sheet_name=0)
    if suffix in (".csv", ".tsv"):
        sep = "\t" if suffix == ".tsv" else ","
        return pd.read_csv(path, sep=sep)
    raise ValueError(f"Unsupported file type: {suffix}. Use .xlsx/.xls/.xlsm or .csv/.tsv.")


# Bloomberg често ползва: PX_DATE, PX_LAST, BB_DATE, Date, DATE, Value, Last
_DATE_HEADER_CANDIDATES = (
    "PX_DATE", "Date", "DATE", "date", "Px_Date", "BBg_Date",
    "Period", "TIMESTAMP", "Timestamp", "MonthlyDate",
)
_VALUE_HEADER_CANDIDATES = (
    "PX_LAST", "Last Price", "Last", "Value", "VALUE", "value",
    "Px_Last", "Close", "CLOSE", "Index Level", "Level",
)


def _auto_detect_columns(df, date_col: Optional[str], value_col: Optional[str]) -> tuple[str, str]:
    """Намира date + value колоните. Раises ValueError ако не може."""
    import pandas as pd

    cols = list(df.columns)

    # Date column
    if date_col:
        if date_col not in cols:
            raise ValueError(f"--date-col '{date_col}' не съществува. Колони: {cols}")
        date_c = date_col
    else:
        date_c = None
        # 1. Exact match срещу candidate list
        for cand in _DATE_HEADER_CANDIDATES:
            if cand in cols:
                date_c = cand
                break
        # 2. Опит за auto-detect по dtype (datetime-like)
        if date_c is None:
            for c in cols:
                try:
                    pd.to_datetime(df[c], errors="raise")
                    date_c = c
                    break
                except (ValueError, TypeError):
                    continue
        if date_c is None:
            raise ValueError(
                f"Не мога да открия date column. Колони: {cols}. "
                f"Подай --date-col NAME."
            )

    # Value column
    if value_col:
        if value_col not in cols:
            raise ValueError(f"--value-col '{value_col}' не съществува. Колони: {cols}")
        value_c = value_col
    else:
        value_c = None
        # 1. Exact match
        for cand in _VALUE_HEADER_CANDIDATES:
            if cand in cols:
                value_c = cand
                break
        # 2. Първата numeric колона различна от date_c
        if value_c is None:
            for c in cols:
                if c == date_c:
                    continue
                if pd.api.types.is_numeric_dtype(df[c]):
                    value_c = c
                    break
        if value_c is None:
            raise ValueError(
                f"Не мога да открия value column. Колони: {cols}. "
                f"Подай --value-col NAME."
            )

    return date_c, value_c


def _normalize_to_month_start(date_value) -> Optional[str]:
    """Конвертира pandas Timestamp / str / date към YYYY-MM-01."""
    import pandas as pd
    if pd.isna(date_value):
        return None
    try:
        ts = pd.to_datetime(date_value)
    except (ValueError, TypeError):
        return None
    return f"{ts.year:04d}-{ts.month:02d}-01"


def _extract_observations(
    df, date_col: str, value_col: str, month_snap: bool
) -> dict[str, float]:
    """Извлича {date_iso: value} от DataFrame."""
    import pandas as pd
    obs: dict[str, float] = {}
    skipped = 0
    for _, row in df.iterrows():
        date_val = row[date_col]
        value_val = row[value_col]
        if pd.isna(date_val) or pd.isna(value_val):
            skipped += 1
            continue
        if month_snap:
            iso = _normalize_to_month_start(date_val)
        else:
            try:
                ts = pd.to_datetime(date_val)
                iso = ts.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                skipped += 1
                continue
        if iso is None:
            skipped += 1
            continue
        try:
            obs[iso] = float(value_val)
        except (ValueError, TypeError):
            skipped += 1
            continue
    if skipped:
        logger.warning(f"Пропуснати {skipped} реда (празни / нечисти стойности)")
    return obs


# ============================================================
# Entry point
# ============================================================

def run_import(args, base_dir: Path) -> int:
    """Изпълнява import workflow-а. Връща брой merged observations.

    Дизайн: всички print-ове отиват към stdout, грешки изпадат с raise.
    Caller-ът (run.py) форматира banner + summary.
    """
    file_path = Path(args.file).resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"Файлът не съществува: {file_path}")

    if args.indicator not in ALL_INDICATORS:
        raise ValueError(
            f"Unknown indicator '{args.indicator}'. Available: {sorted(ALL_INDICATORS)}"
        )

    print(f"📂 Чета {file_path.name}...")
    df = _read_file(file_path)
    print(f"   {len(df)} реда, колони: {list(df.columns)}")

    date_col, value_col = _auto_detect_columns(df, args.date_col, args.value_col)
    print(f"📅 Date column: '{date_col}'  ·  📊 Value column: '{value_col}'")

    obs = _extract_observations(df, date_col, value_col, month_snap=not args.no_month_snap)
    if not obs:
        raise RuntimeError(
            f"Нула observations извлечени от {file_path.name}. "
            f"Провери колоните и форматите."
        )
    print(f"✨ Извлечени {len(obs)} observations (диапазон: "
          f"{min(obs.keys())} → {max(obs.keys())})")

    adapter = _get_adapter(args.indicator, base_dir)
    n_changes = adapter.add_history_observations(
        args.indicator,
        obs,
        source_label=args.source_label or "bloomberg_csv",
    )
    adapter.save_cache()

    cache_path = adapter.cache_path
    total_history = len(adapter._cache[args.indicator].get("history", {}))
    print(f"💾 {n_changes} нови/updated observations merged в {cache_path.name}")
    print(f"   Total history: {total_history} observations за {args.indicator}")
    return n_changes


def main(base_dir: Optional[Path] = None) -> int:
    """Standalone CLI entry point — позволява пускане директно без run.py."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(
        description="Import Bloomberg historical data в indicator cache.",
    )
    parser.add_argument("--indicator", required=True, choices=sorted(ALL_INDICATORS))
    parser.add_argument("--file", required=True, help="Path към Excel/CSV file")
    parser.add_argument("--date-col", default=None, help="Custom date column (auto-detect ако липсва)")
    parser.add_argument("--value-col", default=None, help="Custom value column (auto-detect ако липсва)")
    parser.add_argument(
        "--no-month-snap",
        action="store_true",
        help="НЕ нормализирай датите към първи ден на месеца (запази оригиналите).",
    )
    parser.add_argument(
        "--source-label",
        default=None,
        help="Етикет за audit trail (по default 'bloomberg_csv').",
    )
    args = parser.parse_args()

    if base_dir is None:
        base_dir = Path(__file__).resolve().parent.parent

    try:
        run_import(args, base_dir)
        return 0
    except Exception as e:
        logger.error(f"Import се провали: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
