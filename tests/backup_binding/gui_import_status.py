"""Actual Qt import status lifecycle on an isolated synthetic profile."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import time

from PySide6.QtWidgets import QFileDialog, QMessageBox

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--expect-stale", action="store_true")
    parser.add_argument("--picker-cancel", action="store_true")
    parser.add_argument("--invalid-path", action="store_true")
    args = parser.parse_args()
    q = QtChecks(args.profile, automated=True)
    source = q.paths["downloads"] / "status-neutral.zip"
    shutil.copyfile(args.fixture, source)
    old_picker, old_question, old_warning = (QFileDialog.getOpenFileName,
                                            QMessageBox.question, QMessageBox.warning)
    try:
        q.go("/settings/backup")
        QFileDialog.getOpenFileName = lambda *a, **kw: (
            ("", "") if args.picker_cancel else
            ("/tmp/not-a-disposable-backup.zip", "DLMS backups (*.zip)") if args.invalid_path else
            (str(source), "DLMS backups (*.zip)"))
        QMessageBox.question = lambda *a, **kw: QMessageBox.StandardButton.Yes
        QMessageBox.warning = lambda *a, **kw: None
        q.window.settings_buttons["backup"].click()
        if args.invalid_path:
            assert not q.window.import_in_progress
            assert q.window.statusBar().currentMessage() == "Backup path is not eligible; no import started. Choose an owned local ZIP, without symbolic links."
            return 0
        if args.picker_cancel:
            assert not q.window.import_in_progress
            assert q.window.statusBar().currentMessage() == "Backup file selection canceled; no import started."
            assert q.window.settings_buttons["backup"].hasFocus()
            return 0
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and q.window.import_in_progress:
            q.delay(.15)
        assert not q.window.import_in_progress
        q.wait("location.pathname === '/' && document.readyState === 'complete'", 30)
        q.go("/library")
        assert q.js("document.body.innerText.includes('Gate 1 Neutral Quiz')")
        q.go("/history")
        status = q.window.statusBar().currentMessage()
        result = {"profile": args.profile, "library_loaded": True,
                  "history_loaded": True, "status": status}
        if args.expect_stale:
            assert status == "Copying and validating a private backup snapshot before confirmation…"
        else:
            assert "Backup committed" in status and args.profile in status
            serial = q.window._import_status_serial
            q.window._import_reopen_status = (serial - 1, "Old import is reopening")
            q.window.statusBar().showMessage("Newer operation is active")
            q.window._settings_page_loaded(True, q.window.view)
            assert q.window.statusBar().currentMessage() == "Newer operation is active"
            assert q.window._import_reopen_status is None
            q.window._import_reopen_status = (serial, "Old disposed view is reopening")
            q.window._settings_page_loaded(True, object())
            assert q.window._import_reopen_status == (serial, "Old disposed view is reopening")
            q.window._import_reopen_status = None
            q.window._import_reopen_status = (serial, "Pending import status")
            q.window.failed_reason = "Simulated later backend failure"
            q.window.statusBar().showMessage("Pending import status")
            q.window._settings_page_loaded(True, q.window.view)
            assert q.window.statusBar().currentMessage() == "Pending import status"
            assert q.window._import_reopen_status is None
            q.window.failed_reason = None
        (q.paths["root"] / "import-status-qt.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return 0
    finally:
        QFileDialog.getOpenFileName, QMessageBox.question, QMessageBox.warning = (
            old_picker, old_question, old_warning)
        q.close()


if __name__ == "__main__":
    raise SystemExit(main())
