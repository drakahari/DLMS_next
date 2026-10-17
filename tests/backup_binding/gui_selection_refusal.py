"""Actual Qt Settings selection refusals on fresh synthetic profiles."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time

from PySide6.QtWidgets import QFileDialog, QMessageBox

from tests.gate1.qt_checks import QtChecks
from tests.settings.gui_native_roundtrip import facts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--case", choices=("cancel", "changed", "stage-tamper", "drain-refusal"), required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, automated=True)
    source = q.paths["downloads"] / f"binding-{args.case}.zip"
    shutil.copyfile(args.source, source)
    before = facts(q.paths["backend"])
    old_picker, old_question, old_warning = (QFileDialog.getOpenFileName,
                                              QMessageBox.question, QMessageBox.warning)
    old_drain = q.window._drain_backend
    prompts = []
    warnings = []
    try:
        q.go("/settings/backup")
        QFileDialog.getOpenFileName = lambda *a, **kw: (str(source), "DLMS backups (*.zip)")
        QMessageBox.warning = lambda *a, **kw: warnings.append((a[1], a[2]))

        def confirm(*args_, **kwargs_):
            prompts.append((args_[1], args_[2]))
            if args.case == "cancel":
                return QMessageBox.StandardButton.No
            if args.case == "changed":
                current = source.stat()
                with source.open("r+b") as stream:
                    stream.seek(-1, 2)
                    byte = stream.read(1)
                    stream.seek(-1, 2)
                    stream.write(bytes([byte[0] ^ 1]))
                source.touch()
                # A preserved mtime and size still must not authorize a
                # different selected source after confirmation.
                import os
                os.utime(source, ns=(current.st_atime_ns, current.st_mtime_ns))
            elif args.case == "stage-tamper":
                staged = next((q.paths["root"] / "imports").glob("*.zip"))
                staged.chmod(0o600)
                with staged.open("r+b") as stream:
                    stream.seek(-1, 2)
                    byte = stream.read(1)
                    stream.seek(-1, 2)
                    stream.write(bytes([byte[0] ^ 1]))
            return QMessageBox.StandardButton.Yes

        QMessageBox.question = confirm
        if args.case == "drain-refusal":
            q.window._drain_backend = lambda: False
        q.window.settings_buttons["backup"].click()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and q.window.import_in_progress:
            q.delay(.05)
        assert not q.window.import_in_progress
        assert prompts, "Owner confirmation was not presented for the validated stage"
        assert facts(q.paths["backend"]) == before, "Refused selection altered destination data"
        assert q.window.import_worker is None
        receipts = list((q.paths["root"] / "imports").glob("*.json"))
        assert len(receipts) == 1
        state = json.loads(receipts[0].read_text())["state"]
        if args.case == "cancel":
            assert state == "canceled"
            assert q.window.settings_buttons["backup"].hasFocus()
            assert q.window.statusBar().currentMessage() == "Backup selection canceled; no import started."
        elif args.case == "changed":
            assert state == "canceled"
            assert any("changed" in title.lower() for title, _ in warnings)
            assert q.window.statusBar().currentMessage() == "Backup source changed; the private snapshot was not imported."
        else:
            if args.case == "stage-tamper":
                assert state == "ready"  # tampered evidence is retained, unusable
                assert "could not be used safely" in q.window.statusBar().currentMessage()
            else:
                assert state == "refused"
                assert "save could not be confirmed" in q.window.statusBar().currentMessage()
        result = {"pass": True, "case": args.case, "receipt_state": state,
                  "prompt_sha256_present": hashlib.sha256(args.source.read_bytes()).hexdigest() in prompts[0][1],
                  "destination_unchanged": True, "warnings": warnings}
        assert result["prompt_sha256_present"]
        (q.paths["root"] / f"binding-{args.case}-qt.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return 0
    finally:
        QFileDialog.getOpenFileName = old_picker
        QMessageBox.question = old_question
        QMessageBox.warning = old_warning
        q.window._drain_backend = old_drain
        q.close()


if __name__ == "__main__":
    raise SystemExit(main())
