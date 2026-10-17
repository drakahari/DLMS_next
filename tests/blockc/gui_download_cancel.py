"""Cancel an actual Qt download and do not report a completed file."""
from __future__ import annotations

import argparse
import json
import time

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    report = {}
    try:
        q.go("/settings/backup")
        seen = []

        def cancel(request):
            seen.append(request.downloadFileName())
            request.cancel()

        q.window.profile.downloadRequested.connect(cancel)
        q.js("document.querySelector('form[action=\"/settings/backup/create\"] button').click(); true")
        deadline = time.monotonic() + 20
        while not seen and time.monotonic() < deadline:
            q.delay(0.1)
        q.delay(0.4)
        report["download_offered"] = bool(seen)
        report["native_states"] = q.window.download_results
        report["reported_completed"] = [str(path) for path in q.window.downloaded_files]
        report["message"] = q.window.statusBar().currentMessage()
        report["pass"] = (report["download_offered"] and len(report["native_states"]) == 1
                          and report["native_states"][0]["state"] == "cancelled"
                          and not report["reported_completed"] and "cancelled" in report["message"].lower())
    finally:
        (q.paths["root"] / "blockc-download-cancel.json").write_text(json.dumps(report, indent=2) + "\n")
        q.close()
    print(json.dumps(report, indent=2))
    return 0 if report.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
