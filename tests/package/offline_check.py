"""Packaged Qt foundation inside a disposable loopback-only network namespace."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inside", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if not args.inside:
        host = os.readlink("/proc/self/ns/net")
        env = {**os.environ, "DLMS_PACKAGE_HOST_NETNS": host}
        return subprocess.run(["unshare", "--user", "--map-current-user", "--keep-caps", "--net",
                               sys.executable, "-m", "tests.package.offline_check",
                               "--exe", str(args.exe.resolve()), "--data-root", str(args.data_root.resolve()),
                               "--profile", args.profile, "--cwd", str(args.cwd.resolve()),
                               "--output", str(args.output.resolve()), "--inside"],
                              env=env, check=False).returncode
    current = os.readlink("/proc/self/ns/net")
    host = os.environ.get("DLMS_PACKAGE_HOST_NETNS")
    if not host or current == host:
        raise RuntimeError("Offline check refused without a distinct network namespace")
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True)
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=0.5).close()
    except OSError:
        unreachable = True
    else:
        raise RuntimeError("External network remained reachable; packaged offline check refused")
    steps = []
    for phase in ("create", "reopen"):
        command = [sys.executable, "-m", "tests.package.run_check", "--exe", str(args.exe),
                   "--data-root", str(args.data_root), "--profile", args.profile,
                   "--cwd", str(args.cwd), "--check", "foundation",
                   "--output", str(args.output / phase), "--", "--phase", phase]
        outcome = subprocess.run(command, check=False)
        steps.append({"phase": phase, "exit": outcome.returncode})
        if outcome.returncode:
            break
    result = {"host_namespace": host, "test_namespace": current,
              "external_unreachable": unreachable, "steps": steps,
              "pass": len(steps) == 2 and all(not step["exit"] for step in steps)}
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
