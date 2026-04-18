"""Catalog package — декларативен списък на сериите."""
from catalog.series import (
    SERIES_CATALOG,
    get_series,
    series_by_lens,
    series_by_peer_group,
    series_by_tag,
    all_series_ids,
    validate_catalog,
)

__all__ = [
    "SERIES_CATALOG",
    "get_series",
    "series_by_lens",
    "series_by_peer_group",
    "series_by_tag",
    "all_series_ids",
    "validate_catalog",
]
