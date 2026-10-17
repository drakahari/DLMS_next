"""Scoped local-only Qt authoring, PDF, hotspot and grading drill."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys

from desktop.isolation import AREA, PROJECT


def main() -> int:
    if sys.argv[1:] == ["--enter"]:
        env = {**os.environ, "DLMS_COMPLETION_HOST_NETNS": os.readlink("/proc/self/ns/net"),
               "PYTHONPATH": str(PROJECT), "PYTHONNOUSERSITE": "1"}
        return subprocess.run(["unshare", "--user", "--map-current-user", "--keep-caps", "--net",
                               sys.executable, "-m", "tests.completion.offline_families"],
                              cwd=PROJECT, env=env, check=False).returncode
    host = os.environ.get("DLMS_COMPLETION_HOST_NETNS")
    if not host or os.readlink("/proc/self/ns/net") == host:
        raise RuntimeError("Refusing to touch loopback outside a distinct user/network namespace")
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True)
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=.5).close()
    except OSError:
        external_unreachable = True
    else:
        external_unreachable = False
    if not external_unreachable:
        raise RuntimeError("External service remained reachable; offline claim refused")
    log_root = AREA / "profiles" / "completionfinaltests" / "logs"
    log_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    commands = (
        ("terminology", "tests.completion.gui_terminology_review", "completionofflineterms01", (), ("--reopen",)),
        ("multi", "tests.completion.gui_multi_answer", "completionofflinemulti01", (), ("--reopen",), ("--grade",)),
        ("hotspot", "tests.completion.gui_hotspot", "completionofflinehotspot01", (), ("--reopen",)),
    )
    results = {"namespace": os.readlink("/proc/self/ns/net"), "external_unreachable": external_unreachable,
               "commands": []}
    for family, module, profile, *phases in commands:
        if (AREA / "profiles" / profile).exists():
            raise FileExistsError(f"Disposable offline profile already exists: {profile}")
        for phase in phases:
            label = "create" if not phase else phase[0].lstrip("-")
            log_path = log_root / f"offline-{family}-{label}.log"
            with log_path.open("w") as log:
                result = subprocess.run([sys.executable, "-m", module, "--profile", profile, *phase],
                                        cwd=PROJECT, stdout=log, stderr=subprocess.STDOUT, timeout=90)
            results["commands"].append({"family": family, "phase": label,
                                        "returncode": result.returncode, "log": str(log_path)})
            print(json.dumps(results["commands"][-1]), flush=True)
            if result.returncode:
                break
        if results["commands"][-1]["returncode"]:
            break
    results["pass"] = len(results["commands"]) == 7 and all(
        not result["returncode"] for result in results["commands"])
    (AREA / "profiles" / "completionfinaltests" / "offline-families.json").write_text(
        json.dumps(results, indent=2) + "\n")
    return 0 if results["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
