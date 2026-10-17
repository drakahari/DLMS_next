"""Actual Qt backend managed-request authentication and legacy-route boundary."""
from __future__ import annotations

import argparse
import http.client
import json
from pathlib import Path
import traceback

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--profile", required=True)
    p.add_argument("--foreign-record", type=Path)
    args = p.parse_args()
    q = QtChecks(args.profile)
    report = {"profile": args.profile}
    try:
        port = q.window.port
        base = {"Host": f"127.0.0.1:{port}", "X-DLMS-Recovery-Client": "1"}
        def call(path, headers, method="GET"):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=8)
            conn.request(method, path, headers=headers)
            answer = conn.getresponse(); code = answer.status; data = answer.read(); conn.close()
            return code, data
        report["no_token"] = call("/_desktop/request/context", base)[0]
        authorized = {**base, "X-DLMS-Desktop-Token": q.window.nonce}
        report["wrong_host"] = call("/_desktop/request/context", {**authorized, "Host": "localhost:9001"})[0]
        report["evil_origin"] = call("/_desktop/request/context", {**authorized, "Origin": "https://elsewhere.invalid"})[0]
        report["null_origin"] = call("/settings/backup/create", {**authorized, "Origin": "null"}, "POST")[0]
        report["valid_context"] = call("/_desktop/request/context", authorized)[0]
        report["direct_source_create"] = call("/api/review-marks/generate", authorized, "POST")[0]
        report["source_restore"] = call("/settings/backup/restore/confirm", authorized, "POST")[0]
        if args.foreign_record:
            record = json.loads(args.foreign_record.read_text())
            body = json.dumps({"kind": record["kind"], "payload": record["payload"],
                               "context": record["context"]}).encode()
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=8)
            conn.request("POST", "/_desktop/request/status", body, headers={**authorized,
                "Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json"})
            answer = conn.getresponse(); report["foreign_context"] = answer.status
            answer.read(); conn.close()
        report["status"] = "pass" if ([report[k] for k in ("no_token", "wrong_host", "evil_origin",
            "null_origin", "valid_context", "direct_source_create", "source_restore")] == [403,403,403,403,200,409,409]
            and (not args.foreign_record or report["foreign_context"] == 409)) else "fail"
    except Exception as exc:
        report["status"] = "error"; report["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "blockb-request-boundary.json").write_text(json.dumps(report, indent=2) + "\n")
        q.close()
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
