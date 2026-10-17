"""Separate-process Qt restart proves a precommit abort restored its preimage."""
from __future__ import annotations

import argparse
import json
import sqlite3
import traceback

from desktop.isolation import AREA
from desktop.maintenance import _digest, _file_inventory, run
from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--scope", required=True)
    p.add_argument("--checkpoint", required=True)
    a = p.parse_args()
    abort_file = AREA / "retained" / f"{a.profile}-abort-{a.checkpoint}.json"
    abort = json.loads(abort_file.read_text())
    marker = abort["marker"]
    q = QtChecks(a.profile, automated=True)
    out = {"profile": a.profile, "scope": a.scope, "checkpoint": a.checkpoint}
    try:
        original = AREA / "recovery" / a.profile / marker["operation_id"] / "backend"
        expected = _digest(_file_inventory(original))
        actual = _digest(_file_inventory(q.paths["backend"]))
        live_marker = AREA / "maintenance" / a.profile / "active.json"
        with sqlite3.connect(q.paths["backend"] / "results.db") as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            rows = {table: conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                    for table in ("quizzes", "questions", "choices", "study_sessions", "study_responses", "attempts")}
        repeat = run(a.profile, a.scope, marker["operation_id"])
        out.update(preimage_sha256=expected, active_sha256=actual,
                   marker_absent=not live_marker.exists(),
                   repeat_phase=repeat["phase"], integrity=integrity,
                   rows=rows, page=q.js("location.pathname"))
        out["pass"] = (actual == expected and out["marker_absent"] and
                       out["repeat_phase"] == "rolled_back" and integrity == "ok"
                       and out["page"] == "/" and rows["quizzes"] >= 1)
        out["screenshot"] = str(q.screenshot(f"completion-{a.scope}-rollback.png", width=950, height=720))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / f"completion-{a.scope}-rollback.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
