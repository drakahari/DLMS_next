"""Separate-process Server-mode profile exclusivity and outage persistence."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

from desktop.isolation import isolated_environment, profile_paths
from desktop.server_mode import configured_server, default_config, shell_root, write_config
from tests.package.normal_local_settings_smoke import descendants, starttime, stop_exact_owned


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    paths = profile_paths(args.profile)
    config = default_config(args.profile)
    config["server"] = configured_server(config, "http://127.0.0.2:65530/", "Absent synthetic Server",
                                         private_http_opt_in=True)
    config["mode"] = "server"
    write_config(args.profile, config)
    env = isolated_environment(paths)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["DLMS_DESKTOP_AUTOMATED"] = "1"
    log = paths["logs"] / "mode-launcher-primary.log"
    command = [sys.executable, "-m", "desktop", "--profile", args.profile, "--automated"]
    with log.open("w") as stream:
        first = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[2], env=env,
                                 stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        observed = {first.pid: starttime(first.pid)}
        try:
            deadline = time.monotonic() + 15
            descriptor = shell_root(args.profile) / "instance-owner.json"
            while not descriptor.exists() and time.monotonic() < deadline:
                if first.poll() is not None:
                    raise RuntimeError(f"First Server launcher exited: {first.returncode}")
                time.sleep(.1)
            assert descriptor.exists() and first.poll() is None
            observed.update({pid: starttime(pid) for pid in descendants(first.pid)})
            second = subprocess.run(command, cwd=Path(__file__).resolve().parents[2], env=env,
                                    text=True, capture_output=True, timeout=15)
            assert second.returncode == 0 and "already open" in second.stdout, (second.stdout, second.stderr)
            assert not (paths["root"] / "backend-writer.lock").exists()
            assert not (paths["root"] / "desktop-profile.json").exists()
            print("Server-mode duplicate focused the owned window; neither invocation started a Local backend")
        finally:
            survivors = stop_exact_owned(first, observed)
            assert not survivors, f"Task-owned descendants survived: {survivors}"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
