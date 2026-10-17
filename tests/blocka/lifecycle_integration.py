"""Fedora-only exact-PID lifecycle/security checks with disposable Qt profiles."""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time

from desktop.isolation import AREA, PROJECT, isolated_environment, profile_paths
from tests.gate1.lifecycle_integration import backend_child, live_pid, owned_descendants, wait_until


def launch(name: str, *flags: str):
    paths = profile_paths(name)
    env = isolated_environment(paths)
    env.update(PYTHONPATH=str(PROJECT), PYTHONNOUSERSITE="1")
    output = open(paths["logs"] / "blocka-launcher.log", "ab", buffering=0)
    process = subprocess.Popen(
        [sys.executable, "-m", "desktop", "--profile", name, "--automated", *flags],
        cwd=PROJECT, env=env, stdin=subprocess.DEVNULL, stdout=output,
        stderr=subprocess.STDOUT, start_new_session=True,
    )
    return process, output, paths


def manifest(paths):
    file = paths["root"] / "desktop-profile.json"
    return json.loads(file.read_text()) if file.exists() else None


def request(port: int, path: str, *, token=None, host=None, origin=None, method="GET") -> int:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    headers = {"Host": host or f"127.0.0.1:{port}"}
    if token is not None:
        headers["X-DLMS-Desktop-Token"] = token
    if origin is not None:
        headers["Origin"] = origin
    try:
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


def owned_token(pid: int) -> str:
    entries = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    return next(item.split(b"=", 1)[1].decode() for item in entries if item.startswith(b"DLMS_DESKTOP_NONCE="))


def stop_exact(process, output):
    if process.poll() is None:
        os.kill(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.kill(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
    output.close()


def main() -> int:
    suffix = secrets.token_hex(3)
    names = {key: f"blocka{key}{suffix}" for key in ("normal", "crash", "failure", "publish", "backenddeath")}
    facts = {"profiles": names}

    normal, normal_log, normal_paths = launch(names["normal"], "--synthetic-child")
    try:
        assert wait_until(lambda: manifest(normal_paths) is not None and backend_child(normal.pid) is not None, 20)
        saved = manifest(normal_paths)
        port = saved["port"]
        backend = backend_child(normal.pid)
        assert wait_until(lambda: len(owned_descendants(normal.pid)) >= 3, 12)
        captured = owned_descendants(normal.pid)
        facts["first_origin"] = f"http://127.0.0.1:{port}"
        token = owned_token(backend)
        facts["unauthorized_status"] = request(port, "/")
        facts["wrong_host_status"] = request(port, "/", token=token, host=f"localhost:{port}")
        facts["wrong_origin_status"] = request(port, "/", token=token, origin="http://example.org")
        facts["csrf_status"] = request(port, "/settings/appearance/save", token=token, method="POST")
        facts["native_null_without_csrf_status"] = request(port, "/settings/appearance/save", token=token, origin="null", method="POST")
        facts["action_null_origin_status"] = request(port, "/_desktop/recovery/action", token=token, origin="null", method="POST")
        facts["authorized_status"] = request(port, "/", token=token)
        duplicate, duplicate_log, _ = launch(names["normal"])
        try:
            facts["duplicate_exit"] = duplicate.wait(timeout=8)
            facts["single_backend"] = backend_child(normal.pid) == backend
        finally:
            stop_exact(duplicate, duplicate_log)
        assert facts["duplicate_exit"] == 0 and facts["single_backend"]
        assert [facts[k] for k in ("unauthorized_status", "wrong_host_status", "wrong_origin_status")] == [403, 403, 403]
        assert facts["csrf_status"] in (400, 403)
        assert facts["native_null_without_csrf_status"] in (400, 403)
        assert facts["action_null_origin_status"] == 403
        assert facts["authorized_status"] == 200
        facts["in_app_shutdown_status"] = request(port, "/api/shutdown", token=token, method="POST")
        facts["normal_close_exit"] = normal.wait(timeout=12)
        assert facts["in_app_shutdown_status"] == 200 and facts["normal_close_exit"] == 0
    finally:
        stop_exact(normal, normal_log)
    facts["normal_descendants_gone"] = wait_until(lambda: not any(live_pid(pid) for pid in captured), 8)
    assert facts["normal_descendants_gone"]
    # An unrelated exact listener owns the saved port. It must survive refusal.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(1)
    try:
        blocked, blocked_log, _ = launch(names["normal"])
        try:
            facts["occupied_exit"] = blocked.wait(timeout=12)
        finally:
            stop_exact(blocked, blocked_log)
        facts["listener_untouched"] = listener.fileno() >= 0
        facts["origin_unchanged_on_collision"] = manifest(normal_paths) == saved
        assert facts["occupied_exit"] != 0 and facts["listener_untouched"] and facts["origin_unchanged_on_collision"]
    finally:
        listener.close()

    failed, failed_log, failed_paths = launch(names["failure"], "--fail-backend")
    try:
        facts["backend_failure_exit"] = failed.wait(timeout=12)
    finally:
        stop_exact(failed, failed_log)
    facts["failed_backend_no_origin"] = manifest(failed_paths) is None
    assert facts["backend_failure_exit"] != 0 and facts["failed_backend_no_origin"]
    retry, retry_log, _ = launch(names["failure"], "--close-after-ready", "0.4")
    try:
        facts["backend_failure_retry_exit"] = retry.wait(timeout=18)
    finally:
        stop_exact(retry, retry_log)
    assert facts["backend_failure_retry_exit"] == 0 and manifest(failed_paths)

    bad, bad_log, bad_paths = launch(names["publish"], "--fail-manifest")
    try:
        facts["manifest_failure_exit"] = bad.wait(timeout=18)
    finally:
        stop_exact(bad, bad_log)
    facts["manifest_failure_no_origin"] = manifest(bad_paths) is None
    facts["manifest_failure_no_browser_storage"] = not any(bad_paths["web_storage"].iterdir())
    assert facts["manifest_failure_exit"] != 0 and facts["manifest_failure_no_origin"] and facts["manifest_failure_no_browser_storage"]
    retry, retry_log, _ = launch(names["publish"], "--close-after-ready", "0.4")
    try:
        facts["manifest_failure_retry_exit"] = retry.wait(timeout=18)
    finally:
        stop_exact(retry, retry_log)
    assert facts["manifest_failure_retry_exit"] == 0 and manifest(bad_paths)

    death, death_log, death_paths = launch(names["backenddeath"], "--synthetic-child")
    try:
        assert wait_until(lambda: manifest(death_paths) is not None and backend_child(death.pid) is not None, 20)
        leader = backend_child(death.pid)
        assert wait_until(lambda: len(owned_descendants(death.pid)) >= 3, 12)
        death_descendants = owned_descendants(death.pid)
        os.kill(leader, signal.SIGKILL)  # exact backend child, never a name match
        facts["unexpected_backend_exit"] = death.wait(timeout=12)
        facts["backend_death_message"] = "backend stopped unexpectedly" in (death_paths["logs"] / "blocka-launcher.log").read_text(errors="replace")
        facts["backend_death_cleanup"] = wait_until(lambda: not any(live_pid(pid) for pid in death_descendants), 8)
        assert facts["unexpected_backend_exit"] != 0 and facts["backend_death_message"] and facts["backend_death_cleanup"]
    finally:
        stop_exact(death, death_log)

    crash, crash_log, crash_paths = launch(names["crash"], "--synthetic-child")
    try:
        assert wait_until(lambda: manifest(crash_paths) is not None and backend_child(crash.pid) is not None, 20)
        old = manifest(crash_paths)
        old_backend = backend_child(crash.pid)
        assert wait_until(lambda: len(owned_descendants(crash.pid)) >= 3, 12)
        old_descendants = owned_descendants(crash.pid)
        os.kill(crash.pid, signal.SIGKILL)  # exact process started above
        crash.wait(timeout=5)
        relaunch, relaunch_log, _ = launch(names["crash"], "--close-after-ready", "0.5")
        try:
            facts["immediate_relaunch_exit"] = relaunch.wait(timeout=18)
        finally:
            stop_exact(relaunch, relaunch_log)
        facts["crash_origin_unchanged"] = manifest(crash_paths) == old
        facts["old_backend_gone"] = wait_until(lambda: not live_pid(old_backend), 8)
        facts["crash_descendants_gone"] = wait_until(lambda: not any(live_pid(pid) for pid in old_descendants), 8)
        assert facts["immediate_relaunch_exit"] == 0 and facts["crash_origin_unchanged"]
        assert facts["old_backend_gone"] and facts["crash_descendants_gone"]
    finally:
        stop_exact(crash, crash_log)

    report = AREA / f"blocka-lifecycle-{suffix}.json"
    report.write_text(json.dumps(facts, indent=2) + "\n")
    print(json.dumps(facts, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
