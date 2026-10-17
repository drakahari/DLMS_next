"""Compare every portable row and asset against an adopted synthetic archive."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import zipfile

from desktop.isolation import AREA, profile_paths

EPOCH_STATES = {"certification_state", "exam_plan_state", "review_mark_state",
                "study_mistake_state", "study_state"}
REQUIRED = {"quizzes", "questions", "attempts", "study_responses", "study_mistake_actions",
            "study_mistake_members", "review_marks", "review_mark_actions",
            "certifications", "certification_cycles", "certification_training",
            "certification_allocations", "certification_attachments"}


def rows(conn, table):
    names = [column[1] for column in conn.execute(f'PRAGMA table_info("{table}")')]
    order = ",".join(f'"{name}"' for name in names)
    return sorted(tuple(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY {order}'))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--archive", type=Path, required=True)
    args = p.parse_args()
    paths = profile_paths(args.profile)
    report = {"profile": args.profile, "archive": str(args.archive)}
    with zipfile.ZipFile(args.archive) as z, tempfile.TemporaryDirectory(dir=AREA) as temporary:
        names = {name for name in z.namelist() if name.startswith("DLMS_DATA/")}
        restored = Path(temporary) / "archive.db"
        restored.write_bytes(z.read("DLMS_DATA/results.db"))
        with sqlite3.connect(restored) as source, sqlite3.connect(paths["backend"] / "results.db") as target:
            tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            compared = sorted(tables - EPOCH_STATES)
            report["row_mismatches"] = [name for name in compared if rows(source, name) != rows(target, name)]
            report["required_counts"] = {name: len(rows(source, name)) for name in sorted(REQUIRED)}
            report["schema"] = target.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()[0]
            report["epoch_state_changes"] = sorted(name for name in EPOCH_STATES if rows(source, name) != rows(target, name))
        report["asset_mismatches"] = []
        for name in sorted(names - {"DLMS_DATA/results.db"}):
            if name.endswith("/"):
                continue
            relative = name.removeprefix("DLMS_DATA/")
            disk = paths["backend"] / relative
            if (not disk.is_file() or disk.is_symlink() or
                    hashlib.sha256(z.read(name)).digest() != hashlib.sha256(disk.read_bytes()).digest()):
                report["asset_mismatches"].append(relative)
        report["archive_sha256"] = hashlib.sha256(args.archive.read_bytes()).hexdigest()
        copies = list((paths["root"] / "imports").glob("*.zip"))
        report["preserved_input_copy"] = any(hashlib.sha256(item.read_bytes()).hexdigest() == report["archive_sha256"] for item in copies)
    report["target_pending_records"] = len(list((paths["root"] / "pending-requests").glob("*.json")))
    report["target_accepted_actions"] = len(list((paths["root"] / "durable-actions").glob("*.json")))
    report["status"] = "pass" if (report["schema"] == 12 and not report["row_mismatches"]
        and not report["asset_mismatches"] and report["preserved_input_copy"]
        and report["target_pending_records"] == report["target_accepted_actions"] == 0
        and all(report["required_counts"].values())) else "fail"
    (paths["root"] / "blockb-data-comparison.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
