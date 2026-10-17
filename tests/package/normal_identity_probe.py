"""Read a normal package's Wayland app ID from its own task-owned window."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time

from tests.package.normal_local_settings_smoke import (
    backend_nonce, descendants, request, starttime, stop_exact_owned,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expect-app-id", required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    env = {key: value for key, value in os.environ.items()
           if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "QTWEBENGINE_DISABLE_SANDBOX",
                          "QTWEBENGINE_CHROMIUM_FLAGS", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"}}
    if not env.get("XDG_RUNTIME_DIR"):
        raise RuntimeError("Use the existing graphical session; XDG_RUNTIME_DIR is required")
    for key, path in (("HOME", "home"), ("XDG_DATA_HOME", "xdg/data"),
                      ("XDG_CONFIG_HOME", "xdg/config"), ("XDG_CACHE_HOME", "xdg/cache"),
                      ("TMPDIR", "tmp")):
        target = output / path
        target.mkdir(mode=0o700, parents=True)
        env[key] = str(target)
    env["QT_QPA_PLATFORM"] = "wayland"
    env["WAYLAND_DEBUG"] = "client"
    log_path = output / "normal-wayland.log"
    with log_path.open("w") as log:
        process = subprocess.Popen(
            [str(args.exe.resolve()), "--profile", args.profile,
             "--data-root", str(args.data_root.resolve())],
            cwd=output, env=env, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        observed = {process.pid: starttime(process.pid)}
        try:
            manifest_path = args.data_root / "profiles" / args.profile / "desktop-profile.json"
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Normal package exited before readiness: {process.returncode}")
                observed.update({pid: starttime(pid) for pid in descendants(process.pid)})
                owner = backend_nonce(process.pid)
                if owner and manifest_path.exists():
                    manifest = json.loads(manifest_path.read_text())
                    try:
                        if request(manifest["port"], owner[1], "GET", "/_desktop/ready")[0] == 200:
                            break
                    except OSError:
                        pass
                time.sleep(0.1)
            else:
                raise TimeoutError("Normal package did not become ready")
            assert request(manifest["port"], owner[1], "POST", "/api/shutdown")[0] == 200
            assert process.wait(timeout=25) == 0
            log.flush()
            found = re.findall(r'xdg_toplevel#\d+\.set_app_id\("([^"]+)"\)',
                               log_path.read_text(errors="replace"))
            assert found, "The task-owned Wayland top-level did not advertise an app ID"
            assert set(found) == {args.expect_app_id}, found
            result = {"app_id": found[0], "events": len(found), "profile": args.profile,
                      "normal_executable": str(args.exe.resolve()), "shutdown": "clean",
                      "xdg_runtime_dir_preserved": True}
            (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result, indent=2))
            return 0
        finally:
            residual = stop_exact_owned(process, observed)
            if residual:
                raise RuntimeError(f"Only the task-owned process tree was targeted; residual: {residual}")


if __name__ == "__main__":
    raise SystemExit(main())
