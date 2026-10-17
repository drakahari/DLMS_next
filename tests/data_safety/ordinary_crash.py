"""Exact-process interruption after the first ordinary-bundle quiz publishes."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

from desktop.backend import acquire_writer_lock
from desktop.isolation import AREA, PROJECT, isolated_environment, profile_paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--phase", choices=("crash", "inspect"), required=True)
    args = parser.parse_args()
    assert args.profile.startswith("datasafety")
    paths = profile_paths(args.profile)
    env = isolated_environment(paths)
    os.environ.clear()
    os.environ.update(env)
    os.environ["PYTHONNOUSERSITE"] = "1"
    # This isolated service-level child has no launcher socket. Keep the same
    # project-local data root but do not falsely claim Desktop port ownership.
    os.environ.pop("DLMS_DESKTOP_PROFILE", None)
    lock = acquire_writer_lock(paths["root"] / "backend-writer.lock")
    sys.path.insert(0, str(PROJECT))
    import app as dlms
    root, backend = paths["root"], paths["backend"]
    if args.phase == "crash":
        from werkzeug.datastructures import FileStorage
        archive = AREA / "fixtures/data-safety-two.zip"
        assert archive.is_file()
        with archive.open("rb") as stream:
            upload = FileStorage(stream=stream, filename="synthetic-portable.zip", content_type="application/zip")
            token = dlms._portable_quiz_bundle_service.stage_portable_quiz_bundle(
                upload, content_length=None, staging_folder=dlms.PORTABLE_QUIZ_BUNDLE_STAGING_FOLDER,
                bounded_save_upload=dlms._bounded_save_upload,
                inspect_bundle=dlms._inspect_portable_quiz_bundle,
                secure_filename=dlms.secure_filename)
        (root / "data-safety-ordinary-token.txt").write_text(token + "\n")
        original = dlms._publish_quiz
        calls = 0

        def after_first(*values, **options):
            nonlocal calls
            published = original(*values, **options)
            calls += 1
            if calls == 1:
                checkpoint = {"phase": "first_quiz_published_before_receiver_ack", "pid": os.getpid(),
                              "token": token, "quiz_id": published[0], "title": values[0]}
                from desktop.profile_state import atomic_json
                atomic_json(root / "data-safety-ordinary-checkpoint.json", checkpoint)
                os._exit(71)  # exact test-owned child; no broad process signaling
            return published

        dlms._publish_quiz = after_first
        dlms._install_staged_portable_quiz_bundle(token)
        raise AssertionError("Synthetic checkpoint was not reached")
    else:
        token = (root / "data-safety-ordinary-token.txt").read_text().strip()
        with sqlite3.connect(backend / "results.db") as conn:
            quizzes = [list(row) for row in conn.execute("SELECT id,title,source_file FROM quizzes ORDER BY id")]
            counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("questions", "choices", "matching_pairs")}
        registry = json.loads((backend / "config/quizzes.json").read_text())
        files = {folder: sorted(path.relative_to(backend / folder).as_posix()
                                for path in (backend / folder).rglob("*") if path.is_file())
                 for folder in ("data", "quizzes", "quiz_assets", "uploads/quiz_bundles", ".quiz_publications")}
        report = {"profile": args.profile, "phase": "inspect", "checkpoint": json.loads((root / "data-safety-ordinary-checkpoint.json").read_text()),
                  "quizzes": quizzes, "counts": counts, "registry": registry, "files": files,
                  "stage_token_exists": (backend / "uploads/quiz_bundles" / token / "stage.json").is_file()}
        (root / "data-safety-ordinary-inspect.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        lock.close()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
