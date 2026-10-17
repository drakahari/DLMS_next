"""Read-only positive Smart View checks in the actual owned Qt window."""
from __future__ import annotations

import argparse
import json
import sqlite3
import traceback

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--keys", nargs="+", required=True)
    a = p.parse_args()
    q = QtChecks(a.profile)
    out = {"profile": a.profile, "keys": a.keys, "views": {}}
    try:
        db = q.paths["backend"] / "results.db"
        with sqlite3.connect(db) as c:
            before = {t: c.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
                      for t in ("quizzes", "questions", "choices", "study_responses", "attempts")}
            out["low_score_expected"] = [x[0] for x in c.execute(
                "SELECT quiz_id FROM attempts WHERE percent < 75 AND completed_at IS NOT NULL")]
        for key in a.keys:
            q.go(f"/library?view=active&smart={key}")
            if key == "unfinished":
                q.wait("document.body.classList.contains('library-smart-view-ready')", 15)
            out["views"][key] = json.loads(q.js("JSON.stringify({active:document.body.dataset.librarySmartView,"
                "visible:[...document.querySelectorAll('.library-quiz-card')].filter(e=>!e.classList.contains('library-smart-view-excluded') && e.style.display!=='none').map(e=>Number(e.dataset.quizId)),"
                "eligible:JSON.parse(document.getElementById('librarySmartEligibleQuizData').textContent),"
                "count:document.getElementById('librarySmartViewCount')?.innerText})"))
            out[key + "_screenshot"] = str(q.screenshot(f"completion-smart-{key}.png", width=1000, height=760))
        with sqlite3.connect(db) as c:
            out["canonical_unchanged"] = all(
                c.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() == before[t] for t in before)
        out["pass"] = bool(out["canonical_unchanged"] and all(
            v["active"] == key and v["visible"] and set(v["visible"]) == set(v["eligible"])
            and int(v["count"]) == len(v["visible"]) for key, v in out["views"].items()))
        if "low-score" in out["views"]:
            out["pass"] = out["pass"] and bool(set(out["views"]["low-score"]["visible"])
                                          & set(out["low_score_expected"]))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "completion-smart-positive.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
