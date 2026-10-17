"""Edit the synthetic hotspot and grade its published quiz in real Qt."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
import traceback

from tests.gate1.qt_checks import QtChecks


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    a = p.parse_args()
    q = QtChecks(a.profile)
    root = q.paths["backend"]
    db = root / "results.db"
    out = {"profile": a.profile}
    try:
        manifest_path = next((root / "content_packs").glob("*/manifest.json"))
        manifest = json.loads(manifest_path.read_text())
        dataset_path = manifest_path.parent / "data" / "completion_hotspot.json"
        image_path = manifest_path.parent / "images" / "neutral-target.png"
        before_image = sha(image_path)
        before_dataset = json.loads(dataset_path.read_text())
        pack_id = manifest["id"]
        with sqlite3.connect(db) as conn:
            quiz = conn.execute("SELECT id FROM quizzes WHERE title='Completion Hotspot — Practice'").fetchone()[0]
            source_question = conn.execute("SELECT * FROM questions WHERE quiz_id=?", (quiz,)).fetchall()
            source_choices = conn.execute("SELECT * FROM choices WHERE question_id IN (SELECT id FROM questions WHERE quiz_id=?) ORDER BY choice_order", (quiz,)).fetchall()
        q.go(f"/admin/image-editor?pack={pack_id}&kind=quiz&dataset=completion_hotspot")
        q.wait("document.getElementById('circleRadius') !== null && document.getElementById('saveBtn') !== null")
        q.js("window.confirm=()=>true;(()=>{const r=document.getElementById('circleRadius');r.value='0.08';r.dispatchEvent(new Event('input'));return true})()")
        q.click_css("#saveBtn")
        q.wait("document.getElementById('status')?.innerText.includes('Saved') || document.body.innerText.includes('Backup:')", 20)
        out["edit_status"] = q.js("document.body.innerText.slice(-850)")
        out["edit_screenshot"] = str(q.screenshot("completion-hotspot-edited.png", width=1000, height=800))
        after_dataset = json.loads(dataset_path.read_text())
        old_shape = before_dataset["images"][0]["hotspots"][0]["shape"]
        new_shape = after_dataset["images"][0]["hotspots"][0]["shape"]
        out.update(old_shape=old_shape, new_shape=new_shape, image_sha256=sha(image_path))
        if new_shape != {"type": "circle", "x": 0.5, "y": 0.5, "radius": 0.08}:
            raise AssertionError("Hotspot editor did not retain the exact new geometry")
        registry = json.loads((root / "config/quizzes.json").read_text())
        q.go("/quizzes/" + next(x["html"] for x in registry if x["id"] == quiz))
        q.wait("document.querySelector('.study-mode-btn')?.disabled === false")
        q.js("document.querySelector('.study-mode-btn').click(); true")
        q.wait("document.querySelector('.hotspot-image-wrap') !== null")
        q.js("document.querySelector('.hotspot-image-wrap').focus(); true")
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        QTest.keyClick(q.app.focusWidget() or q.window.view, Qt.Key.Key_Enter)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            with sqlite3.connect(db) as conn:
                response = conn.execute("SELECT event_id,was_correct,payload_json FROM study_responses WHERE kind='response' ORDER BY rowid DESC LIMIT 1").fetchone()
            if response:
                break
            q.delay(.12)
        else:
            raise TimeoutError("Qt hotspot answer did not save")
        out["response"] = response
        out["grade_screenshot"] = str(q.screenshot("completion-hotspot-graded.png", width=1000, height=800))
        with sqlite3.connect(db) as conn:
            after_question = conn.execute("SELECT * FROM questions WHERE quiz_id=?", (quiz,)).fetchall()
            after_choices = conn.execute("SELECT * FROM choices WHERE question_id IN (SELECT id FROM questions WHERE quiz_id=?) ORDER BY choice_order", (quiz,)).fetchall()
        out["pass"] = (sha(image_path) == before_image and after_question == source_question
                       and after_choices == source_choices and response[1] == 1
                       and json.loads(response[2])["selected"] == {"x": 0.5, "y": 0.5})
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "completion-hotspot-edit-grade.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
