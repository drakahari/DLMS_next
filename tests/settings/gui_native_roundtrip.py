"""Separate-process synthetic native Settings backup/import fidelity drill."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import zipfile

from PySide6.QtWidgets import QFileDialog, QMessageBox

from desktop.isolation import profile_paths
from tests.gate1.qt_checks import QtChecks


TABLES = ("quizzes", "questions", "choices", "matching_pairs", "study_sessions",
          "study_responses", "attempts", "attempt_answers")


def facts(backend: Path):
    with closing(sqlite3.connect(backend / "results.db")) as connection:
        connection.row_factory = sqlite3.Row
        rows = {table: [dict(row) for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
                for table in TABLES}
    assets = {}
    for folder in ("quizzes", "quiz_assets", "data"):
        root = backend / folder
        if root.exists():
            for path in sorted(root.rglob("*")):
                if path.is_file() and not path.is_symlink() and not path.name.startswith("parse_log_"):
                    assets[str(path.relative_to(backend))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"rows": rows, "assets": assets}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--phase", choices=("export", "import", "reopen"), required=True)
    args = parser.parse_args()
    source = profile_paths(args.source, create=False)
    q = QtChecks(args.profile, automated=True)
    out = {"profile": args.profile, "source": args.source, "phase": args.phase}
    old_picker, old_question = QFileDialog.getOpenFileName, QMessageBox.question
    evidence = source["root"] / "native-settings-export.json"
    try:
        if args.phase == "export":
            before = facts(q.paths["backend"])
            assert before["rows"]["quizzes"] and before["rows"]["study_responses"]
            q.go("/settings/backup")
            q.window.settings_buttons["create_backup"].click()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and not q.window.downloaded_files:
                q.delay(.15)
            assert len(q.window.downloaded_files) == 1
            archive = q.window.downloaded_files[0]
            with zipfile.ZipFile(archive) as bundle:
                assert bundle.testzip() is None and len(bundle.namelist()) > 3
            q.delay(.4)
            assert "Backup downloaded" in q.window.settings_panel.action_status["create_backup"].text()
            assert archive.name in q.window.settings_panel.inventory_label.text()
            assert before == facts(q.paths["backend"])
            out.update(archive=str(archive), sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), facts=before)
            evidence.write_text(json.dumps(out, indent=2) + "\n")
        elif args.phase == "import":
            source_report = json.loads(evidence.read_text())
            archive = Path(source_report["archive"])
            assert archive.is_file() and hashlib.sha256(archive.read_bytes()).hexdigest() == source_report["sha256"]
            q.go("/settings/backup")
            QFileDialog.getOpenFileName = lambda *a, **kw: (str(archive), "DLMS backups (*.zip)")
            QMessageBox.question = lambda *a, **kw: QMessageBox.StandardButton.Yes
            q.window.settings_buttons["backup"].click()
            assert q.window.import_in_progress
            deadline = time.monotonic() + 55
            while time.monotonic() < deadline and q.window.import_in_progress:
                q.delay(.15)
            assert not q.window.import_in_progress
            q.wait("location.pathname === '/' && document.readyState === 'complete'", 30)
            actual = facts(q.paths["backend"])
            assert actual == source_report["facts"]
            out.update(data_equal=True, row_counts={k: len(v) for k, v in actual["rows"].items()},
                       asset_hashes=actual["assets"])
            q.go("/library")
            assert q.js("document.body.innerText.includes('Gate 1 Neutral Quiz')")
        else:
            source_report = json.loads(evidence.read_text())
            actual = facts(q.paths["backend"])
            assert actual == source_report["facts"]
            out.update(data_equal_after_restart=True,
                       row_counts={k: len(v) for k, v in actual["rows"].items()},
                       asset_hashes=actual["assets"])
            q.go("/library")
            assert q.js("document.body.innerText.includes('Gate 1 Neutral Quiz')")
        out["pass"] = True
    finally:
        QFileDialog.getOpenFileName, QMessageBox.question = old_picker, old_question
        (q.paths["root"] / f"native-settings-{args.phase}.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps({k: v for k, v in out.items() if k != "facts"}, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
