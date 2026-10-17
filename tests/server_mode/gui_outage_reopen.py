"""Separate-process remembered Server outage and explicit Local return."""
from __future__ import annotations

import argparse
import json
import sqlite3
import os
from pathlib import Path
import sys
import time

from desktop.isolation import isolated_environment, profile_paths
from desktop.server_mode import read_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    paths = profile_paths(args.profile, create=False)
    config = read_config(args.profile)
    assert config["mode"] == "server", "This check needs a remembered Server selection"
    env = isolated_environment(paths)
    os.environ.clear()
    os.environ.update(env)
    os.environ["DLMS_DESKTOP_AUTOMATED"] = "1"
    from PySide6.QtWidgets import QApplication
    from desktop.shell import DesktopWindow
    app = QApplication(sys.argv[:1])
    window = DesktopWindow(paths, args.profile)
    window.show()
    window.start()
    deadline = time.monotonic() + 12
    while not window.server_unreachable and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.05)
    assert window.server_unreachable and window.mode == "server"
    assert window.backend is None and window.mode_identity.text().startswith("Server:")
    assert window.mode_identity.isEnabled() and window.local_mode_action.isEnabled()
    assert window.retry_server_action.isVisible() and window.retry_server_action.isEnabled()
    assert config["server"]["origin"] in window.mode_identity.toolTip()
    assert window.server_status.isVisible() and "Local data was not opened" in window.server_status.text()
    with sqlite3.connect(paths["backend"] / "results.db") as connection:
        before = tuple(connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                       for table in ("quizzes", "attempts", "study_responses"))
    assert window.switch_to_local()
    deadline = time.monotonic() + 25
    while (window.backend is None or window.ready_ms is None or window.view is None or window.mode != "local") and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.05)
    assert window.backend is not None and window.backend.poll() is None
    with sqlite3.connect(paths["backend"] / "results.db") as connection:
        after = tuple(connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                      for table in ("quizzes", "attempts", "study_responses"))
    assert after == before
    report = {"outage_kept_server_selected": True, "no_silent_local_backend": True,
              "explicit_local_return_same_database": True,
              "server_storage": str(window.server_paths["storage"])}
    output = paths["root"] / "server-outage-reopen.json"
    output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    window.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
