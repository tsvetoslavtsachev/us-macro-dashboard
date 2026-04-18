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
if not FRED_API_KEY:
    # Fallback — опит за зареждане от .env файл в корена (без python-dotenv dep)
    from pathlib import Path
    _env = Path(__file__).resolve().parent / ".env"
    if _env.exists():
        for line in _env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "FRED_API_KEY":
                FRED_API_KEY = value.strip().strip('"').strip("'")
                break

# ─── Кеш (часове преди следващ FRED pull) ───────────────────────────────────
CACHE_TTL_HOURS = 12

# ─── Исторически прозорец за percentile/analog изчисления ───────────────────
HISTORY_START = "2000-01-01"       # откога смятаме percentiles
ANALOG_HISTORY_START = "1970-01-01"  # откога търсим аналози (по-дълго)

# ─── Модулни тегла за Composite Macro Score ──────────────────────────────────
MODULE_WEIGHTS = {
    "labor":     0.20,
    "inflation": 0.20,
    "growth":    0.20,
    "credit":    0.15,
    "housing":   0.10,
    "fed":       0.10,
    "consumer":  0.05,
}

# ─── Macro режими (composite score → label) ──────────────────────────────────
MACRO_REGIMES = [
    (80, "EXPANSIONARY",  "#00c853"),
    (65, "HEALTHY",       "#69f0ae"),
    (50, "MIXED",         "#ffd600"),
    (35, "DETERIORATING", "#ff6d00"),
    (0,  "RECESSIONARY",  "#d50000"),
]

# ─── Изходна папка ───────────────────────────────────────────────────────────
OUTPUT_DIR = "output"
