"""is_rate → дисплей „%" на лихва/процент серии (item H1 / parity с EU)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from export.quick_briefing import _fmt_reading
from catalog.series import SERIES_CATALOG as C


def test_rate_level_reading_gets_percent():
    # лихва-ниво стойност → „5.23%" (без знак — нивото е процент)
    assert _fmt_reading(5.23, is_pct=False, is_rate=True) == "5.23%"
    assert _fmt_reading(4.45, is_pct=False, is_rate=True) == "4.45%"


def test_pct_change_reading_unchanged_signed():
    # %-темп → „+0.7%" (със знак), непроменено
    assert _fmt_reading(0.66, is_pct=True) == "+0.7%"


def test_index_reading_stays_bare():
    # индекс/бройка → без „%"
    assert _fmt_reading(331.0, is_pct=False, is_rate=False) == "331.00"


def test_is_rate_derivation():
    # %-темпове → True; курирани лихва-ниво → True; индекси/бройки → False
    assert C["TRIMMED_MEAN_CPI"]["is_rate"] is True   # инфл. темп (H1)
    assert C["UNRATE"]["is_rate"] is True              # лихва-ниво
    assert C["UST_10Y"]["is_rate"] is True
    assert C["CSUSHPISA"]["is_rate"] is True           # yoy_pct
    assert C["UMCSENT"]["is_rate"] is False            # индекс
    assert C["MSACSR"]["is_rate"] is False             # месеци, не %
    assert C["UEMPMEAN"]["is_rate"] is False           # седмици, не %
