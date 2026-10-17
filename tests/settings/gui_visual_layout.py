"""Focused Qt DOM geometry check for the two copied presentation edits.

Run after ``tests.gate1.gui_foundation --phase create`` in the same synthetic
profile. No native desktop input or owner data is involved.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from urllib.parse import urlsplit

from tests.gate1.qt_checks import QtChecks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, automated=True)
    result = {}
    try:
        quiz = json.loads((q.paths["root"] / "foundation-create.json").read_text())

        def history():
            q.go("/history")
            q.wait("document.querySelector('#historyTotalAttempts').textContent !== '—'")
            return json.loads(q.js("JSON.stringify((()=>{"
                                   "const a=document.querySelector('.history-table-stats').getBoundingClientRect();"
                                   "const b=document.querySelector('.history-table-panel').getBoundingClientRect();"
                                   "const link=document.querySelector('.history-study-navigation a');"
                                   "const style=getComputedStyle(link);const root=getComputedStyle(document.documentElement);"
                                   "return {gap:b.top-a.bottom,count:document.querySelector('#historyTotalAttempts').textContent,"
                                   "overflow:document.documentElement.scrollWidth>innerWidth,"
                                   "link:{href:link.getAttribute('href'),size:style.fontSize,weight:style.fontWeight,"
                                   "color:style.color,heading:root.getPropertyValue('--theme-heading').trim()}}})())"))

        result["empty_history"] = history()
        assert result["empty_history"]["count"] == "0"
        assert result["empty_history"]["gap"] >= 12
        assert not result["empty_history"]["overflow"]
        assert result["empty_history"]["link"]["href"] == "/study-history"
        assert result["empty_history"]["link"]["size"] == "16px"
        assert result["empty_history"]["link"]["weight"] == "600"
        for width, zoom in ((690, 1), (690, 2)):
            q.window.resize(width, 850)
            q.window.view.setZoomFactor(zoom)
            q.delay(.2)
            measure = json.loads(q.js("JSON.stringify((()=>{const a=document.querySelector('.history-study-navigation a');"
                                      "const r=a.getBoundingClientRect();return {viewport:innerWidth,linkWidth:r.width,"
                                      "overflow:document.documentElement.scrollWidth>innerWidth}})())"))
            result[f"history_{width}_{zoom}"] = measure
            assert not measure["overflow"]
            assert measure["linkWidth"] <= measure["viewport"]
        q.window.resize(1280, 850)
        q.window.view.setZoomFactor(1)

        q.go(urlsplit(quiz["quiz_url"]).path)
        if q.js("!!document.querySelector('.quiz-recovery-start-over')"):
            q.js("window.confirm=()=>true;document.querySelector('.quiz-recovery-start-over').click();true")
        q.js("document.querySelector('.exam-mode-btn').click();true")
        q.wait("document.querySelector('button.choice')!==null")
        q.js("document.querySelector('button.choice').click();document.getElementById('nextBtn').click();true")
        q.wait("document.querySelector('button.choice')!==null")
        q.js("document.querySelector('button.choice').click();window.confirm=()=>true;"
             "document.getElementById('submitBtn').click();true")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with sqlite3.connect(q.paths["backend"] / "results.db") as conn:
                if conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 1:
                    break
            q.delay(.15)
        else:
            raise AssertionError("Synthetic Exam attempt did not commit")
        q.go("/history")
        q.wait("document.querySelector('#historyTotalAttempts').textContent==='1'", 20)
        result["populated_history"] = history()
        assert result["populated_history"]["count"] == "1"
        assert result["populated_history"]["gap"] >= 12
        with sqlite3.connect(q.paths["backend"] / "results.db") as conn:
            result["durable_attempts"] = conn.execute("SELECT count(*) FROM attempts").fetchone()[0]
        assert result["durable_attempts"] == 1

        q.go(f"/quiz-composer/study-mistakes?quizzes={quiz['quiz_id']}")
        assert q.js("!!document.querySelector('.study-mistakes-preview')")
        # Rendering-only fixture: long words and prose must wrap in the third
        # column without changing quiz content or Study mistakes membership.
        q.js("(()=>{const body=document.querySelector('.study-mistakes-preview tbody');"
             "const row=document.createElement('tr');"
             "for(const value of ['Synthetic source','2',"
             "'A lengthy synthetic question with many words and an '+"
             "'unbrokenidentifierthatmustwrapinsideanarrowquestioncolumn'.repeat(5)]){"
             "const cell=document.createElement('td');cell.textContent=value;row.append(cell)}"
             "body.append(row);row.lastChild.id='visualLongQuestion';return true})()")
        for width, zoom in ((1280, 1), (690, 1), (690, 2)):
            q.window.resize(width, 850)
            q.window.view.setZoomFactor(zoom)
            q.delay(.3)
            measure = json.loads(q.js("JSON.stringify((()=>{"
                                      "const h=document.querySelector('.study-mistakes-preview thead th:nth-child(2)');"
                                      "return {heading:h.textContent.trim(),whiteSpace:getComputedStyle(h).whiteSpace,"
                                      "mobile:getComputedStyle(h.parentElement.parentElement).position==='absolute',"
                                      "overflow:document.documentElement.scrollWidth>innerWidth,"
                                      "longCellOverflow:document.querySelector('#visualLongQuestion').scrollWidth>"
                                      "document.querySelector('#visualLongQuestion').clientWidth+1,"
                                      "longCellHeight:document.querySelector('#visualLongQuestion').getBoundingClientRect().height}})())"))
            result[f"preview_{width}_{zoom}"] = measure
            assert measure["heading"] == "Question #"
            assert measure["whiteSpace"] == "nowrap"
            assert not measure["overflow"]
            assert not measure["longCellOverflow"]
            assert measure["longCellHeight"] > 50
            if zoom == 2:
                assert measure["mobile"]  # accessible card layout replaces the narrow header
        result["pass"] = True
    finally:
        (q.paths["root"] / "visual-layout.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
