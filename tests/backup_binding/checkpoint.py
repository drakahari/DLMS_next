"""Separate-process confirmed-selection restore interruption drill."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from desktop.backup_selection import advance, prepare, read
from desktop.isolation import PROJECT, isolated_environment, profile_paths
from desktop.profile_state import read_manifest
from tests.settings.gui_native_roundtrip import facts


def run(module: str, *args: str, env: dict, log: Path) -> int:
    with log.open("ab") as output:
        return subprocess.run([sys.executable, "-m", module, *args], cwd=PROJECT,
                              env=env, stdout=output, stderr=subprocess.STDOUT,
                              timeout=90).returncode


def stable_facts(value: dict) -> dict:
    # The existing Study reopen flow takes a fresh browser ownership token;
    # identity, responses, quiz content and assets must remain exact.
    value = json.loads(json.dumps(value))
    for session in value["rows"]["study_sessions"]:
        session.pop("owner", None)
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--source-profile", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--checkpoint", choices=("marker", "source-receipt"), required=True)
    args = parser.parse_args()
    paths = profile_paths(args.profile)
    env = isolated_environment(paths)
    env.update(PYTHONPATH=str(PROJECT), PYTHONNOUSERSITE="1")
    log = paths["logs"] / f"binding-{args.checkpoint}-checkpoint.log"
    assert run("tests.gate1.gui_foundation", "--profile", args.profile, "--phase", "create",
               env=env, log=log) == 0, log
    before = facts(paths["backend"])
    (paths["root"] / "binding-before-facts.json").write_text(json.dumps(before, indent=2) + "\n")
    before_epoch = read_manifest(paths, args.profile)["epoch"]
    selection = prepare(paths, args.profile, args.archive)
    advance(paths, args.profile, selection["token"], "ready", "confirmed")
    aborted = run("desktop.adopt", "--profile", args.profile, "--selection", selection["token"],
                  env={**env, "DLMS_DESKTOP_AUTOMATED": "1",
                       "DLMS_DESKTOP_TEST_ABORT_AT": args.checkpoint}, log=log)
    assert aborted == 71, f"Expected deterministic process abort 71, got {aborted}: {log}"
    claimed = read(paths, args.profile, selection["token"], state="claimed", check_epoch=False)
    with open(log, "ab") as output:
        duplicate = subprocess.run([sys.executable, "-m", "desktop.adopt", "--profile", args.profile,
                                    "--selection", selection["token"]], cwd=PROJECT, env=env,
                                   stdout=output, stderr=subprocess.STDOUT, timeout=90).returncode
    assert duplicate == 2, "Claimed selection was unexpectedly replayed"
    expected_adopted = args.checkpoint == "source-receipt"
    reopen_module = ("tests.settings.gui_native_roundtrip" if expected_adopted
                     else "tests.gate1.gui_foundation")
    reopen_args = (["--profile", args.profile, "--source", args.source_profile, "--phase", "reopen"]
                   if expected_adopted else ["--profile", args.profile, "--phase", "reopen"])
    reopened = run(reopen_module, *reopen_args, env=env, log=log)
    assert reopened == 0, f"Restart/reconciliation failed: {log}"
    after = facts(paths["backend"])
    (paths["root"] / "binding-after-facts.json").write_text(json.dumps(after, indent=2) + "\n")
    reference = (json.loads((profile_paths(args.source_profile, create=False)["root"] /
                             "native-settings-export.json").read_text())["facts"]
                 if expected_adopted else before)
    assert stable_facts(after) == stable_facts(reference), {
        key: (len(reference["rows"][key]), len(after["rows"][key]))
        for key in reference["rows"] if reference["rows"][key] != after["rows"][key]
    }
    after_epoch = read_manifest(paths, args.profile)["epoch"]
    assert (before_epoch != after_epoch) == expected_adopted
    result = {"pass": True, "profile": args.profile, "checkpoint": args.checkpoint,
              "abort_exit": aborted, "duplicate_exit": duplicate, "reopen_exit": reopened,
              "selection_state": claimed["state"], "epoch_changed": before_epoch != after_epoch,
              "data_equal_expected": True, "log": str(log)}
    (paths["root"] / f"binding-{args.checkpoint}-checkpoint.json").write_text(
        json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
