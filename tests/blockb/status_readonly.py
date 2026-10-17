"""Committed Review practice status must not repair or create portal.json."""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import traceback

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    args = p.parse_args()
    q = QtChecks(args.profile)
    result = {"profile": args.profile}
    portal = q.paths["backend"] / "config" / "portal.json"
    original = portal.read_bytes()
    try:
        record = next(json.loads(path.read_text()) for path in
                      (q.paths["root"] / "pending-requests").glob("*.json")
                      if json.loads(path.read_text())["kind"] == "review_generate")
        envelope = {"kind": record["kind"], "payload": record["payload"],
                    "context": record["context"]}
        portal.write_bytes(b"{ malformed synthetic portal config")
        before = hashlib.sha256(portal.read_bytes()).hexdigest()
        wire = json.dumps(envelope).encode()
        conn = http.client.HTTPConnection("127.0.0.1", q.window.port, timeout=8)
        conn.request("POST", "/_desktop/request/status", wire, headers={
            "Host": f"127.0.0.1:{q.window.port}",
            "Origin": f"http://127.0.0.1:{q.window.port}",
            "Content-Type": "application/json", "Content-Length": str(len(wire)),
            "X-DLMS-Desktop-Token": q.window.nonce,
            "X-DLMS-Recovery-Client": "1"})
        response = conn.getresponse()
        result["http"] = response.status
        result["status_body"] = json.loads(response.read())
        conn.close()
        result["portal_unchanged"] = hashlib.sha256(portal.read_bytes()).hexdigest() == before
        result["status"] = "pass" if (result["http"] == 200 and
            result["status_body"]["state"] == "committed" and result["portal_unchanged"]) else "fail"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        portal.write_bytes(original)
        (q.paths["root"] / "blockb-status-readonly.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
