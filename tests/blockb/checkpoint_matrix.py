"""Separate-process synthetic restore crashes at each Desktop boundary."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from desktop.isolation import PROJECT, isolated_environment, profile_paths
from desktop.profile_state import read_manifest

PHASES = (
    ("marker", False), ("source-safety_backup_created", False),
    ("source-live_apply_started", True), ("source-receipt", True),
    ("quarantine-web_storage-renamed", True),
    ("quarantine-web_cache-renamed", True),
    ("quarantine-pending-requests-renamed", True),
    ("epoch-published", True), ("marker-removed", True),
)


def run(argv, env, log):
    with log.open("ab") as output:
        return subprocess.run([sys.executable, "-m", *argv], cwd=PROJECT, env=env,
                              stdout=output, stderr=subprocess.STDOUT, timeout=90).returncode


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--archive", type=Path, required=True)
    args = p.parse_args()
    results = []
    for index, (phase, epoch_changes) in enumerate(PHASES):
        name = f"blockbmatrix{index:02d}"
        paths = profile_paths(name)
        env = isolated_environment(paths)
        env.update(PYTHONPATH=str(PROJECT), PYTHONNOUSERSITE="1")
        log = paths["logs"] / "checkpoint-matrix.log"
        create = run(["tests.gate1.gui_foundation", "--profile", name, "--phase", "create"], env, log)
        if create:
            raise RuntimeError(f"Synthetic Qt profile creation failed for {phase}; see {log}")
        before = read_manifest(paths, name)
        adopt_env = {**env, "DLMS_DESKTOP_AUTOMATED": "1", "DLMS_DESKTOP_TEST_ABORT_AT": phase}
        aborted = run(["desktop.adopt", "--profile", name, "--archive", str(args.archive)], adopt_env, log)
        if aborted != 71:
            raise RuntimeError(f"Restore checkpoint {phase} exited {aborted}, expected 71; see {log}")
        reopen = run(["tests.gate1.gui_foundation", "--profile", name, "--phase", "reopen"] if not epoch_changes
                     else ["tests.blockb.gui_adoption", "--profile", name], env, log)
        after = read_manifest(paths, name)
        marker = (paths["root"] / "desktop-data-transition.json").exists()
        result = {"profile": name, "phase": phase, "crash_exit": aborted,
                  "qt_reopen_exit": reopen, "epoch_changed": before["epoch"] != after["epoch"],
                  "marker_cleared": not marker,
                  "quarantine": len(list((paths["root"] / "quarantine").glob("*/*"))) if epoch_changes else 0}
        result["status"] = "pass" if reopen == 0 and result["epoch_changed"] == epoch_changes and not marker else "fail"
        results.append(result)
        print(json.dumps(result), flush=True)
        if result["status"] != "pass":
            break
    target = profile_paths("blockbmatrix00")["root"] / "blockb-checkpoint-matrix.json"
    target.write_text(json.dumps(results, indent=2) + "\n")
    return 0 if len(results) == len(PHASES) and all(x["status"] == "pass" for x in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
