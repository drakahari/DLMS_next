"""Exercise a paused import and rejected archive in the actual Qt window."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

from tests.gate1.qt_checks import QtChecks


def until(q, predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        q.delay(0.1)
    raise TimeoutError("Block C import state did not arrive")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    from PySide6.QtCore import QTimer
    report = {}
    try:
        os.environ["DLMS_DESKTOP_AUTOMATED"] = "1"
        os.environ["DLMS_DESKTOP_TEST_PAUSE_AT"] = "marker"
        origin = q.window.port
        beat = {"count": 0}
        timer = QTimer()
        timer.setInterval(60)
        timer.timeout.connect(lambda: beat.update(count=beat["count"] + 1))
        timer.start()
        report["started"] = q.window.adopt_backup(args.archive)
        until(q, lambda: (q.paths["root"] / "blockb-pause-evidence.json").exists())
        # The marker checkpoint is inside begin(), before live apply starts.
        until(q, lambda: "recording the dataset transition" in q.window.import_stage.text().lower())
        report["paused_stage"] = q.window.import_stage.text()
        report["duplicate_rejected"] = not q.window.adopt_backup(args.archive)
        q.window.close()
        report["close_deferred"] = q.window.isVisible() and q.window.import_in_progress
        q.delay(0.6)
        report["event_loop_ticks_while_worker_paused"] = beat["count"]
        picture = q.paths["root"] / "blockc-import-progress.png"
        assert q.window.grab().save(str(picture))
        report["progress_screenshot"] = str(picture)
        (q.paths["root"] / "blockb-pause-continue").write_text("release\n")
        until(q, lambda: not q.window.import_in_progress, 45)
        q.wait("location.pathname === '/' && document.readyState === 'complete'", 30)
        report["same_origin_after_import"] = q.window.port == origin
        report["restored_library"] = q.js("document.body.innerText.includes('Gate 1 Neutral Quiz')")
        timer.stop()
        os.environ.pop("DLMS_DESKTOP_TEST_PAUSE_AT", None)

        invalid = q.paths["root"] / "blockc-invalid.zip"
        invalid.write_bytes(b"invalid synthetic archive\n")
        report["invalid_started"] = q.window.adopt_backup(invalid)
        # The confirmed-byte contract now rejects malformed input before a
        # transition, rather than opening a restore worker to reject it.
        assert not q.window.import_in_progress
        report["failure_message"] = q.window.statusBar().currentMessage()
        report["library_after_rejection"] = q.js("document.body.innerText.includes('Gate 1 Neutral Quiz')")
        failure = q.paths["root"] / "blockc-import-rejected.png"
        assert q.window.grab().save(str(failure))
        report["failure_screenshot"] = str(failure)
        report["pass"] = bool(report["started"] and report["duplicate_rejected"] and
            report["close_deferred"] and report["event_loop_ticks_while_worker_paused"] >= 3 and
            report["same_origin_after_import"] and report["restored_library"] and
            not report["invalid_started"] and report["library_after_rejection"] and
            "rejected before confirmation" in report["failure_message"].lower())
    finally:
        (q.paths["root"] / "blockc-import-async.json").write_text(json.dumps(report, indent=2) + "\n")
        if q.window.import_in_progress:
            (q.paths["root"] / "blockb-pause-continue").write_text("release\n")
            until(q, lambda: not q.window.import_in_progress, 45)
        q.close()
    print(json.dumps(report, indent=2))
    return 0 if report.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
