"""Read-only exact-ID status after a synthetic source edit and lost output."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import threading

from desktop.backend import acquire_writer_lock
from desktop.isolation import PROJECT, isolated_environment, profile_paths
from desktop.profile_state import read_manifest


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    args = p.parse_args()
    paths = profile_paths(args.profile)
    manifest = read_manifest(paths, args.profile)
    env = isolated_environment(paths)
    env.update(PYTHONPATH=os.pathsep.join((str(PROJECT), str(PROJECT))),
               PYTHONNOUSERSITE="1", DLMS_DESKTOP_PROFILE_NAME=args.profile,
               DLMS_DESKTOP_PORT=str(manifest["port"]), DLMS_DESKTOP_NONCE="0" * 32)
    os.environ.clear()
    os.environ.update(env)
    lock = acquire_writer_lock(paths["root"] / "backend-writer.lock")
    try:
        sys.path.insert(0, str(PROJECT))
        import app
        from desktop.requests import PendingRequests
        pending = PendingRequests(paths, args.profile, app, threading.RLock())
        with app.get_db() as conn:
            row = conn.execute("SELECT request_id,input_json,quiz_id FROM study_mistake_actions WHERE state='published' ORDER BY request_id LIMIT 1").fetchone()
            payload = json.loads(row["input_json"])
            source = conn.execute("SELECT id,question_text FROM questions WHERE quiz_id=? ORDER BY id LIMIT 1", (payload["scope"]["quizzes"][0],)).fetchone()
        envelope = {"kind": "study_mistakes", "payload": payload, "context": pending.context()}
        first = pending.status(envelope)
        with app.get_db() as conn:
            conn.execute("UPDATE questions SET question_text=? WHERE id=?", ("Synthetic source edit", source["id"]))
            conn.commit()
        try:
            after_edit = pending.status(envelope)
            changed = json.loads(json.dumps(envelope))
            changed["payload"]["title"] = "Different immutable payload"
            stale = pending.status(changed)
            entry = next(item for item in app.load_registry() if item["id"] == row["quiz_id"])
            html, _data = app._quiz_artifact_names(entry)
            artifact = Path(app.QUIZ_FOLDER) / html
            output = artifact.read_bytes()
            artifact.unlink()
            try:
                missing = pending.status(envelope)
                missing_again = pending.status(envelope)
            finally:
                artifact.write_bytes(output)
        finally:
            with app.get_db() as conn:
                conn.execute("UPDATE questions SET question_text=? WHERE id=?", (source["question_text"], source["id"]))
                conn.commit()
        result = {"first": first, "after_source_edit": after_edit,
                  "changed_payload": stale, "missing_output": missing,
                  "missing_output_repeat": missing_again}
        result["status"] = "pass" if ([v["state"] for v in (first, after_edit, stale, missing, missing_again)]
            == ["committed", "committed", "stale", "unknown", "unknown"]
            and first["request_id"] == after_edit["request_id"]) else "fail"
        (paths["root"] / "blockb-status-matrix.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "pass" else 1
    finally:
        lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
