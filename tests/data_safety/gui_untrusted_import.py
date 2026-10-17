"""A pre-existing unbound stage cannot invent item receipts on confirmation."""
from __future__ import annotations

import argparse
import json
import sqlite3

from tests.gate1.qt_checks import QtChecks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    assert args.profile.startswith("datasafety")
    q = QtChecks(args.profile)
    root, backend = q.paths["root"], q.paths["backend"]
    token = (root / "gate-a-token.txt").read_text().strip()
    with sqlite3.connect(backend / "results.db") as db:
        before = list(db.execute("SELECT id,title,source_file FROM quizzes ORDER BY id"))
    evidence = {"token": token, "before": before}
    try:
        q.go("/quiz-bundles/import/" + token)
        q.js("(()=>{let f=document.querySelector('form[action$=\"/confirm\"]');f.elements.confirm_import.checked=true;f.requestSubmit();return true})()")
        q.wait("document.querySelector('[role=alert]')?.innerText.includes('trustworthy item identity')", 15)
        evidence["message"] = q.js("document.querySelector('[role=alert]').innerText")
        evidence["screenshot"] = str(q.screenshot("gate-a-untrusted-stage.png", width=1050, height=780))
        with sqlite3.connect(backend / "results.db") as db:
            evidence["after"] = list(db.execute("SELECT id,title,source_file FROM quizzes ORDER BY id"))
        evidence["operation_records"] = len(list((root / "portable-import-operations").rglob(token + ".json")))
        assert evidence["before"] == evidence["after"] and evidence["operation_records"] == 0
    finally:
        (root / "gate-a-untrusted-stage.json").write_text(json.dumps(evidence, indent=2) + "\n")
        q.close()


if __name__ == "__main__":
    main()
