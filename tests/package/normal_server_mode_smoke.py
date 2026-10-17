"""Uninstrumented frozen Server launch/reopen against a task-owned loopback site.

This proves packaged routing and storage/process separation, not rendered text
or native control activation. No host-wide input or owner service is involved.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

from tests.package.normal_local_settings_smoke import descendants, starttime, stop_exact_owned


class Handler(BaseHTTPRequestHandler):
    seen: list[str] = []

    def do_GET(self):
        Handler.seen.append(self.path)
        body = b"<html><title>Synthetic Server only</title><body>SERVER DATASET ONLY</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def launch(args, index: int, *, expect_request: bool) -> dict:
    env_root = args.output / "environment"
    env = {"PATH": "/nonexistent", "LANG": "C.UTF-8", "QT_QPA_PLATFORM": "offscreen"}
    for key, relative in (("HOME", "home"), ("XDG_DATA_HOME", "xdg/data"),
                          ("XDG_CONFIG_HOME", "xdg/config"), ("XDG_CACHE_HOME", "xdg/cache"),
                          ("TMPDIR", "tmp"), ("XDG_RUNTIME_DIR", "xdg/runtime")):
        target = env_root / relative
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.chmod(0o700)
        env[key] = str(target)
    with (args.output / f"server-normal-{index}.log").open("w") as log:
        process = subprocess.Popen([str(args.exe), "--profile", args.profile,
                                    "--data-root", str(args.data_root)], cwd=args.cwd,
                                   env=env, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        observed = {process.pid: starttime(process.pid)}
        try:
            descriptor = args.data_root / "shell" / args.profile / "instance-owner.json"
            deadline = time.monotonic() + 30
            baseline = len(Handler.seen)
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Frozen Server launcher exited early: {process.returncode}")
                observed.update({pid: starttime(pid) for pid in descendants(process.pid)})
                if descriptor.is_file() and (not expect_request or len(Handler.seen) > baseline):
                    break
                time.sleep(.1)
            else:
                raise TimeoutError("Frozen Server launcher did not establish expected shell/site state")
            time.sleep(.6)
            assert process.poll() is None
            assert not (args.data_root / "profiles" / args.profile).exists(), "Server startup made a Local data root"
            assert not any(b"--desktop-worker\x00backend" in
                           (Path("/proc") / str(pid) / "cmdline").read_bytes()
                           for pid in descendants(process.pid) if pid != process.pid
                           and (Path("/proc") / str(pid) / "cmdline").exists())
            return {"index": index, "server_requests": len(Handler.seen) - baseline,
                    "local_root_absent": True, "local_backend_absent": True,
                    "shell_descriptor": descriptor.exists(), "owned_pids": sorted(observed)}
        finally:
            residual = stop_exact_owned(process, observed)
            assert not residual, f"Exact owned processes survived: {residual}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.exe, args.data_root, args.cwd, args.output = (
        args.exe.resolve(), args.data_root.resolve(), args.cwd.resolve(), args.output.resolve())
    assert args.exe.is_file() and args.data_root.is_dir() and args.cwd.is_dir()
    assert not (args.data_root / "profiles" / args.profile).exists()
    args.output.mkdir(parents=True, exist_ok=False)
    server = ThreadingHTTPServer(("127.0.0.2", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.2:{server.server_port}"
    identifier = str(uuid.uuid4())
    shell = args.data_root / "shell" / args.profile
    shell.mkdir(mode=0o700, parents=True)
    shell.chmod(0o700)
    config = {"version": 1, "profile": args.profile, "mode": "server",
              "server": {"id": identifier, "label": "Synthetic package Server",
                         "origin": origin, "private_http": True}}
    (shell / "mode.json").write_text(json.dumps(config))
    (shell / "mode.json").chmod(0o600)
    try:
        connected = launch(args, 1, expect_request=True)
        assert Handler.seen
        storage = args.data_root / "server-profiles" / identifier / "web" / "storage"
        assert storage.is_dir()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        disconnected = launch(args, 2, expect_request=False)
        assert json.loads((shell / "mode.json").read_text()) == config
        result = {"normal_executable": str(args.exe), "origin": origin,
                  "connected": connected, "outage_reopen": disconnected,
                  "server_storage": str(storage), "server_mode_retained": True,
                  "scope": "No native GUI input; visible outage wording covered in source Qt test"}
        (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({"pass": True, "server_requests": connected["server_requests"],
                          "outage_reopen": True, "local_root_absent": True}, indent=2))
    finally:
        if thread.is_alive():
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
