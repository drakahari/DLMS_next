"""Real Qt menu confirms a disposable import before stopping the backend."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    archive = q.paths["root"] / "invalid-menu-backup.zip"
    archive.write_bytes(b"Synthetic invalid ZIP for the confirmation boundary\n")
    original_picker, original_question = QFileDialog.getOpenFileName, QMessageBox.question
    report = {}
    try:
        os.environ["DLMS_DESKTOP_AUTOMATED"] = "1"
        q.go("/settings/backup")
        assert q.window._settings_ready("backup")
        QFileDialog.getOpenFileName = lambda *a, **k: (str(archive), "DLMS backups (*.zip)")
        db = q.paths["backend"] / "results.db"
        baseline = hashlib.sha256(db.read_bytes()).hexdigest()
        asked = []

        def answer_no(*args, **kwargs):
            asked.append(str(args[2]))
            return QMessageBox.StandardButton.No

        QMessageBox.question = answer_no
        q.window.settings_buttons["backup"].click()
        report["confirmation_names_profile_and_archive"] = bool(asked and q.window.profile_name in asked[0] and str(archive) in asked[0])
        report["no_preserves_backend_and_data"] = (not q.window.import_in_progress and q.window.backend.poll() is None
                                                    and hashlib.sha256(db.read_bytes()).hexdigest() == baseline)
        QMessageBox.question = lambda *a, **k: QMessageBox.StandardButton.Yes
        pending_output = {"path": str(q.paths["downloads"] / "synthetic-pending.pdf"), "state": "in_progress"}
        q.window.pdf_results.append(pending_output)
        q.window.settings_buttons["backup"].click()
        report["output_blocks_import"] = (not q.window.import_in_progress and q.window.backend.poll() is None
                                          and "wait for the current" in q.window.statusBar().currentMessage().lower())
        os.environ.pop("DLMS_DESKTOP_AUTOMATED", None)
        QMessageBox.question = lambda *a, **k: QMessageBox.StandardButton.No
        q.window.close()
        report["output_close_deferred"] = q.window.isVisible() and q.window.backend.poll() is None
        os.environ["DLMS_DESKTOP_AUTOMATED"] = "1"
        q.window.pdf_results.remove(pending_output)
        QMessageBox.question = lambda *a, **k: QMessageBox.StandardButton.Yes
        q.window.settings_buttons["backup"].click()
        report["yes_starts_worker"] = q.window.import_in_progress
        deadline = time.monotonic() + 30
        while q.window.import_in_progress and time.monotonic() < deadline:
            q.delay(0.1)
        q.wait("location.pathname === '/' && document.readyState === 'complete'", 30)
        report["rejected_input_keeps_data"] = hashlib.sha256(db.read_bytes()).hexdigest() == baseline
        report["failure_message"] = q.window.statusBar().currentMessage()
        report["screenshot"] = str(q.screenshot("blockc-menu-rejected.png"))
        report["pass"] = (report["confirmation_names_profile_and_archive"] and report["no_preserves_backend_and_data"]
                          and report["output_blocks_import"] and report["output_close_deferred"]
                          and report["yes_starts_worker"] and report["rejected_input_keeps_data"]
                          and "rejected or interrupted" in report["failure_message"].lower())
    finally:
        QFileDialog.getOpenFileName, QMessageBox.question = original_picker, original_question
        (q.paths["root"] / "blockc-menu-confirmation.json").write_text(json.dumps(report, indent=2) + "\n")
        q.close()
    print(json.dumps(report, indent=2))
    return 0 if report.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
