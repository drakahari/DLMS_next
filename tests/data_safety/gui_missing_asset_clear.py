"""Managed source clear with a deliberately pre-existing missing synthetic image."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import traceback

from desktop.isolation import AREA
from tests.gate1.qt_checks import QtChecks


def semantic(backend: Path):
    with sqlite3.connect(backend / "results.db") as conn:
        return {table: [list(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
                for table in ("quizzes", "questions", "choices", "attempts", "study_responses")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--phase", choices=("run", "reopen"), required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, automated=True)
    root, backend = q.paths["root"], q.paths["backend"]
    out = {"profile": args.profile, "phase": args.phase}
    try:
        prior = root / "data-safety-missing-asset-preimage.json"
        if args.phase == "run":
            assert (AREA / "retained" / f"{args.profile}-before").is_dir() and prior.is_file()
            before = json.loads(prior.read_text())
            assert semantic(backend) == before["semantic"]
            assert q.window.begin_maintenance("source", confirmed=True)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and q.window.maintenance_worker is not None:
                q.delay(.1)
            out["failure_message"] = q.window.failed_reason
            out["marker_present"] = (AREA / "maintenance" / args.profile / "active.json").exists()
            failure_shot = root / "data-safety-missing-asset-failure.png"
            q.window.resize(1000, 740)
            q.delay(0.3)
            assert q.window.grab().save(str(failure_shot))
            out["screenshot"] = str(failure_shot)
            out["pass"] = bool(out["failure_message"] and out["marker_present"])
        else:
            before = json.loads(prior.read_text())
            source = backend / "content_packs/DLMS_Study_legacy_pack/images/diagram.png"
            out["preexisting_missing_remains_missing"] = not source.exists()
            out["semantic_unchanged"] = semantic(backend) == before["semantic"]
            out["published_json_sha256"] = hashlib.sha256((backend / before["data_file"]).read_bytes()).hexdigest()
            out["marker_absent"] = not (AREA / "maintenance" / args.profile / "active.json").exists()
            out["pass"] = bool(out["preexisting_missing_remains_missing"] and out["semantic_unchanged"]
                               and out["published_json_sha256"] == before["data_sha256"] and out["marker_absent"])
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (root / f"data-safety-missing-asset-{args.phase}.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
