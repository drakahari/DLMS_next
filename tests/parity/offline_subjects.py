"""Scoped external-network denial for Qt IT/Medical local pack workflows."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys

from desktop.isolation import PROJECT, profile_paths


def main() -> int:
    if sys.argv[1:] == ["--enter"]:
        env = {**os.environ, "DLMS_PARITY_HOST_NETNS": os.readlink("/proc/self/ns/net"),
               "PYTHONPATH": str(PROJECT), "PYTHONNOUSERSITE": "1"}
        return subprocess.run(["unshare", "--user", "--map-current-user", "--keep-caps", "--net",
                               sys.executable, "-m", "tests.parity.offline_subjects"],
                              cwd=PROJECT, env=env, check=False).returncode
    host = os.environ.get("DLMS_PARITY_HOST_NETNS")
    if not host or os.readlink("/proc/self/ns/net") == host:
        raise RuntimeError("Refusing to change loopback outside an isolated network namespace")
    paths = profile_paths("parityoffline02")
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True)
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=.5).close()
    except OSError:
        external_unreachable = True
    else:
        external_unreachable = False
    if not external_unreachable:
        raise RuntimeError("External network remained reachable; refusing offline claim")
    result = {"namespace": os.readlink("/proc/self/ns/net"),
              "external_unreachable": external_unreachable}
    log = paths["logs"] / "parity-offline-qt.log"
    env = {**os.environ, "PYTHONPATH": str(PROJECT), "PYTHONNOUSERSITE": "1"}
    with log.open("ab") as output:
        for phase in ("create", "reopen"):
            args = [sys.executable, "-m", "tests.parity.gui_subject_packs", "--profile", "parityoffline02"]
            if phase == "reopen":
                args.append("--reopen")
            completed = subprocess.run(args, cwd=PROJECT, env=env, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT, timeout=90)
            result[phase] = completed.returncode
    result["pass"] = result["create"] == result["reopen"] == 0
    (paths["root"] / "parity-offline-subjects.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
