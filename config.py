"""
econ_v2 — Configuration
========================
Единственото място, където пипаш настройки.
"""
import os

# ─── FRED API ────────────────────────────────────────────────────────────────
# Ключът се чете от env variable FRED_API_KEY.
# Локално: сложи `.env` файл в корена (виж `.env.example`) или export FRED_API_KEY=...
# Регистрация за ключ: https://fred.stlouisfed.org/docs/api/api_key.html
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")

if not FRED_API_KEY or not FIRECRAWL_API_KEY:
    # Fallback — опит за зареждане от .env файл в корена (без python-dotenv dep)
    from pathlib import Path
    _env = Path(__file__).resolve().parent / ".env"
    if _env.exists():
        for line in _env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key_s = key.strip()
            val_s = value.strip().strip('"').strip("'")
            if key_s == "FRED_API_KEY" and not FRED_API_KEY:
                FRED_API_KEY = val_s
            elif key_s == "FIRECRAWL_API_KEY" and not FIRECRAWL_API_KEY:
                FIRECRAWL_API_KEY = val_s

# ─── Исторически прозорец за percentile/analog изчисления ───────────────────
HISTORY_START = "2000-01-01"       # откога смятаме percentiles
ANALOG_HISTORY_START = "1970-01-01"  # откога търсим аналози (по-дълго)

# ─── Изходна папка ───────────────────────────────────────────────────────────
OUTPUT_DIR = "output"
