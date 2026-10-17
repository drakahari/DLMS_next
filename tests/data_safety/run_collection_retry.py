"""Two independently committed collection inner bundles, second crash/retry in Qt."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

from desktop.isolation import AREA, PROJECT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    name = args.profile
    assert name.startswith("datasafety")
    logs = AREA / "retained/gate-a-repair/logs"
    logs.mkdir(parents=True, exist_ok=True)
    commands = [
        ("first-stage", [sys.executable, "-m", "tests.data_safety.managed_import_smoke", name,
                         "stage-seed", "gate-a-collection-inner-001.zip"]),
        ("first-retain", [sys.executable, "-m", "tests.completion.retain_fixture", "--profile", name]),
        ("first-import", [sys.executable, "-m", "tests.data_safety.gui_managed_retry", "--profile", name,
                          "--phase", "retry", "--expected", "101"]),
        ("first-audit", [sys.executable, "-m", "tests.data_safety.audit_managed_import", "--profile", name]),
        ("second-stage", [sys.executable, "-m", "tests.data_safety.gui_collection_second", "--profile", name,
                          "--phase", "stage"]),
        ("second-retain", [sys.executable, "-m", "tests.completion.retain_fixture", "--profile", name,
                           "--label", "before-second"]),
        ("second-crash", [sys.executable, "-m", "tests.data_safety.gui_collection_second", "--profile", name,
                          "--phase", "crash"]),
        ("second-retry", [sys.executable, "-m", "tests.data_safety.gui_collection_second", "--profile", name,
                          "--phase", "retry"]),
        ("second-audit", [sys.executable, "-m", "tests.data_safety.audit_managed_import", "--profile", name,
                          "--label", "before-second"]),
    ]
    result = []
    for label, command in commands:
        log = logs / f"{name}-{label}.log"
        with log.open("w", encoding="utf-8") as output:
            done = subprocess.run(command, cwd=PROJECT, stdout=output, stderr=subprocess.STDOUT, timeout=210)
        result.append({"step": label, "exit": done.returncode, "log": str(log)})
        print(f"{label}: {done.returncode}", flush=True)
        if done.returncode:
            break
    (AREA / "retained/gate-a-repair/collection-final.json").write_text(json.dumps(result, indent=2) + "\n")
    assert len(result) == len(commands) and all(step["exit"] == 0 for step in result)


if __name__ == "__main__":
    main()
