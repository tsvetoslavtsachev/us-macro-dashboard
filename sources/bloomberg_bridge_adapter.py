"""
sources/bloomberg_bridge_adapter.py
====================================
Bridge adapter — чете parquet файлове от private vrm-data-archive репо.

ОТНОСНО ЛИЦЕНЗА:
  Bloomberg Terminal съдържание е под Bloomberg internal-use лиценз. Това
  означава:
    - Локално четене на private parquet архив за анализ → ОК
    - Republish на raw values в public dashboard → НЕ
    - Derived signals (composite scores, regime labels) → ОК (substantive transform)
  Виж vrm-data-archive/DESIGN.md за пълна license dискусия.

PUBLIC ВЕРСИЯ НА US/EU dashboards трябва:
  1. Да четат само series които имат `license_class: source_public` или
     `license_class: derived_only` (per manifest).
  2. Локалните dev runs могат да четат всичко (development иска raw).
  3. CI runs (GitHub Actions) трябва да минават --license-filter за skip
     на bloomberg_internal_use series когато публикуват HTML.

USAGE в catalog:
    "EA_INFL_SWAP_5Y": {
        "source": "bloomberg_bridge",
        "id": "EA_INFL_SWAP_5Y",
        "parquet_path": "../../vrm-data-archive/parquet/EA_INFL_SWAP_5Y.parquet",
        ...
    }

USAGE в pipeline:
    from sources.bloomberg_bridge_adapter import BloombergBridgeAdapter
    adapter = BloombergBridgeAdapter(base_dir=BASE_DIR)
    snapshot_extras = adapter.get_snapshot(SERIES_CATALOG, public_only=False)
    snapshot = fred_snapshot | external_snapshot | snapshot_extras
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class BloombergBridgeAdapter:
    """Чете Bloomberg-sourced parquet файлове от private архив."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).parent.parent

    def _resolve_path(self, parquet_path: str) -> Path:
        """Resolve relative path спрямо base_dir на текущото репо."""
        p = Path(parquet_path)
        if p.is_absolute():
            return p
        return (self.base_dir / parquet_path).resolve()

    def fetch(self, catalog_key: str, parquet_path: str) -> pd.Series:
        """Чете единичен parquet файл → pd.Series."""
        full = self._resolve_path(parquet_path)
        if not full.exists():
            logger.warning(
                f"{catalog_key}: parquet не съществува на {full}. "
                "Дали vrm-data-archive репо е mounted/cloned?"
            )
            return pd.Series(dtype=float)

        try:
            df = pd.read_parquet(full)
        except Exception as e:
            logger.error(f"{catalog_key}: parquet read failed — {e}")
            return pd.Series(dtype=float)

        if df.empty or "date" not in df.columns or "value" not in df.columns:
            logger.warning(f"{catalog_key}: parquet missing date/value columns или празен")
            return pd.Series(dtype=float)

        # За backtests използваме latest as_of per date (point-in-time logic
        # се прави извън adapter-а)
        df = df.sort_values(["date", "as_of"]).drop_duplicates(
            subset=["date"], keep="last"
        )
        s = pd.Series(df["value"].values, index=pd.to_datetime(df["date"]))
        s = s.sort_index()
        s.name = catalog_key
        return s

    def get_snapshot(
        self,
        catalog: dict[str, dict[str, Any]],
        public_only: bool = False,
    ) -> dict[str, pd.Series]:
        """Чете всички series с source='bloomberg_bridge' от catalog-а.

        Args:
            catalog: SERIES_CATALOG
            public_only: ако True, skip-ва series with license_class !=
                'source_public' or 'derived_only' (за CI/public renders).

        Returns:
            dict {catalog_key: pd.Series}
        """
        out: dict[str, pd.Series] = {}
        for key, meta in catalog.items():
            if meta.get("source") != "bloomberg_bridge":
                continue
            if public_only:
                lic = meta.get("license_class", "bloomberg_internal_use")
                if lic not in ("source_public", "derived_only"):
                    continue
            path = meta.get("parquet_path")
            if not path:
                logger.warning(f"{key}: липсва parquet_path в catalog meta")
                continue
            s = self.fetch(key, path)
            if not s.empty:
                out[key] = s
        return out

    def get_cache_status(self, catalog_key: str, parquet_path: str) -> dict[str, Any]:
        """FRED-compatible status за data_status integration."""
        s = self.fetch(catalog_key, parquet_path)
        if s.empty:
            return {
                "is_cached": False,
                "last_fetched": None,
                "last_observation": None,
                "n_observations": 0,
            }
        return {
            "is_cached": True,
            "last_fetched": None,  # parquet няма fetch timestamp концепция
            "last_observation": s.index.max().strftime("%Y-%m-%d"),
            "n_observations": len(s),
        }
