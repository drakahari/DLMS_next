"""Verify copied in-app shutdown closes the owning Qt window cleanly."""
from __future__ import annotations

import json
import socket
import time

from tests.gate1.qt_checks import QtChecks


def port_open():
    with socket.socket() as sock:
        sock.settimeout(0.1)
        return sock.connect_ex(("127.0.0.1", 9001)) == 0


def main():
    q = QtChecks("shutdown01")
    q.js("window.confirm=()=>true; document.getElementById('shutdownBtn').click(); true")
    until = time.monotonic() + 8
    while q.window.isVisible() and time.monotonic() < until:
        q.delay(0.1)
    result = {"window_closed": not q.window.isVisible(),
              "backend_exited": q.window.backend.poll() is not None,
              "port_closed": not port_open(), "failure": q.window.failed_reason}
    result["status"] = "pass" if result["window_closed"] and result["backend_exited"] and result["port_closed"] and not result["failure"] else "fail"
    (q.paths["root"] / "shutdown-evidence.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
