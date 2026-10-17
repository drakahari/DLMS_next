"""Repeated completed-token navigation cannot republish a frozen import."""
from __future__ import annotations

import argparse
import json
import sqlite3

from tests.gate1.qt_checks import QtChecks


def quizzes(db):
    with sqlite3.connect(db) as conn:
        return [list(row) for row in conn.execute("SELECT id,title,source_file FROM quizzes ORDER BY id")]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    root = q.paths["root"]
    token = (root / "gate-a-token.txt").read_text().strip()
    db = q.paths["backend"] / "results.db"
    before = quizzes(db)
    from PySide6.QtCore import QUrl
    q.window.view.setUrl(QUrl(f"http://127.0.0.1:{q.window.port}/quiz-bundles/import/{token}"))
    q.wait("document.readyState === 'complete' && location.pathname !== '/'", 20)
    q.delay(0.3)
    report = {"before": before, "after": quizzes(db), "path": q.js("location.pathname"),
              "message": q.js("document.body.innerText.slice(-1000)"),
              "screenshot": str(q.screenshot("completed-import-repeat.png"))}
    report["pass"] = report["before"] == report["after"]
    (root / "completed-import-repeat.json").write_text(json.dumps(report, indent=2) + "\n")
    q.close()
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
