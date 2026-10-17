"""Read synthetic Block C content after a separate Qt process restart."""
from __future__ import annotations

import argparse
import json
import sqlite3

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    report = {}
    try:
        q.go("/library")
        report["folder_and_quiz"] = q.js("document.body.innerText.includes('Block C Folder') && document.body.innerText.includes('Gate 1 Neutral Quiz')")
        q.go("/exam-plans")
        report["plan_listed"] = q.js("document.body.innerText.includes('Block C Synthetic Plan')")
        report["plan_screenshot"] = str(q.screenshot("blockc-plan-reopen.png"))
        q.go("/certifications")
        report["credential_listed"] = q.js("document.body.innerText.includes('Synthetic credential')")
        q.go("/history")
        report["exam_history"] = q.js("document.body.innerText.includes('Gate 1 Neutral Quiz')")
        with sqlite3.connect(q.paths["backend"] / "results.db") as conn:
            report["plan_config"] = json.loads(conn.execute("SELECT config_json FROM exam_plans LIMIT 1").fetchone()[0])
            report["choice_identity"] = conn.execute("SELECT c.id,c.label,c.text,c.is_correct,c.choice_order FROM choices c JOIN questions q ON q.id=c.question_id WHERE q.quiz_id=1 ORDER BY q.id,c.choice_order").fetchall()
        report["pass"] = bool(report["folder_and_quiz"] and report["plan_listed"]
            and report["credential_listed"] and report["exam_history"]
            and report["plan_config"]["calendar_timezone"] == "America/Chicago"
            and any(row[1:4] == ("B", "Four", 1) for row in report["choice_identity"]))
    finally:
        (q.paths["root"] / "blockc-parity-reopen.json").write_text(json.dumps(report, indent=2) + "\n")
        q.close()
    print(json.dumps(report, indent=2))
    return 0 if report.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
