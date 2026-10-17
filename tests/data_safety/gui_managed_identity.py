"""Qt duplicate confirmation and distinct-upload policy for managed imports."""
from __future__ import annotations
import argparse
import json
import sqlite3
import time

from desktop.isolation import AREA
from tests.gate1.qt_checks import QtChecks


def ids(path):
    with sqlite3.connect(path / "results.db") as conn:
        return [list(row) for row in conn.execute("SELECT id,title,source_file FROM quizzes ORDER BY id")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    assert args.profile.startswith("datasafety")
    q = QtChecks(args.profile)
    root, backend = q.paths["root"], q.paths["backend"]
    token = (root / "gate-a-token.txt").read_text().strip()
    result = {"profile": args.profile, "token": token, "before": ids(backend)}
    try:
        q.go("/quiz-bundles/import/" + token)
        q.js("window.__confirmResults=[];Promise.all([0,1].map(()=>fetch(location.pathname+'/confirm',{method:'POST',body:new URLSearchParams({confirm_import:'yes'}),redirect:'follow'}).then(r=>r.status))).then(x=>window.__confirmResults=x).catch(e=>window.__confirmResults=['error',String(e)]);true")
        q.wait("window.__confirmResults.length === 2", 30)
        result["concurrent"] = json.loads(q.js("JSON.stringify(window.__confirmResults)"))
        result["after_concurrent"] = ids(backend)
        assert len(result["after_concurrent"]) == 3 and result["concurrent"] == [200, 200], result
        q.go("/quiz-bundles/import/" + token)
        result["repeat_message"] = q.js("document.body.innerText")
        result["repeat_screenshot"] = str(q.screenshot("gate-a-repeat-message.png", width=1024, height=740))
        assert "already completed" in result["repeat_message"] and ids(backend) == result["after_concurrent"]
        q.go("/quiz-bundles")
        q.window.file_selection_for_test = AREA / "fixtures/data-safety-two.zip"
        q.click_css('input[name="bundle_zip"]')
        q.js("document.querySelector('form[action=\"/quiz-bundles/import\"]').requestSubmit();true")
        q.wait("location.pathname.startsWith('/quiz-bundles/import/')", 20)
        result["separate_review"] = q.js("document.body.innerText.slice(-1600)")
        assert "(Imported)" in result["separate_review"]
        q.js("(()=>{let f=document.querySelector('form[action$=\"/confirm\"]');f.elements.confirm_import.checked=true;f.requestSubmit();return true})()")
        q.wait("location.pathname === '/quiz-bundles'", 30)
        result["after_separate"] = ids(backend)
        result["separate_screenshot"] = str(q.screenshot("gate-a-separate-import.png", width=1050, height=760))
        assert len(result["after_separate"]) == 5
        assert result["after_separate"][:3] == result["after_concurrent"]
        result["pass"] = True
    finally:
        (root / "gate-a-identity.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps({k: result.get(k) for k in ("profile", "pass", "concurrent", "before", "after_concurrent", "after_separate")}, indent=2))


if __name__ == "__main__":
    main()
