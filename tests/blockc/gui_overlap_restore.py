"""Adopt an overlapping Desktop backup into a second disposable Qt profile."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import zipfile

from tests.gate1.qt_checks import QtChecks


def rows(conn, table):
    columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
    order = ",".join(f'"{name}"' for name in columns)
    return sorted(tuple(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY {order}'))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    report = {}
    try:
        os.environ["DLMS_DESKTOP_AUTOMATED"] = "1"
        report["import_started"] = q.window.adopt_backup(args.archive)
        q.wait("location.pathname === '/' && document.readyState === 'complete'", 40)
        q.go("/library")
        report["library_contains_quiz"] = q.js("document.body.innerText.includes('Block C Concurrent Quiz')")
        report["screenshot"] = str(q.screenshot("blockc-overlap-restored.png"))
        with zipfile.ZipFile(args.archive) as archive, tempfile.TemporaryDirectory(dir=q.paths["tmp"]) as temporary:
            archive_db = Path(temporary) / "archive.db"
            archive_db.write_bytes(archive.read("DLMS_DATA/results.db"))
            with sqlite3.connect(archive_db) as source, sqlite3.connect(q.paths["backend"] / "results.db") as target:
                tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                epoch_tables = {"certification_state", "exam_plan_state", "review_mark_state", "study_mistake_state", "study_state"}
                report["row_mismatches"] = [table for table in sorted(tables - epoch_tables)
                                            if rows(source, table) != rows(target, table)]
                report["schema"] = target.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()[0]
                report["quiz_rows"] = target.execute("SELECT id,title FROM quizzes WHERE title='Block C Concurrent Quiz'").fetchall()
                report["choice_rows"] = target.execute("SELECT label,text,is_correct,choice_order FROM choices ORDER BY question_id,choice_order").fetchall()
            report["asset_mismatches"] = []
            for member in archive.namelist():
                if not member.startswith("DLMS_DATA/") or member.endswith("/") or member == "DLMS_DATA/results.db":
                    continue
                live = q.paths["backend"] / member.removeprefix("DLMS_DATA/")
                if (not live.is_file() or hashlib.sha256(archive.read(member)).digest()
                        != hashlib.sha256(live.read_bytes()).digest()):
                    report["asset_mismatches"].append(member)
        report["archive_sha256"] = hashlib.sha256(args.archive.read_bytes()).hexdigest()
        report["preserved_input"] = any(hashlib.sha256(path.read_bytes()).hexdigest() == report["archive_sha256"]
                                         for path in (q.paths["root"] / "imports").glob("*.zip"))
        report["pass"] = (report["import_started"] and report["library_contains_quiz"]
                          and report["schema"] == 12 and len(report["quiz_rows"]) == 1
                          and any(row[:3] == ("B", "Four", 1) for row in report["choice_rows"])
                          and not report["row_mismatches"] and not report["asset_mismatches"]
                          and report["preserved_input"])
    finally:
        (q.paths["root"] / "blockc-overlap-restore.json").write_text(json.dumps(report, indent=2) + "\n")
        q.close()
    print(json.dumps(report, indent=2))
    return 0 if report.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
