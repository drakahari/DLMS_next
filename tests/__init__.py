"""DLMS test package bootstrap."""

from tests._isolation import TEST_DATA_ROOT, ensure_test_data_isolation


ensure_test_data_isolation()

__all__ = ["TEST_DATA_ROOT", "ensure_test_data_isolation"]
