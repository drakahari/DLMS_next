"""Exercise all six Library Smart View filters in the actual Qt WebEngine page."""
from __future__ import annotations

import argparse
import json
import sqlite3
import traceback

from tests.gate1.qt_checks import QtChecks


KEYS = ("needs-review", "recently-added", "low-score", "unfinished", "ocr-imported", "generated-practice")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--reopen", action="store_true")
    a = p.parse_args()
    q = QtChecks(a.profile)
    out = {"profile": a.profile, "reopen": a.reopen, "views": {}}
    try:
        db = q.paths["backend"] / "results.db"
        with sqlite3.connect(db) as conn:
            before = {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
                      for t in ("quizzes", "questions", "choices", "study_responses", "attempts")}
        with sqlite3.connect(db) as conn:
            mixed_id = conn.execute("SELECT id FROM quizzes WHERE title='Parity Mixed Synthetic Quiz'").fetchone()[0]
        for key in KEYS:
            q.go(f"/library?view=active&smart={key}")
            if key == "unfinished":
                q.wait("document.body.classList.contains('library-smart-view-ready')", 15)
            view = json.loads(q.js("JSON.stringify({active:document.body.dataset.librarySmartView,"
                                   "link:!!document.querySelector('.library-smart-view-link.active[aria-current=page]'),"
                                   "visible:[...document.querySelectorAll('.library-quiz-card')].filter(e=>!e.classList.contains('library-smart-view-excluded') && e.style.display!=='none').map(e=>Number(e.dataset.quizId)),"
                                   "eligible:JSON.parse(document.getElementById('librarySmartEligibleQuizData').textContent),"
                                   "count:document.getElementById('librarySmartViewCount')?.innerText})"))
            out["views"][key] = view
            if key in ("generated-practice", "unfinished"):
                out[key + "_screenshot"] = str(q.screenshot(f"parity-smart-{key}.png", width=800, height=760))
        with sqlite3.connect(db) as conn:
            out["canonical_unchanged"] = all(conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()==before[t] for t in before)
        out["mixed_id"] = mixed_id
        out["expected_for_fixture"] = {
            "needs-review": [], "recently-added": [1,2,3,4], "low-score": [],
            "unfinished": [1,3], "ocr-imported": [], "generated-practice": [],
        }
        out["pass"] = bool(all(v["active"] == key and v["link"] and
                               set(v["visible"]).issubset(set(v["eligible"])) and
                               sorted(v["visible"]) == out["expected_for_fixture"][key] and
                               int(v["count"]) == len(v["visible"])
                               for key, v in out["views"].items())
                           and mixed_id not in out["views"]["generated-practice"]["visible"]
                           and out["canonical_unchanged"])
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / ("parity-smart-views-reopen.json" if a.reopen else "parity-smart-views.json")).write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
