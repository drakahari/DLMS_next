"""Pytest bootstrap that establishes hermetic DLMS data before collection."""

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
