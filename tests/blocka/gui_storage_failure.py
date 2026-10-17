"""Fail durable publication before acknowledgment in the actual Qt page."""
from __future__ import annotations

import argparse
import json
import sqlite3
from urllib.parse import urlsplit

from tests.gate1.qt_checks import QtChecks


def count(db, kind):
    with sqlite3.connect(db) as conn:
        table = "study_responses" if kind == "study" else "attempts"
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--kind", choices=("study", "exam"), required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, fail_action_accept=True)
    try:
        path = urlsplit(json.loads((q.paths["root"] / "foundation-create.json").read_text())["quiz_url"]).path
        q.go(path)
        db = q.paths["backend"] / "results.db"
        before = count(db, args.kind)
        if args.kind == "study":
            q.js("document.querySelector('.study-mode-btn').click(); true")
            q.wait("document.querySelector('button.choice') !== null")
            q.js("document.querySelector('button.choice').click(); true")
            q.wait("document.querySelector('#studyLearningEventStatus')?.innerText.includes('not retained')", 20)
            status = q.js("document.querySelector('#studyLearningEventStatus').innerText")
        else:
            q.js("document.querySelector('.exam-mode-btn').click(); true")
            q.wait("document.querySelector('button.choice') !== null")
            q.js("document.querySelector('button.choice').click(); true")
            q.js("window.confirm=()=>true; document.getElementById('submitBtn').click(); true")
            q.wait("document.body.innerText.includes('not confirmed as retained or saved')", 20)
            status = q.js("document.getElementById('result').innerText")
        result = {"kind": args.kind, "before": before, "after": count(db, args.kind),
                  "journal": [p.name for p in (q.paths["root"] / "durable-actions").glob("*.json")],
                  "status_text": status, "screenshot": str(q.screenshot(f"{args.kind}-storage-failure.png"))}
        result["status"] = "pass" if result["after"] == before and not result["journal"] else "fail"
        (q.paths["root"] / f"{args.kind}-storage-failure.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "pass" else 1
    finally:
        q.close()


if __name__ == "__main__":
    raise SystemExit(main())
