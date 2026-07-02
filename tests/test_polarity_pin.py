"""
tests/test_polarity_pin.py
===========================
Полярностен GOLDEN PIN (REVIEW-03 т.0.4, P3-fix-B, генериран 2026-07-02).

Полярността на всяка серия е изрично обсъдено решение — една тихо обърната
полярност обръща леща, без нито един тест да падне (инцидентът с housing
сериите, поправен 2026-06-05, мина незабелязан точно затова; REVIEW-03 R.6).
Този тест пинва ПЪЛНИЯ полярностен вектор.

При ЛЕГИТИМНА промяна на полярност: редактирай двата файла ЗАЕДНО (дефиницията
и този golden) в един commit, с обяснение защо посоката се сменя.
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from catalog.polarity import (  # noqa: E402
    POLARITY,
    POLARITY_BY_LENS,
    PEER_GROUP_WEIGHT,
    U_BAND,
)
from catalog.series import SERIES_CATALOG  # noqa: E402


def _diff(actual: dict, expected: dict) -> dict:
    """Кои ключове се различават — за четим failure."""
    keys = set(actual) | set(expected)
    return {
        k: {"expected": expected.get(k, "<ЛИПСВА>"), "actual": actual.get(k, "<ЛИПСВА>")}
        for k in sorted(keys, key=str)
        if actual.get(k, "<ЛИПСВА>") != expected.get(k, "<ЛИПСВА>")
    }


EXPECTED_POLARITY = {'AHE': 1,
 'AWHAETP': 1,
 'AWHMAN': 1,
 'AWOTMAN': 1,
 'BREAKEVEN_10Y': ('U', 'target', 2.0),
 'BREAKEVEN_5Y5Y': ('U', 'target', 2.0),
 'CB_CCI': 1,
 'CB_LEI': 1,
 'CCSA': -1,
 'CC_DELINQUENCY': -1,
 'CFNAI': 1,
 'CFNAIMA3': 1,
 'CIVPART': 1,
 'COMPUTSA': 1,
 'COMP_DESIGN': 1,
 'COMP_GDP_SHARE': 1,
 'CPIAUCSL': ('U', 'target', 2.0),
 'CPILFESL': ('U', 'target', 2.0),
 'CPI_GOODS': ('U', 'target', 2.0),
 'CPI_SERVICES': ('U', 'target', 2.0),
 'CPI_SHELTER': ('U', 'target', 2.0),
 'CSUSHPISA': 1,
 'C_AND_I_LOANS': 1,
 'DGORDER': 1,
 'ECIWAG': 1,
 'EMRATIO': 1,
 'EXHOSLUSM495S': 1,
 'FED_BS': 1,
 'FED_FUNDS': -1,
 'FIXHAI': 1,
 'GDPC1': 1,
 'HOSINVUSM495N': ('U', 'self'),
 'HOUST': 1,
 'HPIPONM226S': 1,
 'HSN1F': 1,
 'HY_OAS': -1,
 'IC4WSA': -1,
 'ICSA': -1,
 'IG_OAS': -1,
 'INDPRO': 1,
 'ISM_MFG_PMI': 1,
 'ISM_SVCS_PMI': 1,
 'JTSJOL': 1,
 'JTSLDL': -1,
 'JTSQUR': 1,
 'LABOR_SHARE_NBS': 1,
 'M2': 1,
 'MANEMP': 1,
 'MBA_PURCHASE_IDX': 1,
 'MBA_REFINANCE_IDX': 1,
 'MEDIAN_CPI': ('U', 'target', 2.0),
 'MICH_INFL_1Y': ('U', 'target', 2.0),
 'MORTGAGE15US': -1,
 'MORTGAGE30US': -1,
 'MSACSR': -1,
 'NAHB_HMI': 1,
 'NAR_PHSI': 1,
 'NFCI': -1,
 'PAYEMS': 1,
 'PCEC96': 1,
 'PCEPI': ('U', 'target', 2.0),
 'PCEPILFE': ('U', 'target', 2.0),
 'PERMIT': 1,
 'PHILLY_FED': 1,
 'PPICORE': ('U', 'target', 2.0),
 'PPIFIS': ('U', 'target', 2.0),
 'PROF_TECH_SERV': 1,
 'PSAVERT': ('U', 'self'),
 'RSXFS': 1,
 'SOFR': -1,
 'SOFT_PUB': 1,
 'SPCS20RSA': 1,
 'STICKY_CPI': ('U', 'target', 2.0),
 'STLFSI': -1,
 'TEMPHELPS': 1,
 'TLRESCONS': 1,
 'TOTAL_RESERVES': 1,
 'TRIMMED_MEAN_CPI': ('U', 'target', 2.0),
 'TRUCK_EMP': 1,
 'U6RATE': -1,
 'UEMPMEAN': -1,
 'UMCSENT': 1,
 'UNRATE': -1,
 'USCONS': 1,
 'USINFO': 1,
 'USPRIV': 1,
 'USSTHPI': 1,
 'UST_10Y': -1,
 'UST_2Y': -1,
 'US_PMI_COMPOSITE': 1,
 'US_PMI_MFG': 1,
 'US_PMI_SVCS': 1,
 'US_SOFR_OIS_1Y': -1,
 'US_SOFR_OIS_2Y': -1,
 'US_SOFR_OIS_3M': -1,
 'US_SOFR_OIS_6M': -1,
 'YC_10Y2Y': 1,
 'YC_10Y3M': 1}

EXPECTED_POLARITY_BY_LENS = {('inflation', 'AHE'): ('U', 'self'),
 ('inflation', 'COMP_GDP_SHARE'): ('U', 'self'),
 ('inflation', 'ECIWAG'): ('U', 'self'),
 ('inflation', 'LABOR_SHARE_NBS'): ('U', 'self')}

EXPECTED_PEER_GROUP_WEIGHT = {'labor_share': 0.5, 'money_supply': 0.5}

EXPECTED_U_BAND = 1.0


class TestPolarityPin:
    def test_polarity_vector_pinned(self):
        d = _diff(POLARITY, EXPECTED_POLARITY)
        assert not d, f"ПОЛЯРНОСТЕН ДРИФТ (изрична редакция на golden-а нужна): {d}"

    def test_polarity_overrides_pinned(self):
        d = _diff(POLARITY_BY_LENS, EXPECTED_POLARITY_BY_LENS)
        assert not d, f"Override дрифт: {d}"

    def test_peer_group_weights_pinned(self):
        d = _diff(PEER_GROUP_WEIGHT, EXPECTED_PEER_GROUP_WEIGHT)
        assert not d, f"Peer-group тегловен дрифт: {d}"

    def test_u_band_pinned(self):
        assert U_BAND == EXPECTED_U_BAND

    def test_every_catalog_series_has_explicit_polarity(self):
        missing = sorted(set(SERIES_CATALOG) - set(POLARITY))
        assert not missing, f"Серии без изрична полярност (би паднало към default +1): {missing}"
