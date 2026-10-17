"""Portable snapshot refuses accepted, unsettled Desktop requests."""
from __future__ import annotations

import argparse
import http.client
import json

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--profile", required=True)
    args = p.parse_args()
    q = QtChecks(args.profile)
    try:
        pending = q.paths["root"] / "pending-requests"
        before = len(list(pending.glob("*.json")))
        backups = q.paths["backend"] / "backups"
        count = len(list(backups.glob("*.zip")))
        conn = http.client.HTTPConnection("127.0.0.1", q.window.port, timeout=8)
        conn.request("POST", "/settings/backup/create", headers={
            "Host": f"127.0.0.1:{q.window.port}",
            "Origin": f"http://127.0.0.1:{q.window.port}",
            "X-DLMS-Desktop-Token": q.window.nonce, "Content-Length": "0"})
        answer = conn.getresponse(); code = answer.status; body = answer.read().decode(); conn.close()
        result = {"profile": args.profile, "pending_before": before,
                  "pending_after": len(list(pending.glob("*.json"))),
                  "backups_before": count, "backups_after": len(list(backups.glob("*.zip"))),
                  "http": code, "message": body}
        result["status"] = "pass" if (before > 0 and result["pending_after"] == before
            and result["backups_after"] == count and code == 409) else "fail"
        (q.paths["root"] / "blockb-backup-refusal.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "pass" else 1
    finally:
        q.close()


if __name__ == "__main__":
    raise SystemExit(main())
