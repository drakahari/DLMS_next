"""Real Qt Settings entry to the existing managed settings-reset transaction."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time

from PySide6.QtWidgets import QMessageBox

from desktop.isolation import AREA
from tests.gate1.qt_checks import QtChecks


TABLES = ("quizzes", "questions", "choices", "matching_pairs", "attempts",
          "attempt_answers", "study_sessions", "study_responses", "certifications")


def facts(database):
    with sqlite3.connect(database) as connection:
        return {name: connection.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
                for name in TABLES}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--phase", choices=("run", "reopen"), required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, automated=True)
    old_question = QMessageBox.question
    out = {"profile": args.profile, "phase": args.phase}
    evidence = q.paths["root"] / "settings-maintenance-before.json"
    marker_path = AREA / "maintenance" / args.profile / "active.json"
    try:
        database = q.paths["backend"] / "results.db"
        if args.phase == "run":
            before = facts(database)
            assert before["quizzes"] and before["study_responses"]
            evidence.write_text(json.dumps(before, indent=2) + "\n")
            q.go("/settings/reset-remove")
            assert q.window._settings_ready("reset-remove")
            q.window.grab().save(str(q.paths["root"] / "settings-maintenance-before.png"))
            QMessageBox.question = lambda *a, **kw: QMessageBox.StandardButton.Yes
            q.window.settings_buttons["settings"].click()
            assert q.window.maintenance_worker is not None
            assert q.window.settings_panel is None
            # A queued activation during worker progress cannot begin a second transaction.
            worker_pid = q.window.maintenance_worker.pid
            q.window._activate_settings_action("settings")
            assert q.window.maintenance_worker.pid == worker_pid
            q.window.grab().save(str(q.paths["root"] / "settings-maintenance-progress.png"))
            deadline = time.monotonic() + 50
            while time.monotonic() < deadline:
                q.delay(.15)
                if marker_path.exists() and json.loads(marker_path.read_text()).get("phase") == "browser_check_pending":
                    break
            else:
                raise TimeoutError("Managed settings transaction did not reach browser verification")
            after = facts(database)
            assert after == before, "Default-settings reset changed unrelated semantic records"
            marker = json.loads(marker_path.read_text())
            assert marker["scope"] == "settings" and marker.get("retained_safety_sha256")
            out.update(pass_=True, worker_pid=worker_pid, unrelated_rows_unchanged=True,
                       marker_phase=marker["phase"], retained_safety_sha256=marker["retained_safety_sha256"])
        else:
            before = json.loads(evidence.read_text())
            after = json.loads(json.dumps(facts(database)))
            assert after == before
            assert not marker_path.exists()
            assert q.js("location.pathname") == "/"
            out.update(pass_=True, unrelated_rows_unchanged=True, marker_absent=True)
        out["pass"] = out.pop("pass_")
    finally:
        QMessageBox.question = old_question
        (q.paths["root"] / f"settings-maintenance-{args.phase}.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
