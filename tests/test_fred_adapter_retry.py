"""
tests/test_fred_adapter_retry.py
=================================
Тестове за retry layer-а на FredAdapter.

Целта: да потвърдим, че transient FRED 5xx errors се retry-ват
автоматично, а permanent errors (bad ID) fail-ват бързо.

Всички тестове mock-ват fredapi.Fred — няма реални HTTP заявки.
retry_backoff=[0, 0] за да избегнем realsleep в тестовете.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

# Добавяме econ_v2/ в Python path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from sources.fred_adapter import FredAdapter, _classify_fetch_error  # noqa: E402


# ============================================================
# _classify_fetch_error — pure function tests
# ============================================================

class TestClassifyError:
    """Класификаторът трябва да разпознава transient vs permanent."""

    def test_http_500_via_code_attribute(self):
        err = Exception("some message")
        err.code = 500
        assert _classify_fetch_error(err) == "transient"

    def test_http_503_via_code_attribute(self):
        err = Exception("unavailable")
        err.code = 503
        assert _classify_fetch_error(err) == "transient"

    def test_http_404_via_code_attribute(self):
        err = Exception("not found")
        err.code = 404
        assert _classify_fetch_error(err) == "permanent"

    def test_http_400_via_code_attribute(self):
        err = Exception("bad request")
        err.code = 400
        assert _classify_fetch_error(err) == "permanent"

    def test_transient_500_string(self):
        assert _classify_fetch_error(
            Exception("HTTP Error 500: Internal Server Error")
        ) == "transient"

    def test_transient_internal_server_error_string(self):
        assert _classify_fetch_error(
            Exception("fetch failed — Internal Server Error")
        ) == "transient"

    def test_transient_service_unavailable(self):
        assert _classify_fetch_error(
            Exception("HTTP 503: Service Unavailable")
        ) == "transient"

    def test_transient_timeout(self):
        assert _classify_fetch_error(
            Exception("urlopen error timed out")
        ) == "transient"

    def test_permanent_bad_request(self):
        # Точно каквото fredapi връща за грешен ID
        assert _classify_fetch_error(
            Exception("Bad Request.  The series does not exist.")
        ) == "permanent"

    def test_permanent_not_found(self):
        assert _classify_fetch_error(
            Exception("HTTP Error 404: Not Found")
        ) == "permanent"

    def test_unknown_defaults_to_transient(self):
        # Консервативна политика — retry вместо fail
        assert _classify_fetch_error(
            Exception("mysterious non-matching error text")
        ) == "transient"


# ============================================================
# Retry behavior — integration tests (с mock fredapi)
# ============================================================

@pytest.fixture
def adapter(tmp_path):
    """FredAdapter с празен cache и 2 бързи retry-а (no real sleep)."""
    return FredAdapter(
        api_key="fake-key",
        cache_path=tmp_path / "cache.json",
        base_dir=tmp_path,
        retry_backoff=[0, 0],  # 2 retries, без sleep
    )


@pytest.fixture
def sample_series():
    return pd.Series(
        [100.0, 101.5, 103.2],
        index=pd.to_datetime(["2025-01-01", "2025-02-01", "2025-03-01"]),
    )


class TestRetrySuccess:
    """Ако FRED върне 5xx, но по-късно се вдигне — трябва да мине."""

    def test_succeeds_on_first_try(self, adapter, sample_series):
        mock_fred = MagicMock()
        mock_fred.get_series.return_value = sample_series
        adapter._fred_client = mock_fred

        result = adapter.fetch("TEST", "TEST_ID", "monthly", force=True)

        assert not result.empty
        assert len(result) == 3
        assert mock_fred.get_series.call_count == 1

    def test_succeeds_after_one_transient_500(self, adapter, sample_series):
        mock_fred = MagicMock()
        mock_fred.get_series.side_effect = [
            Exception("HTTP Error 500: Internal Server Error"),
            sample_series,
        ]
        adapter._fred_client = mock_fred

        result = adapter.fetch("TEST", "TEST_ID", "monthly", force=True)

        assert not result.empty
        assert len(result) == 3
        assert mock_fred.get_series.call_count == 2  # 1 fail + 1 success

    def test_succeeds_after_two_transient_500s(self, adapter, sample_series):
        """Точно симулира днешния инцидент с GDPC1 / COMP_GDP_SHARE."""
        mock_fred = MagicMock()
        mock_fred.get_series.side_effect = [
            Exception("Internal Server Error"),
            Exception("Internal Server Error"),
            sample_series,
        ]
        adapter._fred_client = mock_fred

        result = adapter.fetch("TEST", "TEST_ID", "monthly", force=True)

        assert not result.empty
        assert mock_fred.get_series.call_count == 3  # 2 fails + 1 success


class TestRetryFailFast:
    """Permanent errors (грешен ID) не трябва да retry-ват."""

    def test_bad_request_no_retry(self, adapter):
        mock_fred = MagicMock()
        mock_fred.get_series.side_effect = Exception(
            "Bad Request.  The series does not exist."
        )
        adapter._fred_client = mock_fred

        result = adapter.fetch("BAD", "NONEXISTENT", "monthly", force=True)

        # Fall back към празен cache (няма данни)
        assert result.empty
        # КРИТИЧНО: само 1 опит, без retry
        assert mock_fred.get_series.call_count == 1

    def test_404_no_retry(self, adapter):
        err = Exception("not found")
        err.code = 404
        mock_fred = MagicMock()
        mock_fred.get_series.side_effect = err
        adapter._fred_client = mock_fred

        result = adapter.fetch("BAD", "NONEXISTENT", "monthly", force=True)

        assert result.empty
        assert mock_fred.get_series.call_count == 1


class TestRetryExhausted:
    """Ако всички retries се изчерпят, fall-back към cache."""

    def test_exhausts_retries_then_falls_back_to_empty_cache(self, adapter):
        mock_fred = MagicMock()
        mock_fred.get_series.side_effect = Exception("Internal Server Error")
        adapter._fred_client = mock_fred

        result = adapter.fetch("TEST", "TEST_ID", "monthly", force=True)

        assert result.empty  # no cache налични
        # initial + 2 retries = 3 общо опита
        assert mock_fred.get_series.call_count == 3

    def test_exhausts_retries_falls_back_to_populated_cache(
        self, adapter, sample_series
    ):
        """Ако има stale cache, fall-back го връща вместо празна серия."""
        # Pre-populate cache
        adapter._store_in_cache("TEST", "TEST_ID", sample_series)

        mock_fred = MagicMock()
        mock_fred.get_series.side_effect = Exception("Internal Server Error")
        adapter._fred_client = mock_fred

        result = adapter.fetch("TEST", "TEST_ID", "monthly", force=True)

        # Fresh fetch пада → retry → retry → fall-back към cache
        assert not result.empty
        assert len(result) == 3
        assert mock_fred.get_series.call_count == 3
