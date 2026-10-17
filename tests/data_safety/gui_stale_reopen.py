"""Separate-process Qt check of stale Study/Exam browser evidence and zero result."""
from __future__ import annotations

import argparse
import json
import sqlite3
from urllib.parse import urlsplit

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--kind", choices=("study", "exam"), required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    root, db = q.paths["root"], q.paths["backend"] / "results.db"
    fixture = json.loads((root / "foundation-create.json").read_text())
    before = json.loads((root / f"data-safety-{args.kind}-stale-before-accept.json").read_text())
    try:
        q.go(urlsplit(fixture["quiz_url"]).path)
        checkpoint = q.js(f"localStorage.getItem('dlms.quiz-progress.v1:'+{fixture['quiz_id']})")
        with sqlite3.connect(db) as conn:
            table = "study_responses" if args.kind == "study" else "attempts"
            durable = conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
        out = {"profile": args.profile, "kind": args.kind,
               "same_pending_action": before["action_id"] in (checkpoint or ""),
               "durable_count": durable,
               "journal_empty": not list((root / "durable-actions").glob("*.json")),
               "recovery_screen": q.js("document.body.innerText.slice(0,700)"),
               "screenshot": str(q.screenshot(f"data-safety-{args.kind}-stale-reopen.png", width=1020, height=760))}
        out["pass"] = (out["same_pending_action"] and
                       durable == before["durable_count_before"] and out["journal_empty"])
        (root / f"data-safety-{args.kind}-stale-reopen.json").write_text(json.dumps(out, indent=2) + "\n")
        print(json.dumps(out, indent=2))
        return 0 if out["pass"] else 1
    finally:
        q.close()


if __name__ == "__main__":
    raise SystemExit(main())
