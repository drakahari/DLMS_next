"""Fedora-only, task-PID-scoped lifecycle checks for the disposable Qt shell."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import urlopen

from desktop.isolation import PROJECT, isolated_environment, profile_paths


def port_open() -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.1)
        return sock.connect_ex(("127.0.0.1", 9001)) == 0


def wait_until(test, seconds=12):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if test():
            return True
        time.sleep(0.1)
    return False


def backend_child(parent_pid: int) -> int | None:
    children_file = Path(f"/proc/{parent_pid}/task/{parent_pid}/children")
    try:
        children = [int(x) for x in children_file.read_text().split()]
    except OSError:
        return None
    for pid in children:
        try:
            argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if len(argv) >= 3 and argv[1:3] == [b"-m", b"desktop.backend"]:
            return pid
    return None


def owned_descendants(parent_pid: int) -> list[int]:
    """Capture only PIDs proven to descend from this task-owned launcher."""
    found = []
    pending = [parent_pid]
    while pending:
        parent = pending.pop()
        try:
            children = [int(x) for x in Path(f"/proc/{parent}/task/{parent}/children").read_text().split()]
        except OSError:
            continue
        found.extend(children)
        pending.extend(children)
    return found


def live_pid(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except OSError:
        return False


def launch(name: str, extra: list[str] | None = None):
    paths = profile_paths(name)
    env = isolated_environment(paths)
    env["PYTHONPATH"] = str(PROJECT)
    env["PYTHONNOUSERSITE"] = "1"
    out = open(paths["logs"] / "launcher.log", "ab", buffering=0)
    process = subprocess.Popen(
        [sys.executable, "-m", "desktop", "--profile", name, "--automated", *(extra or [])],
        cwd=PROJECT, env=env, stdin=subprocess.DEVNULL, stdout=out,
        stderr=subprocess.STDOUT, start_new_session=True,
    )
    return process, out, paths


def rss_kib(pid: int) -> int | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except OSError:
        pass
    return None


def main() -> int:
    assert not port_open(), "port 9001 was already occupied; test did not start"
    result = {}

    first, first_out, paths = launch("lifecycle01", ["--synthetic-child"])
    try:
        assert wait_until(lambda: port_open() and backend_child(first.pid) is not None), "first desktop did not start"
        backend = backend_child(first.pid)
        assert wait_until(lambda: len(owned_descendants(backend)) >= 1), "synthetic backend child did not start"
        backend_descendants = owned_descendants(backend)
        result["first_launcher_pid"] = first.pid
        result["first_backend_pid"] = backend
        second, second_out, _ = launch("lifecycle01")
        try:
            second_code = second.wait(timeout=8)
        finally:
            second_out.close()
        result["duplicate_exit"] = second_code
        result["first_survived_duplicate"] = first.poll() is None
        result["same_backend_after_duplicate"] = backend_child(first.pid) == backend
        assert second_code == 0 and result["first_survived_duplicate"] and result["same_backend_after_duplicate"]
        # Kill only the exact backend child started by this launcher.
        os.kill(backend, signal.SIGKILL)
        result["launcher_detected_backend_exit"] = wait_until(lambda: first.poll() is not None, 8)
        result["port_closed_after_backend_exit"] = wait_until(lambda: not port_open(), 8)
        result["backend_descendants_cleaned_after_exit"] = wait_until(lambda: not any(live_pid(pid) for pid in backend_descendants), 8)
    finally:
        if first.poll() is None:
            first.terminate()
            try: first.wait(timeout=6)
            except subprocess.TimeoutExpired: first.kill(); first.wait(timeout=3)
        first_out.close()
    assert result["launcher_detected_backend_exit"] and result["port_closed_after_backend_exit"] and result["backend_descendants_cleaned_after_exit"]

    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 9001))
    listener.listen(1)
    try:
        occupied, occupied_out, occupied_paths = launch("occupied01")
        try:
            code = occupied.wait(timeout=15)
        finally:
            occupied_out.close()
        result["occupied_exit"] = code
        result["own_listener_untouched"] = listener.fileno() >= 0
        result["occupied_message"] = "Backend exited during startup" in (occupied_paths["logs"] / "launcher.log").read_text(errors="replace")
        assert code != 0 and result["own_listener_untouched"] and result["occupied_message"]
    finally:
        listener.close()
    assert not port_open()

    failed, failed_out, failed_paths = launch("failed01", ["--fail-backend"])
    try:
        result["startup_failure_exit"] = failed.wait(timeout=12)
        failure_log = (failed_paths["logs"] / "launcher.log").read_text(errors="replace")
        result["startup_failure_explained"] = ("Backend exited during startup" in failure_log
                                                and "backend.log" in failure_log)
        result["startup_failure_port_closed"] = not port_open()
        assert result["startup_failure_exit"] != 0 and result["startup_failure_explained"] and result["startup_failure_port_closed"]
    finally:
        if failed.poll() is None:
            failed.terminate(); failed.wait(timeout=5)
        failed_out.close()

    forced, forced_out, forced_paths = launch("forced01", ["--synthetic-child"])
    try:
        assert wait_until(lambda: port_open() and backend_child(forced.pid) is not None), "forced-launch desktop did not start"
        forced_backend = backend_child(forced.pid)
        descendants = owned_descendants(forced.pid)
        os.kill(forced.pid, signal.SIGKILL)  # exact task-owned launcher PID
        forced.wait(timeout=5)
        result["old_backend_live_at_relaunch"] = live_pid(forced_backend)
        reopened, reopened_out, _ = launch("forced01", ["--close-after-ready", "1"])
        try:
            result["immediate_relaunch_exit"] = reopened.wait(timeout=14)
            result["immediate_relaunch_backend_was_unique"] = result["immediate_relaunch_exit"] == 0
        finally:
            if reopened.poll() is None:
                reopened.terminate(); reopened.wait(timeout=5)
            reopened_out.close()
        result["backend_closed_after_forced_launcher_kill"] = wait_until(lambda: not live_pid(forced_backend) and not port_open(), 8)
        result["task_descendants_after_forced_kill"] = [pid for pid in descendants if live_pid(pid)]
        assert result["backend_closed_after_forced_launcher_kill"]
        assert result["immediate_relaunch_backend_was_unique"]
        assert not result["task_descendants_after_forced_kill"]
    finally:
        if forced.poll() is None:
            forced.kill(); forced.wait(timeout=3)
        forced_out.close()
    result["port_closed_final"] = not port_open()
    assert result["port_closed_final"]

    normal, normal_out, _ = launch("normal01", ["--close-after-ready", "2"])
    try:
        assert wait_until(lambda: port_open() and backend_child(normal.pid) is not None), "normal-close desktop did not start"
        try:
            with urlopen("http://127.0.0.1:9001/", timeout=1) as response:
                result["unauthenticated_loopback_http"] = response.status
        except HTTPError as error:
            result["unauthenticated_loopback_http"] = error.code
        assert result["unauthenticated_loopback_http"] == 403
        time.sleep(0.8)  # let the Qt page create its render helpers before the RSS snapshot
        normal_descendants = owned_descendants(normal.pid)
        result["ready_rss_kib"] = {str(pid): rss_kib(pid) for pid in [normal.pid, *normal_descendants]}
        result["normal_close_exit"] = normal.wait(timeout=10)
        result["normal_close_port_closed"] = wait_until(lambda: not port_open(), 6)
        result["normal_close_descendants_live"] = [pid for pid in normal_descendants if live_pid(pid)]
        assert result["normal_close_exit"] == 0 and result["normal_close_port_closed"] and not result["normal_close_descendants_live"]
    finally:
        if normal.poll() is None:
            normal.terminate(); normal.wait(timeout=5)
        normal_out.close()
    output = profile_paths("lifecycle01")["root"] / "lifecycle-evidence.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
