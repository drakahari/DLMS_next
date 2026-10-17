"""Actual Qt: a mismatched Desktop epoch never relabels a browser request."""
from __future__ import annotations

import argparse
import json
import sqlite3
import traceback

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    args = p.parse_args()
    q = QtChecks(args.profile)
    result = {"profile": args.profile}
    try:
        quiz = json.loads((q.paths["root"] / "foundation-create.json").read_text())["quiz_id"]
        q.go(f"/quiz-composer/study-mistakes?quizzes={quiz}")
        planted = {"context": {"profile_uuid": "00000000-0000-0000-0000-000000000001",
                               "epoch": "00000000-0000-0000-0000-000000000002"},
                   "payload": {"request_id": "syntheticstalerequest01", "title": "Never publish"}}
        q.js(f"localStorage.setItem('dlms-study-mistakes-request', {json.dumps(json.dumps(planted))}); true")
        with sqlite3.connect(q.paths["backend"] / "results.db") as conn:
            before = conn.execute("SELECT count(*) FROM study_mistake_actions").fetchone()[0]
        q.go(f"/quiz-composer/study-mistakes?quizzes={quiz}")
        q.wait("document.getElementById('mistakeStatus')?.innerText.includes('another Desktop dataset')", 15)
        result["message"] = q.js("document.getElementById('mistakeStatus').innerText")
        result["retained"] = q.js("!!localStorage.getItem('dlms-study-mistakes-request')")
        result["retry_hidden"] = q.js("document.getElementById('retryMistakeMix').hidden")
        q.js("document.getElementById('mistakeStatus').scrollIntoView({block:'center'}); true")
        result["screenshot"] = str(q.screenshot("blockb-stale-evidence.png"))
        with sqlite3.connect(q.paths["backend"] / "results.db") as conn:
            after = conn.execute("SELECT count(*) FROM study_mistake_actions").fetchone()[0]
        result["status"] = "pass" if before == after and result["retained"] and result["retry_hidden"] else "fail"
    except Exception as exc:
        result["status"] = "error"; result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "blockb-stale-evidence.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
