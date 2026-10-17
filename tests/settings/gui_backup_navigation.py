"""A native backup with a lost browser response blocks new actions until restart."""
from __future__ import annotations

import argparse
import json
import time
import zipfile

from PySide6.QtCore import QUrl

from tests.gate1.qt_checks import QtChecks


def until(q, predicate, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        q.delay(.1)
    raise TimeoutError("Backup checkpoint did not arrive")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--phase", choices=("interrupt", "reopen"), required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, automated=True, pause_backup_iteration=args.phase == "interrupt")
    root = q.paths["root"]
    report = {"phase": args.phase, "profile": args.profile}
    try:
        if args.phase == "interrupt":
            q.go("/settings/backup")
            q.window.settings_buttons["create_backup"].click()
            entered = root / "blockc-backup-iteration.json"
            until(q, entered.exists)
            assert q.window._backup_creating
            q.window.view.setUrl(QUrl(f"http://127.0.0.1:{q.window.port}/settings/reset-remove"))
            q.wait("location.pathname === '/settings/reset-remove' && document.readyState === 'complete'")
            until(q, lambda: q.window._settings_ready("reset-remove"))
            assert not q.window.settings_buttons["exam"].isEnabled()
            q.window._activate_settings_action("exam")
            assert q.window.maintenance_worker is None
            (root / "blockc-backup-iteration-release").write_text("release\n")
            until(q, (root / "blockc-backup-iterable-closed.json").exists)
            q.delay(.4)
            assert q.window._backup_creating and not q.window.downloaded_files
            backups = sorted((q.paths["backend"] / "backups").glob("*.zip"))
            assert len(backups) == 1 and zipfile.is_zipfile(backups[0])
            report.update(backup_name=backups[0].name, no_browser_ack=True,
                          maintenance_blocked=True, retained_backup=True)
        else:
            prior = json.loads((root / "native-backup-interrupt.json").read_text())
            q.go("/settings/backup")
            q.delay(.5)
            assert q.window._settings_ready("backup") and not q.window._backup_creating
            assert prior["backup_name"] in q.window.settings_panel.inventory_label.text()
            backups = sorted((q.paths["backend"] / "backups").glob("*.zip"))
            assert len(backups) == 1 and backups[0].name == prior["backup_name"]
            report.update(restart_inventory_visible=True, no_duplicate_backup=True)
        report["pass"] = True
    finally:
        if args.phase == "interrupt":
            (root / "blockc-backup-iteration-release").write_text("release\n")
        (root / f"native-backup-{args.phase}.json").write_text(json.dumps(report, indent=2) + "\n")
        q.close()
    print(json.dumps(report, indent=2))
    return 0 if report.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
