"""Deterministic real-Qt process-crash checkpoints for the two durable actions."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import time
from urllib.parse import urlsplit

from tests.gate1.qt_checks import QtChecks


def rows(db: Path, kind: str):
    with sqlite3.connect(db) as conn:
        if kind == "study":
            return [dict(zip(("event_id", "sequence", "payload_json"), row)) for row in
                    conn.execute("SELECT event_id,sequence,payload_json FROM study_responses WHERE kind='response' ORDER BY sequence,event_id")]
        columns = {row[1] for row in conn.execute("PRAGMA table_info(attempts)")}
        identity = "attempt_id" if "attempt_id" in columns else "id"
        return [dict(zip(("attempt_id", "score", "total"), row)) for row in
                conn.execute(f"SELECT CAST({identity} AS TEXT),score,total FROM attempts ORDER BY id")]


def source_hashes(backend: Path):
    with sqlite3.connect(backend / "results.db") as conn:
        content = [list(conn.execute(f"SELECT * FROM {table} ORDER BY id")) for table in ("questions", "choices")]
    hashed = {"db_questions_choices": hashlib.sha256(json.dumps(content, default=str).encode()).hexdigest()}
    for folder in ("data", "quizzes"):
        for path in sorted((backend / folder).glob("quiz_*")):
            hashed[str(path.relative_to(backend))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--kind", choices=("study", "exam"), required=True)
    parser.add_argument("--phase", choices=("accepted", "committed", "cleanup", "reopen"), required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, pause_action=args.phase if args.phase in {"accepted", "committed"} else None,
                 fail_action_cleanup=args.phase == "cleanup")
    root = q.paths["root"]
    db = q.paths["backend"] / "results.db"
    result = {"kind": args.kind, "phase": args.phase}
    try:
        url = urlsplit(json.loads((root / "foundation-create.json").read_text())["quiz_url"]).path
        if args.phase == "reopen":
            result["source_hashes_after"] = source_hashes(q.paths["backend"])
            result["rows_after"] = rows(db, args.kind)
            result["journal_after"] = [p.name for p in (root / "durable-actions").glob("*.json")]
            q.go(url)
            result["resume_present"] = bool(q.js("!!document.querySelector('.quiz-recovery-resume, #durableStudyResume')"))
            result["browser_retry"] = False
            # The fixture's first Study response leaves a Study Resume panel.
            # It is not evidence of an Exam browser queue after a crash.
            if args.kind == "study" and q.js("!!document.querySelector('.quiz-recovery-resume')"):
                q.js("document.querySelector('.quiz-recovery-resume').click(); true")
                q.wait("studyLearningEventSaves.size === 0", 20)
                result["browser_retry"] = True
            result["rows_after_browser_retry"] = rows(db, args.kind)
            result["screenshot"] = str(q.screenshot(f"{args.kind}-{args.phase}.png"))
            expected = json.loads((root / f"{args.kind}-{json.loads((root / 'crash-checkpoint.json').read_text())['phase']}.json").read_text())
            identifier = expected["id"]
            key = "event_id" if args.kind == "study" else "attempt_id"
            result["identity_count"] = sum(row[key] == identifier for row in result["rows_after"])
            result["status"] = "pass" if (result["identity_count"] == 1 and not result["journal_after"]
                                            and len(result["rows_after_browser_retry"]) == len(result["rows_after"])
                                            and result["source_hashes_after"] == expected["source_hashes_at_crash"]) else "fail"
        else:
            q.go(url)
            if q.js("!!document.querySelector('.quiz-recovery-start-over')"):
                q.js("window.confirm=()=>true; document.querySelector('.quiz-recovery-start-over').click(); true")
                q.wait("document.querySelector('.quiz-recovery-panel')?.hidden === true")
            result["rows_before"] = rows(db, args.kind)
            if args.kind == "study":
                q.js("document.querySelector('.study-mode-btn').click(); true")
                q.wait("document.querySelector('button.choice') !== null")
                q.js("document.querySelector('button.choice').click(); true")
            else:
                q.js("document.querySelector('.exam-mode-btn').click(); true")
                q.wait("document.querySelector('button.choice') !== null")
                q.js("document.querySelector('button.choice').click(); true")
                q.js("window.confirm=()=>true; document.getElementById('submitBtn').click(); true")
            if args.phase == "cleanup":
                q.wait("document.body.innerText.includes('cleanup is pending') || document.body.innerText.includes('cleanup is pending and will retry')", 20)
                files = list((root / "durable-actions").glob("*.json"))
                if len(files) != 1:
                    raise AssertionError("Committed action did not retain its cleanup-failure file")
                result["id"] = json.loads(files[0].read_text())["id"]
            else:
                marker = root / f"recovery-pause-{args.phase}.json"
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline and not marker.exists():
                    q.delay(0.1)
                if not marker.exists():
                    raise TimeoutError(f"Backend did not reach {args.phase} checkpoint")
                result.update(json.loads(marker.read_text()))
            result["rows_at_crash"] = rows(db, args.kind)
            result["source_hashes_at_crash"] = source_hashes(q.paths["backend"])
            result["journal_at_crash"] = [p.name for p in (root / "durable-actions").glob("*.json")]
            result["screenshot"] = str(q.screenshot(f"{args.kind}-{args.phase}.png"))
            result["status"] = "pass" if len(result["journal_at_crash"]) == 1 else "fail"
            (root / f"{args.kind}-{args.phase}.json").write_text(json.dumps(result, indent=2) + "\n")
            (root / "crash-checkpoint.json").write_text(json.dumps({"kind": args.kind, "phase": args.phase}) + "\n")
            print(json.dumps(result, indent=2), flush=True)
            if result["status"] == "pass" and args.phase != "cleanup":
                os.kill(os.getpid(), signal.SIGKILL)  # only this disposable Qt launcher
            if args.phase == "cleanup":
                q.close()
                return 0 if result["status"] == "pass" else 1
            return 1
    finally:
        if args.phase == "reopen":
            (root / f"{args.kind}-reopen.json").write_text(json.dumps(result, indent=2) + "\n")
            q.close()
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
