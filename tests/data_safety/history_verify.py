"""Verify saved Study/Exam facts and historical image after managed source clear."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import traceback

from tests.gate1.qt_checks import QtChecks


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    root, backend = q.paths["root"], q.paths["backend"]
    before = json.loads((root / "data-safety-history-before.json").read_text())
    seed = json.loads((root / "closure-source-legacy-seed.json").read_text())
    out = {"profile": args.profile}
    try:
        with sqlite3.connect(backend / "results.db") as conn:
            study = [list(row) for row in conn.execute("SELECT event_id,session_id,sequence,payload_json FROM study_responses WHERE kind='response' ORDER BY saved_at,event_id")]
            attempts = [list(row) for row in conn.execute("SELECT * FROM attempts ORDER BY id")]
            answers = [list(row) for row in conn.execute("SELECT * FROM attempt_answers ORDER BY id")]
            events = [list(row) for row in conn.execute("SELECT * FROM learning_events ORDER BY id")]
            missed = [list(row) for row in conn.execute("SELECT * FROM missed_questions ORDER BY id")]
            questions = [list(row) for row in conn.execute("SELECT * FROM questions ORDER BY id")]
            choices = [list(row) for row in conn.execute("SELECT * FROM choices ORDER BY id")]
        assert study == before["study"] and attempts == before["attempts"] and answers == before["answers"]
        assert events == before["events"] and missed == before["missed"]
        assert choices == before["choices"]
        assert [row[:13] + row[14:] for row in questions] == [row[:13] + row[14:] for row in before["questions"]]
        assert len(questions) == len(before["questions"])
        assert questions[0][13] != before["questions"][0][13]
        db_url = json.loads(questions[0][13])["image_url"]
        runtime = json.loads((backend / seed["data_file"]).read_text())
        runtime_url = runtime[0]["image_url"]
        assert db_url.startswith("/quiz-assets/") and runtime_url.startswith("/quiz-assets/")
        def asset(url):
            return backend / "quiz_assets" / url.removeprefix("/quiz-assets/")
        assert sha(asset(db_url)) == sha(asset(runtime_url)) == before["legacy_sha"]
        assert not (backend / "content_packs/DLMS_Study_legacy_pack").exists()
        assert {rel: sha(backend / rel) for rel in seed["protected_files"]} == seed["protected_files"]
        q.go("/quizzes/" + before["quiz_html"])
        q.js("document.querySelector('.study-mode-btn').click();true")
        q.wait("document.querySelector('.question-media-image')?.naturalWidth > 0", 20)
        image_src = q.js("document.querySelector('.question-media-image').getAttribute('src')")
        assert image_src == runtime_url
        q.go("/study-history")
        study_text = q.js("document.body.innerText")
        assert "Closure Published Legacy" in study_text
        q.go("/history?attempt=" + attempts[0][0])
        q.wait("document.querySelector('.history-result-row.selected') !== null", 15)
        exam_text = q.js("document.querySelector('.history-result-row.selected').innerText")
        assert "Closure Published Legacy" in exam_text
        out.update(study_count=len(study), exam_count=len(attempts), choice_count=len(choices),
                   study_id=study[0][0], attempt_id=attempts[0][0],
                   runtime_url=runtime_url, db_url=db_url, asset_sha256=before["legacy_sha"],
                   study_history_visible=True, exam_history_visible=True,
                   screenshot=str(q.screenshot("data-safety-history-after.png", width=1030, height=760)),
                   pass_=True)
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        out["pass"] = out.pop("pass_", False)
        (root / "data-safety-history-after.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
