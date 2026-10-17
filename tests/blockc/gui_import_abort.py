"""Abort the exact Qt-owned import worker at the Desktop marker."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    report = {}
    try:
        os.environ["DLMS_DESKTOP_AUTOMATED"] = "1"
        os.environ["DLMS_DESKTOP_TEST_ABORT_AT"] = "marker"
        report["started"] = q.window.adopt_backup(args.archive)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not q.window.failed_reason:
            q.delay(0.1)
        report["failure"] = q.window.failed_reason
        report["marker_preserved"] = (q.paths["root"] / "desktop-data-transition.json").is_file()
        report["backend_stopped"] = q.window.backend is None
        screenshot = q.paths["root"] / "blockc-import-interrupted.png"
        assert q.window.grab().save(str(screenshot))
        report["screenshot"] = str(screenshot)
        report["pass"] = bool(report["started"] and report["failure"]
            and "needs recovery" in report["failure"].lower()
            and report["marker_preserved"] and report["backend_stopped"])
    finally:
        (q.paths["root"] / "blockc-import-abort.json").write_text(json.dumps(report, indent=2) + "\n")
        q.close()
    print(json.dumps(report, indent=2))
    return 0 if report.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
