"""Actual Qt confirmation and pending-action refusal without source mutation."""
from __future__ import annotations

import argparse
import hashlib
import json
import traceback

from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import QUrl

from desktop.maintenance import read_marker
import desktop.maintenance as maintenance
from desktop.isolation import AREA
from tests.gate1.qt_checks import QtChecks


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--phase", choices=("pending", "storage"), default="pending")
    a = p.parse_args()
    q = QtChecks(a.profile, automated=True)
    out = {"profile": a.profile}
    old_question = QMessageBox.question
    old_warning = QMessageBox.warning
    old_atomic = maintenance.atomic_json
    try:
        q.go("/settings/reset-remove")
        assert q.window._settings_ready("reset-remove")
        db = q.paths["backend"] / "results.db"
        before = digest(db)
        warnings = []
        QMessageBox.question = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.No)
        q.window.settings_buttons["exam"].click()
        out["declined"] = q.window.maintenance_worker is None
        out["decline_unchanged"] = digest(db) == before and read_marker(a.profile) is None
        QMessageBox.warning = staticmethod(lambda *args, **kwargs: warnings.append(args[2]) or QMessageBox.StandardButton.Ok)
        QMessageBox.question = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
        if a.phase == "pending":
            q.js("localStorage.setItem('dlms-study-mistakes-request', JSON.stringify({id:'synthetic-unsettled'}))")
            assert q.window._settings_ready("reset-remove")
            q.window.settings_buttons["exam"].click()
            out["pending_refused"] = q.window.maintenance_worker is None
            out["pending_unchanged"] = digest(db) == before and read_marker(a.profile) is None
            out["evidence_retained"] = q.js("localStorage.getItem('dlms-study-mistakes-request') !== null")
            out["warnings"] = warnings
            out["fail_closed"] = (not q.window._settings_ready("reset-remove")
                                  and q.window.settings_fallback.isVisible()
                                  and "Close and reopen" in q.window.settings_fallback.text())
            q.window.view.setUrl(QUrl(f"http://127.0.0.1:{q.window.port}/library"))
            q.delay(.2)
            out["fallback_persists_after_navigation"] = q.window.settings_fallback.isVisible() and not q.window.view.isVisible()
            out["pass"] = all(out[k] for k in ("declined", "decline_unchanged", "pending_refused",
                                               "pending_unchanged", "evidence_retained", "fail_closed",
                                               "fallback_persists_after_navigation")) \
                and any("Study mistakes" in w for w in warnings)
        else:
            def unavailable(*args, **kwargs):
                raise OSError("synthetic maintenance recovery storage unavailable")
            maintenance.atomic_json = unavailable
            assert q.window._settings_ready("reset-remove")
            q.window.settings_buttons["exam"].click()
            out["storage_refused"] = q.window.maintenance_worker is None
            out["storage_unchanged"] = digest(db) == before and read_marker(a.profile) is None
            out["storage_message"] = warnings[-1]
            out["fail_closed"] = (not q.window._settings_ready("reset-remove")
                                  and q.window.settings_fallback.isVisible()
                                  and "Close and reopen" in q.window.settings_fallback.text())
            out["pass"] = all(out[k] for k in ("declined", "decline_unchanged", "storage_refused",
                                               "storage_unchanged", "fail_closed")) \
                and "synthetic maintenance recovery storage unavailable" in out["storage_message"]
        out["screenshot"] = str(q.screenshot("completion-maintenance-refusal.png", width=1000, height=760))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        QMessageBox.question = old_question
        QMessageBox.warning = old_warning
        maintenance.atomic_json = old_atomic
        (q.paths["root"] / "completion-maintenance-refusal.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
