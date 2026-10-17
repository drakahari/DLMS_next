"""Reproducible six-scope synthetic Qt preservation drill.

Each invocation uses new profile names, writes only under .gate1, and retains
the verified pre-operation profile outside the destructive target.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from desktop.isolation import AREA, PROJECT

SCOPES = ("study", "learning", "quiz", "source", "settings", "fresh")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--prefix", required=True)
    p.add_argument("--committed-abort", action="store_true")
    a = p.parse_args()
    if not a.prefix.isalnum() or len(a.prefix) > 18:
        raise ValueError("Use a short alphanumeric disposable prefix")
    log_root = AREA / "profiles" / "completionfinaltests" / "logs"
    log_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    results = []
    for scope in SCOPES:
        profile = f"{a.prefix}{scope}"
        if (AREA / "profiles" / profile).exists() or (AREA / "retained" / f"{profile}-before").exists():
            raise FileExistsError(f"Disposable profile already exists: {profile}")
        setup = (
            ("foundation", "tests.gate1.gui_foundation", "--profile", profile, "--phase", "create"),
            ("credentials", "tests.blockb.populated_fixture", "--profile", profile),
            ("retain", "tests.completion.retain_fixture", "--profile", profile),
        )
        finish = (("abort-committed", "tests.completion.gui_maintenance_abort", "--profile", profile,
                   "--scope", scope, "--checkpoint", "committed"),
                  ("replay", "tests.completion.gui_maintenance_committed_replay", "--profile", profile,
                   "--scope", scope)) if a.committed_abort else (
                  ("run", "tests.completion.gui_maintenance_scope", "--profile", profile,
                   "--scope", scope, "--phase", "run"),
                  ("reopen", "tests.completion.gui_maintenance_scope", "--profile", profile,
                   "--scope", scope, "--phase", "reopen"))
        commands = setup + finish
        for label, module, *args in commands:
            log_path = log_root / f"{profile}-{label}.log"
            with log_path.open("w") as log:
                result = subprocess.run([sys.executable, "-m", module, *args], cwd=PROJECT,
                                        stdout=log, stderr=subprocess.STDOUT, check=False)
            results.append({"profile": profile, "scope": scope, "step": label,
                            "exit_code": result.returncode, "log": str(log_path)})
            print(json.dumps(results[-1]), flush=True)
            if result.returncode:
                break
        if results[-1]["exit_code"]:
            break
    report = AREA / "profiles" / "completionfinaltests" / f"rich-scopes-{a.prefix}.json"
    report.write_text(json.dumps(results, indent=2) + "\n")
    return 0 if len(results) == 5 * len(SCOPES) and all(not x["exit_code"] for x in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
