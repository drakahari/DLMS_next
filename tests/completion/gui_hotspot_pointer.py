"""Actual Qt pointer grading of a synthetic published hotspot."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
import traceback

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--reopen", action="store_true")
    a = p.parse_args()
    q = QtChecks(a.profile)
    out = {"profile": a.profile, "reopen": a.reopen}
    try:
        backend = q.paths["backend"]
        db = backend / "results.db"
        with sqlite3.connect(db) as conn:
            quiz_id = conn.execute("SELECT id FROM quizzes WHERE title='Completion Hotspot — Practice'").fetchone()[0]
            original = [conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
                        for table in ("quizzes", "questions", "choices", "matching_pairs")]
            before = conn.execute("SELECT event_id,was_correct,payload_json FROM study_responses WHERE kind='response' ORDER BY rowid").fetchall()
        registry = json.loads((backend / "config/quizzes.json").read_text())
        page = next(item["html"] for item in registry if item["id"] == quiz_id)
        image = next((backend / "content_packs").glob("*/images/neutral-target.png"))
        image_hash = hashlib.sha256(image.read_bytes()).hexdigest()
        if not a.reopen:
            q.go("/quizzes/" + page)
            q.wait("document.querySelector('.study-mode-btn')?.disabled === false")
            q.click_css(".study-mode-btn")
            q.wait("document.querySelector('.hotspot-image-wrap img')?.complete === true")
            q.click_css(".hotspot-image-wrap img")
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                with sqlite3.connect(db) as conn:
                    responses = conn.execute("SELECT event_id,was_correct,payload_json FROM study_responses WHERE kind='response' ORDER BY rowid").fetchall()
                if len(responses) == len(before) + 1:
                    break
                q.delay(.1)
            else:
                raise TimeoutError("Qt pointer response was not durably saved")
            out["response"] = responses[-1]
            out["visible_correct_marker"] = q.js("!!document.querySelector('.hotspot-click-marker.correct')")
            out["screenshot"] = str(q.screenshot("completion-hotspot-pointer.png", width=1000, height=800))
        else:
            responses = before
            out["response"] = responses[-1]
            previous = json.loads((q.paths["root"] / "completion-hotspot-pointer.json").read_text())
            out["same_response_after_restart"] = list(out["response"]) == previous["response"]
            out["same_image_after_restart"] = image_hash == previous["image_sha256"]
        with sqlite3.connect(db) as conn:
            after = [conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
                     for table in ("quizzes", "questions", "choices", "matching_pairs")]
        selected = json.loads(out["response"][2])["selected"]
        out["selected"] = selected
        out["image_sha256"] = image_hash
        out["source_rows_unchanged"] = original == after
        out["pass"] = (out["response"][1] == 1 and abs(selected["x"] - .5) < .02
                       and abs(selected["y"] - .5) < .02 and out["source_rows_unchanged"]
                       and (not a.reopen or (out["same_response_after_restart"]
                                              and out["same_image_after_restart"]))
                       and (a.reopen or out["visible_correct_marker"]))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / ("completion-hotspot-pointer-reopen.json" if a.reopen
                            else "completion-hotspot-pointer.json")).write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
