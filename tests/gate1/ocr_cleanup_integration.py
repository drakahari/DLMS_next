"""Check actual task-owned OCR/Qt helpers after the GUI process exits."""
from __future__ import annotations

import json
import os
import subprocess
import sys

from desktop.isolation import PROJECT, isolated_environment, profile_paths
from tests.gate1.lifecycle_integration import live_pid, wait_until


def main() -> int:
    paths = profile_paths("ocr06")
    env = isolated_environment(paths)
    env["PYTHONPATH"] = str(PROJECT)
    env["PYTHONNOUSERSITE"] = "1"
    with open(paths["logs"] / "ocr-driver.log", "wb") as log:
        process = subprocess.Popen(
            [sys.executable, "tests/gate1/gui_ocr_pdf.py", "--profile", "ocr06"],
            cwd=PROJECT, env=env, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        code = process.wait(timeout=70)
    evidence = json.loads((paths["root"] / "ocr-pdf-evidence.json").read_text())
    captured = evidence["task_descendants_at_window_close"]
    clean = wait_until(lambda: not any(live_pid(pid) for pid in captured), 8)
    result = {"gui_exit": code, "ocr_status": evidence["status"],
              "captured_task_helpers": len(captured), "all_gone_after_process_exit": clean}
    (paths["root"] / "ocr-cleanup-evidence.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if code == 0 and evidence["status"] == "pass" and clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
