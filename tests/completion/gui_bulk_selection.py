"""Verify exact multi-page Library bundle selection inside the Qt window."""
from __future__ import annotations

import argparse
import json
import sqlite3
import traceback

from PySide6.QtTest import QTest

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    out = {"profile": args.profile}
    try:
        db = q.paths["backend"] / "results.db"
        with sqlite3.connect(db) as conn:
            before = conn.execute("SELECT id,title FROM quizzes ORDER BY id").fetchall()
        expected = {str(row[0]) for row in before}
        q.go("/quiz-bundles")
        out["candidate_count"] = q.js("document.querySelectorAll('input[name=quiz_ids]').length")
        q.click_css("#selectAllBundleQuizzes")
        out["all_selected"] = json.loads(q.js("JSON.stringify([...document.querySelectorAll('input[name=quiz_ids]:checked')].map(x=>x.value).sort())"))
        q.click_css("#bundleSearch")
        QTest.keyClicks(q.app.focusWidget() or q.window.view, "Parity Coll 001")
        out["filter_match"] = q.js("document.getElementById('bundleMatchCount').textContent")
        out["outside_filter"] = q.js("document.getElementById('bundleQuizCount').textContent")
        out["selected_after_filter"] = json.loads(q.js("JSON.stringify([...document.querySelectorAll('input[name=quiz_ids]:checked')].map(x=>x.value).sort())"))
        q.click_css("#clearBundleQuizzes")
        out["cleared"] = q.js("document.querySelectorAll('input[name=quiz_ids]:checked').length")
        q.click_css("#selectAllBundleQuizzes")
        out["one_filtered_selected"] = json.loads(q.js("JSON.stringify([...document.querySelectorAll('input[name=quiz_ids]:checked')].map(x=>x.value))"))
        q.screenshot("completion-bulk-selection.png", width=850, height=760)
        q.click_css('button[name="export_action"][value="check"]')
        q.delay(.6)
        out["after_click_url"] = q.js("location.href")
        out["after_click_excerpt"] = q.js("document.body.innerText.slice(0,900)")
        q.wait("location.pathname === '/quiz-bundles/export' && document.querySelector('#exportPreflightHeading') !== null")
        out["preflight_text"] = q.js("document.querySelector('#exportPreflightHeading').parentElement?.innerText")
        out["checked_after_preflight"] = json.loads(q.js("JSON.stringify([...document.querySelectorAll('input[name=quiz_ids]:checked')].map(x=>x.value))"))
        with sqlite3.connect(db) as conn:
            out["db_unchanged"] = conn.execute("SELECT id,title FROM quizzes ORDER BY id").fetchall() == before
        out["pass"] = bool(len(expected) == 101 and out["candidate_count"] == 101
                           and set(out["all_selected"]) == expected
                           and set(out["selected_after_filter"]) == expected
                           and "1 matching of 101" in out["filter_match"]
                           and "100 outside this filter" in out["outside_filter"]
                           and out["cleared"] == 0 and len(out["one_filtered_selected"]) == 1
                           and out["checked_after_preflight"] == out["one_filtered_selected"]
                           and "1 selected" in out["preflight_text"] and out["db_unchanged"])
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "completion-bulk-selection.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
