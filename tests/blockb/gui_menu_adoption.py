"""Select a copied synthetic archive through the owned Qt import workflow."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import traceback
from PySide6.QtWidgets import QFileDialog, QMessageBox

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--pause-at", default=None)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    old_picker, old_question = QFileDialog.getOpenFileName, QMessageBox.question
    os.environ["DLMS_DESKTOP_AUTOMATED"] = "1"
    if args.pause_at:
        os.environ["DLMS_DESKTOP_TEST_PAUSE_AT"] = args.pause_at
        (q.paths["root"] / "blockb-menu-driver.pid").write_text(str(os.getpid()))
    result = {"profile": args.profile, "archive": str(args.archive)}
    try:
        q.go("/settings/backup")
        result["settings_action_visible"] = (q.window._settings_ready("backup")
            and q.window.settings_buttons["backup"].isVisible())
        QFileDialog.getOpenFileName = lambda *a, **kw: (str(args.archive), "DLMS backups (*.zip)")
        QMessageBox.question = lambda *a, **kw: QMessageBox.StandardButton.Yes
        q.window.settings_buttons["backup"].click()
        result["adopt_started"] = q.window.import_in_progress
        q.wait("location.pathname === '/' && document.readyState === 'complete'", 30)
        q.go("/library")
        result["restored_library"] = q.js("document.body.innerText.includes('Gate 1 Neutral Quiz')")
        result["screenshot"] = str(q.screenshot("blockb-menu-restored-library.png"))
        result["status"] = "pass" if result["settings_action_visible"] and result["adopt_started"] and result["restored_library"] else "fail"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        QFileDialog.getOpenFileName, QMessageBox.question = old_picker, old_question
        (q.paths["root"] / "blockb-menu-adoption.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
