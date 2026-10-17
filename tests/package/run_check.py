"""Run one instrumented frozen Qt check with an isolated synthetic environment."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--check", required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-exit", type=int, default=0)
    args, extras = parser.parse_known_args()
    if extras and extras[0] == "--":
        extras = extras[1:]
    args.output.mkdir(parents=True, exist_ok=True)
    env_root = args.output / "environment"
    env = {"PATH": "/nonexistent", "LANG": "C.UTF-8", "DISPLAY": os.environ["DISPLAY"],
           "QT_QPA_PLATFORM": "xcb", "XDG_RUNTIME_DIR": os.environ["XDG_RUNTIME_DIR"]}
    if "DBUS_SESSION_BUS_ADDRESS" in os.environ:
        env["DBUS_SESSION_BUS_ADDRESS"] = os.environ["DBUS_SESSION_BUS_ADDRESS"]
    for name, relative in (("HOME", "home"), ("XDG_DATA_HOME", "xdg/data"),
                           ("XDG_CONFIG_HOME", "xdg/config"), ("XDG_CACHE_HOME", "xdg/cache"),
                           ("TMPDIR", "tmp")):
        path = env_root / relative
        path.mkdir(parents=True, exist_ok=True)
        env[name] = str(path)
    cmd = [str(args.exe.resolve()), "--packaged-check", args.check, "--profile", args.profile,
           "--data-root", str(args.data_root.resolve()), *extras]
    start = time.monotonic()
    with (args.output / "launcher.log").open("w") as log:
        proc = subprocess.Popen(cmd, cwd=args.cwd, env=env, stdout=log,
                                stderr=subprocess.STDOUT)
        try:
            code = proc.wait(timeout=110)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=8)
            raise
    report = {"check": args.check, "profile": args.profile, "pid": proc.pid,
              "exit_code": code, "expected_exit": args.expected_exit,
              "elapsed_seconds": time.monotonic() - start,
              "log": str(args.output / "launcher.log")}
    (args.output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if code != args.expected_exit:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
