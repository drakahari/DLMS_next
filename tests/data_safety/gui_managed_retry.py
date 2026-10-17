"""Actual Qt confirmation, exact backend crash, separate-process same-token retry."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time

from tests.gate1.qt_checks import QtChecks


def rows(path):
    with sqlite3.connect(path / "results.db") as conn:
        return [list(row) for row in conn.execute("SELECT id,title,source_file FROM quizzes ORDER BY id")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--phase", choices=("crash", "retry"), required=True)
    parser.add_argument("--abort", default="after_item_0")
    parser.add_argument("--expected", type=int, default=2)
    args = parser.parse_args()
    assert args.profile.startswith("datasafety")
    q = QtChecks(args.profile, abort_import_at=args.abort if args.phase == "crash" else None)
    root, backend = q.paths["root"], q.paths["backend"]
    token = (root / "gate-a-token.txt").read_text().strip()
    result = {"profile": args.profile, "phase": args.phase, "token": token,
              "before": rows(backend), "abort": args.abort}
    try:
        q.go("/quiz-bundles/import/" + token)
        result["review"] = q.js("document.body.innerText.slice(-1500)")
        result["review_screenshot"] = str(q.screenshot("gate-a-" + args.phase + "-review.png", width=1050, height=780))
        assert q.js("!!document.querySelector('form[action$=\"/confirm\"]')")
        q.js("(()=>{let f=document.querySelector('form[action$=\"/confirm\"]');f.elements.confirm_import.checked=true;f.requestSubmit();return true})()")
        deadline = time.monotonic() + 35
        if args.phase == "crash":
            while time.monotonic() < deadline and not (root / "gate-a-checkpoint.json").exists():
                q.delay(0.1)
            assert (root / "gate-a-checkpoint.json").exists(), "backend did not reach exact crash checkpoint"
            result["checkpoint"] = json.loads((root / "gate-a-checkpoint.json").read_text())
        else:
            while time.monotonic() < deadline:
                if q.js("location.pathname === '/quiz-bundles'"):
                    break
                q.delay(0.1)
            if not q.js("location.pathname === '/quiz-bundles'"):
                result["failed_path"] = q.js("location.pathname")
                result["failed_message"] = q.js("document.body.innerText.slice(-2200)")
                result["failed_screenshot"] = str(q.screenshot("gate-a-retry-failure.png", width=1050, height=780))
                raise AssertionError("same-token retry did not complete in Qt")
            result["message"] = q.js("document.body.innerText.slice(-1500)")
            result["final_screenshot"] = str(q.screenshot("gate-a-retry-result.png", width=1050, height=780))
        result["after"] = rows(backend)
        op_files = list((root / "portable-import-operations").rglob(token + ".json"))
        assert len(op_files) == 1
        result["operation"] = json.loads(op_files[0].read_text())
        if args.phase == "crash":
            expected_state = ({"complete"} if args.abort == "after_complete_receipt" else
                              {"cleanup_pending"} if args.abort == "after_temporary_cleanup" else
                              {"prepared", "running"})
            result["pass"] = (result["checkpoint"]["stage"] == args.abort
                              and result["operation"]["state"] in expected_state)
        else:
            receipts = [item["receipt"] for item in result["operation"]["items"]]
            result["pass"] = (len(result["after"]) == args.expected
                              and result["operation"]["state"] == "complete"
                              and len({receipt["quiz_id"] for receipt in receipts}) == len(receipts)
                              and {receipt["quiz_id"] for receipt in receipts}.issubset({row[0] for row in result["after"]}))
        assert result["pass"], result
    finally:
        output = root / ("gate-a-" + args.phase + ".json")
        output.write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps({k: result.get(k) for k in ("profile", "phase", "pass", "before", "after", "checkpoint")}, indent=2))


if __name__ == "__main__":
    main()
