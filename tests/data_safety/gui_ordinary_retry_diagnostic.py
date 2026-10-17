"""Diagnose same-token retry after a process-killed two-quiz receiver."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    root, backend = q.paths["root"], q.paths["backend"]
    prior = json.loads((root / "data-safety-ordinary-inspect.json").read_text())
    token = prior["checkpoint"]["token"]
    with sqlite3.connect(backend / "results.db") as conn:
        before = [list(row) for row in conn.execute("SELECT id,title FROM quizzes ORDER BY id")]
    q.go("/quiz-bundles/import/" + token)
    review = q.js("document.body.innerText")
    out = {"profile": args.profile, "token": token,
           "before": before, "review_excerpt": review[-1200:]}
    try:
        confirm = q.js("!!document.querySelector('form[action$=\"/confirm\"]')")
        out["confirm_enabled"] = confirm
        if confirm:
            q.js("(()=>{const f=document.querySelector('form[action$=\"/confirm\"]');f.elements.confirm_import.checked=true;f.requestSubmit();return true})()")
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                with sqlite3.connect(backend / "results.db") as conn:
                    current = [list(row) for row in conn.execute("SELECT id,title FROM quizzes ORDER BY id")]
                if len(current) > len(before) or q.js("location.pathname === '/quiz-bundles'"):
                    break
                q.delay(.1)
        with sqlite3.connect(backend / "results.db") as conn:
            after = [list(row) for row in conn.execute("SELECT id,title FROM quizzes ORDER BY id")]
        out.update(after=after, page=q.js("location.pathname"), message=q.js("document.body.innerText.slice(-1100)"),
                   screenshot=str(q.screenshot("data-safety-ordinary-retry.png", width=1030, height=760)))
        original = prior["checkpoint"]["title"]
        out["duplicate_first_source"] = sum(title.startswith(original) for _, title in after) > 1
        out["safe_retry"] = not out["duplicate_first_source"]
        out["diagnostic_complete"] = True
    finally:
        (root / "data-safety-ordinary-retry.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps({k: out.get(k) for k in ("profile", "confirm_enabled", "duplicate_first_source", "safe_retry", "diagnostic_complete")}, indent=2))
    return 0 if out["diagnostic_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
