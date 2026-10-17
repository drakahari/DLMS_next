"""Application-local normal-package pilot launch/reopen in a fixture home."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time

from tests.package.normal_local_settings_smoke import (
    backend_nonce, descendants, request, starttime, stop_exact_owned,
)


def launch(launcher: Path, root: Path, output: Path, index: int, *, session_wayland: bool) -> dict:
    env = {key: value for key, value in os.environ.items()
           if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "QTWEBENGINE_DISABLE_SANDBOX",
                          "QTWEBENGINE_CHROMIUM_FLAGS", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"}}
    if session_wayland:
        if not env.get("XDG_RUNTIME_DIR") or not env.get("WAYLAND_DISPLAY"):
            raise RuntimeError("A running Wayland session is required")
        env["QT_QPA_PLATFORM"] = "wayland"
        env["WAYLAND_DEBUG"] = "client"
    else:
        env["QT_QPA_PLATFORM"] = "offscreen"
        for key, leaf in (("HOME", "home"), ("XDG_DATA_HOME", "xdg/data"),
                          ("XDG_CONFIG_HOME", "xdg/config"), ("XDG_CACHE_HOME", "xdg/cache"),
                          ("TMPDIR", "tmp")):
            path = output / leaf
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            env[key] = str(path)
        # Fixture launch gets a private offscreen runtime. The real menu launch
        # and session-wayland check preserve the graphical session's directory.
        runtime = output / "xdg/runtime"
        runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
        env["XDG_RUNTIME_DIR"] = str(runtime)
    log = output / f"normal-{index}.log"
    with log.open("w") as stream:
        process = subprocess.Popen([str(launcher)], cwd=output, env=env,
                                   stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        observed = {process.pid: starttime(process.pid)}
        try:
            manifest_path = root / "profiles/pilot01/desktop-profile.json"
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Installed fixture exited before readiness: {process.returncode}")
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
                raise TimeoutError("Installed fixture did not reach authenticated readiness")
            assert request(manifest["port"], owner[1], "GET", "/library")[0] == 200
            assert request(manifest["port"], "wrong", "GET", "/library")[0] == 403
            assert request(manifest["port"], owner[1], "POST", "/api/shutdown")[0] == 200
            assert process.wait(timeout=25) == 0
            return {"profile_uuid": manifest["uuid"], "origin_port": manifest["port"],
                    "backend_pid": owner[0], "normal_executable": str(launcher),
                    "shutdown": "authenticated, clean", "log": str(log)}
        finally:
            residual = stop_exact_owned(process, observed)
            if residual:
                raise RuntimeError(f"Fixture left owned processes: {residual}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--launcher", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--session-wayland", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    root = args.data_root.resolve()
    runs = [launch(args.launcher.resolve(), root, output, index,
                   session_wayland=args.session_wayland) for index in (1, 2)]
    assert runs[0]["profile_uuid"] == runs[1]["profile_uuid"]
    assert runs[0]["origin_port"] == runs[1]["origin_port"]
    result = {"normal_package": True, "session_wayland": args.session_wayland, "runs": runs,
              "stable_profile_and_origin": True, "data_root": str(root)}
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
