"""Hermetic DLMS application-data setup for every supported test entry point."""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path


TEST_DATA_ROOT = Path(tempfile.mkdtemp(prefix="dlms-test-suite-")).resolve()


def _cleanup_test_data_root():
    shutil.rmtree(TEST_DATA_ROOT, ignore_errors=True)


atexit.register(_cleanup_test_data_root)


def ensure_test_data_isolation():
    """Select a fresh temporary DLMS root before the application is imported."""
    app_module = sys.modules.get("app")
    if app_module is not None:
        selected_root = Path(getattr(app_module, "APP_DATA_DIR", "")).resolve()
        if selected_root != TEST_DATA_ROOT:
            raise RuntimeError(
                "DLMS app was imported before hermetic test-data isolation was established"
            )

    # Deliberately replace, rather than merely default, any inherited value. A
    # developer shell may point QUIZAPP_DATA_DIR at real data, and aggregate
    # tests must never trust that process-level setting.
    os.environ["QUIZAPP_DATA_DIR"] = str(TEST_DATA_ROOT)
    os.environ["DLMS_TEST_DATA_ROOT"] = str(TEST_DATA_ROOT)
    return TEST_DATA_ROOT


ensure_test_data_isolation()
