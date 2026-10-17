"""Deterministic exact-backend-crash/Qt-retry matrix in fresh synthetic profiles."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys

from desktop.isolation import AREA, PROJECT

CASES = [
    ("before_mutation", "data-safety-two.zip", 3),
    ("item_intent_0", "data-safety-two.zip", 3),
    ("publication_db_committed", "data-safety-two.zip", 3),
    ("publication_artifacts_promoted", "data-safety-two.zip", 3),
    ("publication_registry_published", "data-safety-two.zip", 3),
    ("before_item_receipt", "data-safety-two.zip", 3),
    ("after_item_receipt", "data-safety-two.zip", 3),
    ("after_item_0", "data-safety-two.zip", 3),
    ("after_all_receipts", "data-safety-two.zip", 3),
    ("after_temporary_cleanup", "data-safety-two.zip", 3),
    ("before_item_receipt", "closure-portable-media.zip", 2),
    ("after_item_0", "closure-portable-media.zip", 2),
    ("after_temporary_cleanup", "closure-portable-media.zip", 2),
    ("after_complete_receipt", "data-safety-two.zip", 3),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--indices", nargs="*", type=int)
    parser.add_argument("--prefix", default="datasafetygb")
    args = parser.parse_args()
    indices = args.indices if args.indices is not None else list(range(len(CASES)))
    log_root = AREA / "retained" / "gate-a-repair" / "logs"
    log_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    summary = []
    for index in indices:
        stage, fixture, expected = CASES[index]
        profile = f"{args.prefix}{index:02d}"
        commands = [
            ("stage", [sys.executable, "-m", "tests.data_safety.managed_import_smoke", profile, "stage-seed", fixture]),
            ("retain", [sys.executable, "-m", "tests.completion.retain_fixture", "--profile", profile]),
            ("crash", [sys.executable, "-m", "tests.data_safety.gui_managed_retry", "--profile", profile, "--phase", "crash", "--abort", stage, "--expected", str(expected)]),
            ("retry", [sys.executable, "-m", "tests.data_safety.gui_managed_retry", "--profile", profile, "--phase", "retry", "--expected", str(expected)]),
            ("audit", [sys.executable, "-m", "tests.data_safety.audit_managed_import", "--profile", profile]),
        ]
        case = {"index": index, "profile": profile, "checkpoint": stage,
                "fixture": fixture, "steps": {}}
        print(f"Gate A {index}: {stage} / {fixture}", flush=True)
        for label, command in commands:
            log = log_root / f"{profile}-{label}.log"
            with log.open("w", encoding="utf-8") as output:
                result = subprocess.run(command, cwd=PROJECT, stdout=output, stderr=subprocess.STDOUT, timeout=100)
            case["steps"][label] = {"exit": result.returncode, "log": str(log)}
            print(f"  {label}: {result.returncode}", flush=True)
            if result.returncode:
                break
        case["pass"] = len(case["steps"]) == len(commands) and all(step["exit"] == 0 for step in case["steps"].values())
        summary.append(case)
        (log_root.parent / "matrix.json").write_text(json.dumps(summary, indent=2) + "\n")
    assert all(case["pass"] for case in summary), "one or more Gate A checkpoint cases failed; logs and profiles retained"
    print(json.dumps({"cases": len(summary), "passed": sum(case["pass"] for case in summary)}, indent=2))


if __name__ == "__main__":
    main()
