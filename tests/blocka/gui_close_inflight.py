"""A known in-flight Study action completes while the real Qt window closes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlsplit

from tests.gate1.qt_checks import QtChecks


def responses(db):
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT event_id,session_id,sequence,payload_json FROM study_responses ORDER BY saved_at,event_id").fetchall()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--phase", choices=("close", "reopen"), required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, pause_action="accepted" if args.phase == "close" else None)
    root = q.paths["root"]
    db = q.paths["backend"] / "results.db"
    result = {"phase": args.phase}
    try:
        url = urlsplit(json.loads((root / "foundation-create.json").read_text())["quiz_url"]).path
        q.go(url)
        if args.phase == "close":
            q.js("document.querySelector('.study-mode-btn').click(); true")
            q.wait("document.querySelector('button.choice') !== null")
            before = len(responses(db))
            q.js("document.querySelector('button.choice').click(); true")
            marker = root / "recovery-pause-accepted.json"
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not marker.exists(): q.delay(0.1)
            if not marker.exists(): raise TimeoutError("Accepted file was not reached")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(350, lambda: (root / "recovery-pause-release").write_text("release\n"))
            q.close()  # quiesce waits for the known promise, then drains, then checkpoints
            result.update(before=before, after=len(responses(db)),
                          action_id=json.loads(marker.read_text())["id"],
                          journal=[p.name for p in (root / "durable-actions").glob("*.json")],
                          evidence_present=(root / "recovery-evidence.json").exists())
            result["status"] = "pass" if result["after"] == before + 1 and not result["journal"] and result["evidence_present"] else "fail"
        else:
            expected = json.loads((root / "close-inflight-close.json").read_text())
            saved = responses(db)
            result.update(after=len(saved), identity_count=sum(row[0] == expected["action_id"] for row in saved),
                          journal=[p.name for p in (root / "durable-actions").glob("*.json")])
            result["status"] = "pass" if result["identity_count"] == 1 and not result["journal"] else "fail"
            q.close()
        (root / f"close-inflight-{args.phase}.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "pass" else 1
    finally:
        if q.window.isVisible(): q.close()


if __name__ == "__main__":
    raise SystemExit(main())
