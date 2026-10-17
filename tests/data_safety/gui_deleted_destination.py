"""Deliberately deleted imported item is never recreated by same-token retry."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time

from tests.gate1.qt_checks import QtChecks


def rows(db):
    with sqlite3.connect(db) as connection:
        return [list(row) for row in connection.execute(
            "SELECT id,title,source_file FROM quizzes ORDER BY id")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--retry-only", action="store_true")
    args = parser.parse_args()
    assert args.profile.startswith("datasafety")
    q = QtChecks(args.profile)
    root, backend = q.paths["root"], q.paths["backend"]
    token = (root / "gate-a-token.txt").read_text().strip()
    result = {"token": token, "before": rows(backend / "results.db")}
    try:
        if args.retry_only:
            record = next((root / "portable-import-operations").rglob(token + ".json"))
            quiz_id = json.loads(record.read_text())["items"][0]["receipt"]["quiz_id"]
        else:
            imported = [row for row in result["before"] if row[2].startswith("portable_quiz_")]
            assert len(imported) == 1
            quiz_id = imported[0][0]
            q.go("/library")
            selector = f'form[action="/delete_quiz/{quiz_id}"]'
            assert q.js(f"!!document.querySelector({json.dumps(selector)})")
            q.js(f"(()=>{{let f=document.querySelector({json.dumps(selector)});f.onsubmit=null;f.requestSubmit();return true}})()")
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and quiz_id in {row[0] for row in rows(backend / "results.db")}:
                q.delay(0.08)
        result["after_delete"] = rows(backend / "results.db")
        assert quiz_id not in {row[0] for row in result["after_delete"]}
        q.go("/quiz-bundles/import/" + token)
        q.js("(()=>{let f=document.querySelector('form[action$=\"/confirm\"]');f.elements.confirm_import.checked=true;f.requestSubmit();return true})()")
        q.wait("!!document.querySelector('.portable-bundle-error')", 15)
        result["message"] = q.js("document.querySelector('.portable-bundle-error').innerText")
        result["screenshot"] = str(q.screenshot("gate-a-deleted-destination.png", width=1050, height=780))
        result["after_retry"] = rows(backend / "results.db")
        record = next((root / "portable-import-operations").rglob(token + ".json"))
        result["operation"] = json.loads(record.read_text())
        assert result["after_retry"] == result["after_delete"]
        assert result["operation"]["items"][0]["receipt"]["quiz_id"] == quiz_id
        assert result["operation"]["items"][1]["state"] == "planned"
        assert "Previously committed quiz changed or was removed" in result["message"]
        result["pass"] = True
    finally:
        (root / "gate-a-deleted-destination.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()


if __name__ == "__main__":
    main()
