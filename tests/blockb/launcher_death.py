"""Kill exactly the synthetic Qt owner while its restore worker is paused."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from desktop.isolation import PROJECT, profile_paths
from desktop.ownership import process_start_ticks


def same_process(pid: int, ticks: int) -> bool:
    try:
        return process_start_ticks(pid) == ticks
    except (FileNotFoundError, ProcessLookupError):
        return False


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--archive", type=Path, required=True)
    args = p.parse_args()
    paths = profile_paths(args.profile)
    marker = paths["root"] / "blockb-pause-evidence.json"
    driver_file = paths["root"] / "blockb-menu-driver.pid"
    marker.unlink(missing_ok=True)
    driver_file.unlink(missing_ok=True)
    log = paths["logs"] / "blockb-launcher-death.log"
    with log.open("ab", buffering=0) as stream:
        driver = subprocess.Popen([sys.executable, "-m", "tests.blockb.gui_menu_adoption",
            "--profile", args.profile, "--archive", str(args.archive),
            "--pause-at", "source-live_apply_started"], cwd=PROJECT,
            env={**os.environ, "PYTHONPATH": str(PROJECT)}, stdout=stream,
            stderr=subprocess.STDOUT, start_new_session=True)
        driver_ticks = process_start_ticks(driver.pid)
        deadline = time.monotonic() + 30
        while not marker.exists() and driver.poll() is None and time.monotonic() < deadline:
            time.sleep(.05)
        if not marker.exists():
            raise AssertionError(f"Qt restore did not reach pause; see {log}")
        worker = json.loads(marker.read_text())["pid"]
        if int(driver_file.read_text()) != driver.pid or process_start_ticks(driver.pid) != driver_ticks:
            raise AssertionError("Qt owner identity changed before the targeted signal")
        worker_cmd = (Path("/proc") / str(worker) / "cmdline").read_bytes()
        worker_status = (Path("/proc") / str(worker) / "status").read_text()
        if b"desktop.adopt" not in worker_cmd or f"PPid:\t{driver.pid}\n" not in worker_status:
            raise AssertionError("Restore worker is not the exact Qt owner's child")
        worker_ticks = process_start_ticks(worker)
        os.kill(driver.pid, signal.SIGKILL)
        driver.wait(timeout=8)
        deadline = time.monotonic() + 10
        while same_process(worker, worker_ticks) and time.monotonic() < deadline:
            time.sleep(.05)
        worker_gone = not same_process(worker, worker_ticks)
        result = {"driver_pid": driver.pid, "worker_pid": worker,
                  "driver_exit": driver.returncode, "worker_gone": worker_gone,
                  "marker_retained": (paths["root"] / "desktop-data-transition.json").exists(),
                  "log": str(log)}
        (paths["root"] / "blockb-launcher-death.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return 0 if worker_gone and result["marker_retained"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
