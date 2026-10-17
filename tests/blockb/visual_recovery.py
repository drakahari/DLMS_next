"""Produce readable Qt recovery screenshots with fresh synthetic profiles."""
from __future__ import annotations

import json
import os
import subprocess
import sys

from desktop.isolation import PROJECT, isolated_environment, profile_paths


def main() -> int:
    results = []
    for kind, module in (("mistake", "tests.blockb.gui_mistake_crash"),
                         ("review", "tests.blockb.gui_review_crash")):
        name = "blockbvisual" + kind
        paths = profile_paths(name)
        env = isolated_environment(paths)
        env.update(PYTHONPATH=str(PROJECT), PYTHONNOUSERSITE="1")
        log = paths["logs"] / "visual-recovery.log"
        steps = (("tests.gate1.gui_foundation", "create"), (module, "committed"), (module, "reopen"))
        if kind == "mistake":
            steps = (("tests.gate1.gui_foundation", "create"), (module, "accepted"), (module, "reopen"))
        codes = []
        with log.open("ab") as output:
            for program, phase in steps:
                command = [sys.executable, "-m", program, "--profile", name, "--phase", phase]
                codes.append(subprocess.run(command, cwd=PROJECT, env=env, stdout=output,
                                            stderr=subprocess.STDOUT, timeout=75).returncode)
                if codes[-1]:
                    break
        results.append({"kind": kind, "profile": name, "exit_codes": codes,
                        "log": str(log), "status": "pass" if codes == [0, 0, 0] else "fail"})
        print(json.dumps(results[-1]), flush=True)
    profile = profile_paths("blockbvisualmistake")
    (profile["root"] / "blockb-visual-recovery.json").write_text(json.dumps(results, indent=2) + "\n")
    return 0 if all(result["status"] == "pass" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
