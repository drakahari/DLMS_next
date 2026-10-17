"""Change the original source after confirmation; import the frozen bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

from PySide6.QtWidgets import QFileDialog, QMessageBox

from tests.gate1.qt_checks import QtChecks
from tests.settings.gui_native_roundtrip import facts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--source-profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, automated=True)
    source_evidence = json.loads((q.paths["root"].parent / args.source_profile /
                                  "native-settings-export.json").read_text())
    original = Path(source_evidence["archive"])
    copy = q.paths["downloads"] / "selected-synthetic.zip"
    shutil.copyfile(original, copy)
    expected_digest = hashlib.sha256(copy.read_bytes()).hexdigest()
    old_picker, old_question, old_adopt = (QFileDialog.getOpenFileName,
                                           QMessageBox.question, q.window.adopt_backup)
    changed = []
    try:
        q.go("/settings/backup")
        QFileDialog.getOpenFileName = lambda *_a, **_kw: (str(copy), "DLMS backups (*.zip)")
        QMessageBox.question = lambda *_a, **_kw: QMessageBox.StandardButton.Yes
        def change_source_then_adopt(selection):
            replacement = copy.with_name("new-source.zip")
            replacement.write_bytes(b"a different postconfirmation source file")
            os.replace(replacement, copy)
            changed.append(True)
            return old_adopt(selection)
        q.window.adopt_backup = change_source_then_adopt
        q.window.settings_buttons["backup"].click()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and q.window.import_in_progress:
            q.delay(.1)
        assert changed and not q.window.import_in_progress
        q.wait("location.pathname === '/' && document.readyState === 'complete'", 30)
        assert facts(q.paths["backend"]) == source_evidence["facts"]
        receipt_path = next((q.paths["root"] / "imports").glob("*.json"))
        receipt = json.loads(receipt_path.read_text())
        assert receipt["state"] == "completed" and receipt["sha256"] == expected_digest
        assert hashlib.sha256(copy.read_bytes()).hexdigest() != expected_digest
        result = {"pass": True, "source_changed_after_final_check": True,
                  "confirmed_sha256": expected_digest, "receipt_state": receipt["state"],
                  "imported_records_and_assets_equal_frozen_source": True}
        (q.paths["root"] / "binding-after-confirm-qt.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return 0
    finally:
        QFileDialog.getOpenFileName, QMessageBox.question = old_picker, old_question
        q.window.adopt_backup = old_adopt
        q.close()


if __name__ == "__main__":
    raise SystemExit(main())
