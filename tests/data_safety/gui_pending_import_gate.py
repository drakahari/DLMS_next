"""An accepted incomplete import blocks backup and managed maintenance."""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json

from PySide6.QtWidgets import QMessageBox

from desktop.maintenance import read_marker
from tests.gate1.qt_checks import QtChecks


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    assert args.profile.startswith("datasafety")
    q = QtChecks(args.profile, automated=True)
    root, backend = q.paths["root"], q.paths["backend"]
    token = (root / "gate-a-token.txt").read_text().strip()
    db = backend / "results.db"
    before = digest(db)
    old_warning = QMessageBox.warning
    result = {"profile": args.profile, "db_before": before}
    try:
        warnings = []
        QMessageBox.warning = staticmethod(lambda *a, **kw: warnings.append(a[2]) or QMessageBox.StandardButton.Ok)
        connection = http.client.HTTPConnection("127.0.0.1", q.window.port, timeout=8)
        connection.request("POST", "/settings/backup/create", headers={
            "Host": f"127.0.0.1:{q.window.port}",
            "Origin": f"http://127.0.0.1:{q.window.port}",
            "X-DLMS-Desktop-Token": q.window.nonce, "Content-Length": "0",
        })
        response = connection.getresponse()
        result["backup_http"] = response.status
        result["backup_message"] = response.read().decode(errors="replace")
        connection.close()
        result["maintenance_started"] = q.window.begin_maintenance("exam", confirmed=True)
        result["warnings"] = warnings
        result["db_after"] = digest(db)
        result["marker"] = read_marker(args.profile)
        op = next((root / "portable-import-operations").rglob(token + ".json"))
        result["operation"] = json.loads(op.read_text())["state"]
        q.go("/quiz-bundles/import/" + token)
        result["screenshot"] = str(q.screenshot("gate-a-pending-gate.png", width=1050, height=780))
        assert (result["backup_http"] == 409 and result["maintenance_started"] is False
                and result["db_before"] == result["db_after"] and result["marker"] is None
                and result["operation"] == "running"
                and any("import" in warning.lower() for warning in warnings))
        result["pass"] = True
    finally:
        QMessageBox.warning = old_warning
        (root / "gate-a-pending-gate.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()


if __name__ == "__main__":
    main()
