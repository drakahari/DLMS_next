"""Normal-mode Qt menu and Desktop-only Settings boundary copy."""
from __future__ import annotations

import argparse
import hashlib
import json
import traceback

from PySide6.QtWidgets import QMessageBox, QInputDialog

from desktop.maintenance import SCOPES, read_marker
from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    a = p.parse_args()
    q = QtChecks(a.profile)
    out = {"profile": a.profile}
    old_question = QMessageBox.question
    old_get_text = QInputDialog.getText
    try:
        q.go("/settings/reset-remove")
        out["settings_action_visible"] = q.window._settings_ready("reset-remove") and q.window.settings_panel.isVisible()
        out["scopes"] = sorted(k for k in q.window.settings_buttons
                               if k not in {"backup", "create_backup", "refresh_storage", "remove"})
        out["banner"] = q.js("document.getElementById('desktopResetBoundary')?.innerText")
        out["removal_tombstone_wording"] = q.js("document.body.innerText.includes('Desktop retains an external removal record and will refuse to reopen this profile name')")
        out["legacy_disabled"] = q.js("[...document.querySelectorAll('#clearDBBtn,.resetAction,#removeAllDlmsDataBtn')].every(x=>x.disabled)")
        out["screenshot"] = str(q.screenshot("completion-maintenance-menu.png", width=1100, height=800))
        database = q.paths["backend"] / "results.db"
        database_before = hashlib.sha256(database.read_bytes()).hexdigest()
        captured = []
        QMessageBox.question = staticmethod(lambda *args, **kwargs: captured.append(args[2]) or QMessageBox.StandardButton.No)
        QInputDialog.getText = staticmethod(lambda *args, **kwargs: ("DELETE STUDY HISTORY", True))
        out["cancelled_scopes"] = {scope: q.window.begin_maintenance(scope) is False for scope in SCOPES}
        out["cancelled"] = all(out["cancelled_scopes"].values())
        out["confirmation"] = next((message for message in captured if "Reset Quiz Library" in message), "")
        QInputDialog.getText = staticmethod(lambda *args, **kwargs: ("WRONG PHRASE", True))
        out["study_wrong_phrase_refused"] = q.window.begin_maintenance("study") is False
        out["study_dialog_phrase"] = "DELETE STUDY HISTORY"
        QInputDialog.getText = staticmethod(lambda *args, **kwargs: ("DELETE STUDY HISTORY", True))
        out["study_second_confirmation_refused"] = q.window.begin_maintenance("study") is False
        out["study_confirmation"] = captured[-1] if captured else ""
        out["marker_absent"] = read_marker(a.profile) is None
        out["cancel_database_unchanged"] = hashlib.sha256(database.read_bytes()).hexdigest() == database_before
        QInputDialog.getText = staticmethod(lambda *args, **kwargs: ("", False))
        out["removal_cancelled"] = q.window.begin_removal() is False
        out["pass"] = (out["settings_action_visible"] and out["scopes"] == sorted(SCOPES)
                       and "native Desktop controls" in out["banner"] and out["removal_tombstone_wording"]
                       and out["legacy_disabled"]
                       and out["cancelled"] and out["study_wrong_phrase_refused"]
                       and out["study_second_confirmation_refused"] and "Study history" in out["study_confirmation"]
                       and out["removal_cancelled"] and out["marker_absent"] and out["cancel_database_unchanged"]
                       and a.profile in out["confirmation"] and "Study Packs" in out["confirmation"])
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        QMessageBox.question = old_question
        QInputDialog.getText = old_get_text
        (q.paths["root"] / "completion-maintenance-menu.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
