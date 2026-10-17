"""Run actual Qt core work in a separate network namespace, loopback only."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys

from desktop.isolation import PROJECT, profile_paths


def main() -> int:
    if sys.argv[1:] == ["--enter"]:
        env = {**os.environ, "DLMS_BLOCKC_HOST_NETNS": os.readlink("/proc/self/ns/net"),
               "PYTHONPATH": str(PROJECT)}
        return subprocess.run(["unshare", "--user", "--map-current-user", "--keep-caps", "--net",
            sys.executable, "-m", "tests.blockc.offline_scope"], cwd=PROJECT, env=env,
            check=False).returncode
    host = os.environ.get("DLMS_BLOCKC_HOST_NETNS")
    if not host or os.readlink("/proc/self/ns/net") == host:
        raise RuntimeError("Refusing to alter loopback outside an isolated network namespace")
    name = "blockcoffline01"
    paths = profile_paths(name)
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True)
    unreachable = False
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=0.5).close()
    except OSError:
        unreachable = True
    if not unreachable:
        raise RuntimeError("External network remained reachable; offline test refused")
    log = paths["logs"] / "blockc-offline-qt.log"
    result = {"namespace": os.readlink("/proc/self/ns/net"), "external_unreachable": unreachable}
    env = {**os.environ, "PYTHONPATH": str(PROJECT), "PYTHONNOUSERSITE": "1"}
    with log.open("ab") as output:
        for phase in ("create", "reopen"):
            completed = subprocess.run([sys.executable, "-m", "tests.gate1.gui_foundation",
                "--profile", name, "--phase", phase], cwd=PROJECT, env=env,
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                timeout=70)
            result[phase] = completed.returncode
    result["pass"] = result["create"] == result["reopen"] == 0
    (paths["root"] / "blockc-offline-scope.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
