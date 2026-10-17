"""Verify adopted synthetic content in a fresh Qt process without old browser state."""
from __future__ import annotations

import argparse
import json
import sqlite3
import traceback

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    result = {"profile": args.profile}
    try:
        q.go("/library")
        result["library_text"] = q.js("document.body.innerText.includes('Gate 1 Neutral Quiz')")
        result["library_screenshot"] = str(q.screenshot("blockb-adopted-library.png"))
        result["browser_progress_keys"] = json.loads(q.js("JSON.stringify(Object.keys(localStorage).filter(key=>key.startsWith('dlms.quiz-progress.v1:')))"))
        q.go("/history")
        result["history_text"] = q.js("document.body.innerText.slice(0,1200)")
        result["history_screenshot"] = str(q.screenshot("blockb-adopted-history.png"))
        with sqlite3.connect(q.paths["backend"] / "results.db") as conn:
            result["schema"] = conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()[0]
            result["quizzes"] = conn.execute("SELECT id,title FROM quizzes ORDER BY id").fetchall()
            result["responses"] = conn.execute("SELECT count(*) FROM study_responses WHERE kind='response'").fetchone()[0]
        result["status"] = "pass" if (result["library_text"] and result["schema"] == 12 and
            result["responses"] >= 1 and not result["browser_progress_keys"]) else "fail"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "blockb-adoption-qt.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
