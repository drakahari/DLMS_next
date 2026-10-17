"""Synthetic epoch or assessment-revision mismatch quarantines accepted evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3

from desktop.isolation import profile_paths
from desktop.profile_state import synthetic_epoch_change
from tests.gate1.qt_checks import QtChecks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--kind", choices=("study", "exam"), required=True)
    parser.add_argument("--mismatch", choices=("epoch", "revision"), required=True)
    parser.add_argument("--phase", choices=("mutate", "reopen"), required=True)
    parser.add_argument("--committed", action="store_true", help="the paused action committed before source edit")
    args = parser.parse_args()
    paths = profile_paths(args.profile)
    root = paths["root"]
    record_file = next((root / "durable-actions").glob("*.json")) if args.phase == "mutate" else None
    if args.phase == "mutate":
        record = json.loads(record_file.read_text())
        if args.mismatch == "epoch":
            old = json.loads((root / "desktop-profile.json").read_text())
            updated = synthetic_epoch_change(paths, args.profile)
            assert old["epoch"] != updated["epoch"]
        else:
            with sqlite3.connect(paths["backend"] / "results.db") as conn:
                conn.execute("UPDATE questions SET question_text=question_text || ' [synthetic revision]' WHERE quiz_id=? AND question_number=1", (record["payload"]["quizId"],))
                conn.commit()
        result = {"phase": "mutate", "kind": args.kind, "mismatch": args.mismatch,
                  "accepted_record_hash": hashlib.sha256(record_file.read_bytes()).hexdigest(),
                  "id": record["id"]}
    else:
        q = QtChecks(args.profile)
        try:
            db = paths["backend"] / "results.db"
            with sqlite3.connect(db) as conn:
                table, column = ("study_responses", "event_id") if args.kind == "study" else ("attempts", "id")
                target = json.loads((root / "stale-mutate.json").read_text())["id"]
                count = conn.execute(f"SELECT count(*) FROM {table} WHERE {column}=?", (target,)).fetchone()[0]
            quarantine = list((root / "durable-actions-quarantine").glob("*.json"))
            result = {"phase": "reopen", "kind": args.kind, "mismatch": args.mismatch,
                      "durable_identity_count": count, "quarantine": [p.name for p in quarantine],
                      "live_records": [p.name for p in (root / "durable-actions").glob("*.json")]}
            if args.committed:
                result["status"] = "pass" if count == 1 and not quarantine and not result["live_records"] else "fail"
            else:
                result["status"] = "pass" if count == 0 and len(quarantine) == 1 and not result["live_records"] else "fail"
        finally:
            q.close()
    (root / f"stale-{args.phase}.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result.get("status", "pass") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
