"""Read-only semantic and hash audit after a Qt same-operation retry."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

from desktop.backend import acquire_writer_lock
from desktop.isolation import AREA, PROJECT, isolated_environment, profile_paths


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def sentinel(backend):
    with sqlite3.connect(backend / "results.db") as conn:
        conn.row_factory = sqlite3.Row
        quiz = conn.execute("SELECT id,title,source_file FROM quizzes WHERE title='Unrelated Sentinel'").fetchone()
        assert quiz
        question = conn.execute("SELECT id,question_number,question_text,question_type FROM questions WHERE quiz_id=?", (quiz["id"],)).fetchall()
        answers = [list(row) for row in conn.execute("SELECT id,label,text,is_correct,choice_order FROM choices WHERE question_id=? ORDER BY choice_order,id", (question[0]["id"],))]
    registry = json.loads((backend / "config/quizzes.json").read_text())
    entry = next(row for row in registry if row["id"] == quiz["id"])
    html = backend / "quizzes" / entry["html"]
    data = backend / "data" / entry["html"].replace(".html", ".json")
    return {"quiz": list(quiz), "question": [list(row) for row in question],
            "answers": answers, "registry": entry,
            "html_sha256": digest(html), "json_sha256": digest(data)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--label", default="before")
    args = parser.parse_args()
    paths = profile_paths(args.profile, create=False)
    root, backend = paths["root"], paths["backend"]
    retained = AREA / "retained" / (args.profile + "-" + args.label) / "backend"
    before = sentinel(retained)
    after = sentinel(backend)
    assert before == after, "unrelated sentinel changed"
    env = isolated_environment(paths)
    os.environ.clear(); os.environ.update(env)
    manifest = json.loads((root / "desktop-profile.json").read_text())
    os.environ.update(DLMS_DESKTOP_NONCE="a"*32, DLMS_DESKTOP_PORT=str(manifest["port"]), PYTHONNOUSERSITE="1")
    lock = acquire_writer_lock(root / "backend-writer.lock")
    sys.path.insert(0, str(PROJECT))
    import app
    from desktop import import_operations as operations
    token = (root / "gate-a-token.txt").read_text().strip()
    op = operations._read(operations._file(root, manifest["epoch"], token))
    assert op["state"] == "complete"
    archive = retained / "uploads" / "quiz_bundles" / token / "bundle.zip"
    assert digest(archive) == op["archive_sha256"]
    report = app._inspect_portable_quiz_bundle(str(archive))
    receipts = []
    for item in op["items"]:
        receipt = item["receipt"]
        html = receipt["html"]
        journal = {"quiz": {"id": receipt["quiz_id"]}, "registry": {"html": html},
                   "artifacts": {"assets": {"name": html[:-5]}}, "owned_logo": receipt["logo"]}
        output = {"json": str(backend / "data" / (html[:-5] + ".json")),
                  "html": str(backend / "quizzes" / html),
                  "assets": str(backend / "quiz_assets" / html[:-5])}
        current = operations._verify_committed(app, op, item, journal, output,
                                               report_override=report)
        assert current == receipt
        receipts.append({"id": receipt["quiz_id"], "html": html, "hashes": receipt["hashes"],
                         "record_ids": receipt["record_ids"]})
    assert not list((backend / ".quiz_publications").glob("publication_*.json"))
    assert not list((backend / "quiz_assets").glob("portable_import_*"))
    assert not (backend / "uploads" / "quiz_bundles" / token).exists()
    output = {"profile": args.profile, "pass": True, "unrelated_unchanged": True,
              "items": receipts, "operation_state": op["state"]}
    (root / "gate-a-audit.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))
    lock.close()


if __name__ == "__main__":
    main()
