"""Storage/cleanup failure with a separate real-Qt process retry."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

from desktop.isolation import AREA, PROJECT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--kind", choices=("receipt", "cleanup"), required=True)
    args = parser.parse_args()
    assert args.profile.startswith("datasafety")
    name = args.profile
    steps = [
        ("stage", [sys.executable, "-m", "tests.data_safety.managed_import_smoke", name,
                   "stage-seed", "closure-portable-media.zip"]),
        ("retain", [sys.executable, "-m", "tests.completion.retain_fixture", "--profile", name]),
        ("fail", [sys.executable, "-m", "tests.data_safety.gui_managed_failure", "--profile", name,
                  "--kind", args.kind]),
        ("retry", [sys.executable, "-m", "tests.data_safety.gui_managed_retry", "--profile", name,
                   "--phase", "retry", "--expected", "2"]),
        ("audit", [sys.executable, "-m", "tests.data_safety.audit_managed_import", "--profile", name]),
    ]
    root = AREA / "retained/gate-a-repair/logs"
    root.mkdir(parents=True, exist_ok=True)
    result = []
    for label, command in steps:
        log = root / f"{name}-{label}.log"
        with log.open("w", encoding="utf-8") as output:
            done = subprocess.run(command, cwd=PROJECT, stdout=output, stderr=subprocess.STDOUT, timeout=100)
        result.append({"step": label, "exit": done.returncode, "log": str(log)})
        print(label, done.returncode, flush=True)
        if done.returncode:
            break
    (AREA / f"retained/gate-a-repair/{name}-matrix.json").write_text(json.dumps(result, indent=2) + "\n")
    assert len(result) == len(steps) and all(step["exit"] == 0 for step in result)


if __name__ == "__main__":
    main()
