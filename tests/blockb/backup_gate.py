"""Actual backend: abandoned backup response must release the Desktop gate."""
from __future__ import annotations

import argparse
import http.client
import json
from http.cookies import SimpleCookie
import traceback

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    args = p.parse_args()
    q = QtChecks(args.profile)
    result = {"profile": args.profile}
    try:
        opener = http.client.HTTPConnection("127.0.0.1", q.window.port, timeout=8)
        opener.request("GET", "/settings/backup", headers={
            "Host": f"127.0.0.1:{q.window.port}", "X-DLMS-Desktop-Token": q.window.nonce})
        page = opener.getresponse()
        cookies = SimpleCookie()
        for key, value in page.getheaders():
            if key.lower() == "set-cookie":
                cookies.load(value)
        page.read()
        opener.close()
        csrf = cookies["dlms_csrf_token"].value
        cookie = "; ".join(f"{name}={morsel.value}" for name, morsel in cookies.items())
        headers = {"Host": f"127.0.0.1:{q.window.port}",
                   "Origin": f"http://127.0.0.1:{q.window.port}",
                   "X-DLMS-Desktop-Token": q.window.nonce,
                   "X-CSRFToken": csrf, "Cookie": cookie,
                   "Content-Length": "0"}
        first = http.client.HTTPConnection("127.0.0.1", q.window.port, timeout=15)
        first.request("POST", "/settings/backup/create", headers=headers)
        first.close()  # no body read; Waitress must close the WSGI iterable
        second = http.client.HTTPConnection("127.0.0.1", q.window.port, timeout=20)
        second.request("POST", "/settings/backup/create", headers=headers)
        response = second.getresponse()
        result["second_status"] = response.status
        result["second_zip"] = response.read(2) == b"PK"
        second.close()
        context = http.client.HTTPConnection("127.0.0.1", q.window.port, timeout=8)
        context.request("GET", "/_desktop/request/context", headers={
            "Host": headers["Host"], "X-DLMS-Desktop-Token": q.window.nonce,
            "X-DLMS-Recovery-Client": "1"})
        response = context.getresponse()
        result["context_status"] = response.status
        response.read()
        context.close()
        result["status"] = "pass" if result["second_status"] == 200 and result["second_zip"] and result["context_status"] == 200 else "fail"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "blockb-backup-gate.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
