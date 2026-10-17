"""Task-owned process termination before a confirmed selection is claimed."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from desktop.backup_selection import advance, prepare
from desktop.isolation import PROJECT, isolated_environment, profile_paths
from tests.backup_binding.checkpoint import run, stable_facts
from tests.settings.gui_native_roundtrip import facts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--phase", choices=("copy", "ready", "confirmed"), required=True)
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    paths = profile_paths(args.profile)
    if args.child:
        if args.phase == "copy":
            prepare(paths, args.profile, args.archive, after_chunk=lambda _n: os._exit(71))
        selected = prepare(paths, args.profile, args.archive)
        if args.phase == "confirmed":
            advance(paths, args.profile, selected["token"], "ready", "confirmed")
        os._exit(71)
    env = isolated_environment(paths)
    env.update(PYTHONPATH=str(PROJECT), PYTHONNOUSERSITE="1")
    log = paths["logs"] / f"binding-{args.phase}-interrupt.log"
    assert run("tests.gate1.gui_foundation", "--profile", args.profile, "--phase", "create",
               env=env, log=log) == 0
    before = facts(paths["backend"])
    with log.open("ab") as output:
        interrupted = subprocess.run([sys.executable, "-m", "tests.backup_binding.selection_interrupt",
                                      "--profile", args.profile, "--archive", str(args.archive),
                                      "--phase", args.phase, "--child"], cwd=PROJECT, env=env,
                                     stdout=output, stderr=subprocess.STDOUT, timeout=90).returncode
    assert interrupted == 71
    imports = paths["root"] / "imports"
    receipts = [json.loads(path.read_text()) for path in imports.glob("*.json")]
    expected = {"copy": [], "ready": ["ready"], "confirmed": ["confirmed"]}[args.phase]
    assert [item["state"] for item in receipts] == expected
    assert run("tests.gate1.gui_foundation", "--profile", args.profile, "--phase", "reopen",
               env=env, log=log) == 0
    assert stable_facts(facts(paths["backend"])) == stable_facts(before)
    result = {"pass": True, "profile": args.profile, "phase": args.phase,
              "process_exit": interrupted, "receipt_states": expected,
              "destination_unchanged_after_restart": True, "log": str(log)}
    (paths["root"] / f"binding-{args.phase}-interrupt.json").write_text(
        json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
