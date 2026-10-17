"""Create a synthetic hotspot through Qt's existing image builder and keyboard stage."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sqlite3
import traceback

from desktop.isolation import AREA
from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--reopen", action="store_true")
    a = p.parse_args()
    q = QtChecks(a.profile)
    root = q.paths["backend"]
    out = {"profile": a.profile, "reopen": a.reopen}
    try:
        image = AREA / "fixtures" / "gate1-ocr.png"
        if not image.is_file():
            raise FileNotFoundError("Project-local synthetic PNG fixture is required")
        out["input_sha256"] = hashlib.sha256(image.read_bytes()).hexdigest()
        if not a.reopen:
            q.go("/study-packs/image-builder")
            payload = base64.b64encode(image.read_bytes()).decode()
            q.js("""(()=>{const data=atob(""" + json.dumps(payload) + """),bytes=new Uint8Array(data.length);
              for(let i=0;i<data.length;i++)bytes[i]=data.charCodeAt(i);
              const dt=new DataTransfer();dt.items.add(new File([bytes],'neutral-target.png',{type:'image/png'}));
              document.querySelector('[name=study_images]').files=dt.files;
              document.querySelector('.image-builder-upload-form').requestSubmit();return true})()""")
            q.wait("document.getElementById('builderForm') !== null", 25)
            q.js("""(()=>{const f=document.getElementById('builderForm');f.elements.pack_title.value='Completion Hotspot';
              f.elements.subject.value='General';f.elements.source_note.value='Synthetic project fixture';
              f.elements.rights_ok.checked=true;const c=document.querySelector('.image-builder-question-card');
              c.querySelector('.q-text').value='Find the synthetic target.';
              const t=c.querySelector('.q-type');t.value='hotspot';t.dispatchEvent(new Event('change'));
              c.querySelector('.hotspot-label').value='Target';
              c.querySelector('.image-builder-hotspot-stage').focus();return true})()""")
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest
            QTest.keyClick(q.app.focusWidget() or q.window.view, Qt.Key.Key_Enter)
            q.delay(.2)
            out["stage_status"] = q.js("document.querySelector('.hotspot-status').innerText")
            out["stage_shape"] = json.loads(q.js("JSON.stringify(document.querySelector('.image-builder-question-card')._shape)"))
            if not out["stage_shape"].get("center"):
                raise AssertionError("Qt keyboard did not place a hotspot center")
            q.click_css('#builderForm button[type=submit]')
            q.wait("location.pathname.startsWith('/quizzes/')", 30)
        with sqlite3.connect(root / "results.db") as conn:
            quiz = conn.execute("SELECT id,title FROM quizzes WHERE title='Completion Hotspot — Practice'").fetchone()
            question = conn.execute("SELECT id,question_text,media_json FROM questions WHERE quiz_id=?", (quiz[0],)).fetchone()
        out.update(quiz=quiz, question=question)
        out["pack_paths"] = [str(x.relative_to(root)) for x in (root / "content_packs").glob("*/manifest.json")]
        out["asset_hashes"] = {str(x.relative_to(root)): hashlib.sha256(x.read_bytes()).hexdigest()
                               for x in (root / "content_packs").glob("**/*") if x.is_file()}
        out["pass"] = (question[1] == "Find the synthetic target. [Image hotspot]" and
                       out["input_sha256"] in out["asset_hashes"].values()
                       and (a.reopen or out["stage_shape"]["center"] == [0.5, 0.5]))
        out["screenshot"] = str(q.screenshot("completion-hotspot-reopen.png" if a.reopen else "completion-hotspot.png", width=1000, height=800))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / ("completion-hotspot-reopen.json" if a.reopen else "completion-hotspot.json")).write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
