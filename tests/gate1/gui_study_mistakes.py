"""Create one schema-12 Study mistakes pass and batch in the Qt window."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import traceback

from tests.gate1.qt_checks import QtChecks


def content_hashes(root: Path):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for folder in ("data", "quizzes") for path in (root / folder).glob("*")
            if path.is_file() and not path.name.startswith("parse_log_")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    result = {}
    try:
        root = q.paths["backend"]
        original = content_hashes(root)
        quiz_id = json.loads((q.paths["root"] / "foundation-create.json").read_text())["quiz_id"]
        q.go(f"/quiz-composer/study-mistakes?quizzes={quiz_id}")
        result["eligible_text"] = q.js("document.getElementById('mistakeCounts').innerText")
        result["source_preview"] = q.js("document.querySelector('#studyMistakeResults .study-mistakes-preview')?.innerText || ''")
        result["start_enabled"] = q.js("!document.getElementById('startMistakePass').disabled")
        if not result["start_enabled"]:
            raise RuntimeError("No verified Study mistake eligible for a pass")
        q.js("document.getElementById('startMistakePass').click(); true")
        q.wait("document.getElementById('createMistakeMix') && !document.getElementById('createMistakeMix').disabled", 20)
        result["pass_before"] = q.js("document.getElementById('mistakePassSummary').innerText")
        q.js("document.getElementById('mistakeTitle').value='Gate 1 Mistake Batch'; document.getElementById('mistakeCount').value='1'; document.getElementById('createMistakeMix').click(); true")
        q.wait("document.getElementById('openMistakeMix') && !document.getElementById('openMistakeMix').hidden", 20)
        result["saved_message"] = q.js("document.getElementById('mistakeStatus').innerText")
        result["pass_after"] = q.js("document.getElementById('mistakePassSummary').innerText")
        result["batch_link"] = q.js("document.getElementById('openMistakeMix').getAttribute('href')")
        result["screenshot"] = str(q.screenshot("study-mistakes-pass.png"))
        with sqlite3.connect(root / "results.db") as conn:
            result["schema"] = conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()[0]
            result["saved_batch_count"] = conn.execute("SELECT count(*) FROM quizzes WHERE title='Gate 1 Mistake Batch'").fetchone()[0]
            result["pass_rows"] = conn.execute("SELECT count(*) FROM study_mistake_passes").fetchone()[0]
            result["member_rows"] = conn.execute("SELECT count(*) FROM study_mistake_members").fetchone()[0]
        after = content_hashes(root)
        result["original_content_unchanged"] = all(after.get(k) == v for k, v in original.items())
        result["status"] = "pass" if result["schema"] == 12 and result["saved_batch_count"] == 1 and result["original_content_unchanged"] else "fail"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "mistake-evidence.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
