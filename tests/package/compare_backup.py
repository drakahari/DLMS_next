"""Read-only semantic/asset comparison for one packaged synthetic adoption."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import zipfile

EPOCH_STATES = {"certification_state", "exam_plan_state", "review_mark_state",
                "study_mistake_state", "study_state"}


def rows(conn: sqlite3.Connection, table: str):
    columns = [item[1] for item in conn.execute(f'PRAGMA table_info("{table}")')]
    ordering = ",".join(f'"{column}"' for column in columns)
    return sorted(tuple(item) for item in conn.execute(f'SELECT * FROM "{table}" ORDER BY {ordering}'))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    backend = args.target / "backend"
    with zipfile.ZipFile(args.archive) as archive, tempfile.TemporaryDirectory(dir=args.output.parent) as temporary:
        source_db = Path(temporary) / "archive.db"
        source_db.write_bytes(archive.read("DLMS_DATA/results.db"))
        with sqlite3.connect(source_db) as source, sqlite3.connect(backend / "results.db") as target:
            tables = {row[0] for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            compared = sorted(tables - EPOCH_STATES)
            row_mismatches = [name for name in compared if rows(source, name) != rows(target, name)]
            counts = {name: len(rows(target, name)) for name in
                      ("quizzes", "questions", "choices", "study_responses", "attempts")}
            schema = target.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()[0]
        assets = {}
        mismatches = []
        for name in archive.namelist():
            if not name.startswith("DLMS_DATA/") or name.endswith("/") or name == "DLMS_DATA/results.db":
                continue
            relative = Path(name.removeprefix("DLMS_DATA/"))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"Unsafe member in tested archive: {name}")
            expected = sha(archive.read(name))
            found = backend / relative
            actual = sha(found.read_bytes()) if found.is_file() and not found.is_symlink() else None
            assets[str(relative)] = {"expected": expected, "actual": actual}
            if actual != expected:
                mismatches.append(str(relative))
    archive_hash = sha(args.archive.read_bytes())
    copies = list((args.target / "imports").glob("*.zip"))
    preserved = any(sha(path.read_bytes()) == archive_hash for path in copies)
    pending = len(list((args.target / "pending-requests").glob("*.json")))
    actions = len(list((args.target / "durable-actions").glob("*.json")))
    report = {"schema": schema, "table_count": len(compared), "row_mismatches": row_mismatches,
              "counts": counts, "assets": assets, "asset_mismatches": mismatches,
              "preserved_input_copy": preserved, "pending_requests": pending,
              "durable_actions": actions, "archive_sha256": archive_hash}
    report["pass"] = (schema == 12 and counts["quizzes"] >= 1 and counts["study_responses"] >= 1
                      and not row_mismatches and not mismatches and preserved and pending == actions == 0)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "assets"}, indent=2))
    if not report["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
