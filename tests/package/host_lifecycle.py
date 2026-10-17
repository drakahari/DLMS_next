"""Exact-process packaged duplicate and occupied-port checks on synthetic data."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import time

from tests.package.host_smoke import await_window, close_exact_window, window_for


def dismiss_owned_dialog(pid: int) -> dict:
    """Press Return only when X11's focused window belongs to this launcher."""
    active = subprocess.run(["xprop", "-root", "_NET_ACTIVE_WINDOW"],
                            capture_output=True, text=True, check=True).stdout.strip().split()[-1]
    property_text = subprocess.run(["xprop", "-id", active, "_NET_WM_PID"],
                                   capture_output=True, text=True).stdout.strip()
    if not property_text.endswith(f"= {pid}"):
        raise RuntimeError(f"Refusing to send Return to non-owned active window: {active} {property_text}")
    x11 = ctypes.CDLL("libX11.so.6")
    xtest = ctypes.CDLL("libXtst.so.6")
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XKeysymToKeycode.restype = ctypes.c_uint
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xtest.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    display = x11.XOpenDisplay(None)
    if not display:
        raise RuntimeError("Cannot open scoped X display")
    try:
        keycode = x11.XKeysymToKeycode(display, 0xFF0D)  # Return
        xtest.XTestFakeKeyEvent(display, keycode, 1, 0)
        xtest.XTestFakeKeyEvent(display, keycode, 0, 0)
        x11.XFlush(display)
    finally:
        x11.XCloseDisplay(display)
    return {"active_window": active, "pid_property": property_text, "pressed": "Return"}


def owned_windows(pid: int) -> list[tuple[str, str]]:
    lines = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True, check=True).stdout.splitlines()
    result = []
    for line in lines:
        parts = line.split(None, 4)
        if len(parts) == 5 and parts[2] == str(pid):
            result.append((parts[0], parts[4]))
    return result


def run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.exe = args.exe.resolve()
    args.data_root = args.data_root.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    root = args.data_root / "profiles" / args.profile
    manifest = json.loads((root / "desktop-profile.json").read_text())
    port = manifest["port"]
    env_root = args.output / "environment"
    env = {"PATH": "/nonexistent", "LANG": "C.UTF-8", "DISPLAY": os.environ["DISPLAY"],
           "QT_QPA_PLATFORM": "xcb", "XDG_RUNTIME_DIR": os.environ["XDG_RUNTIME_DIR"]}
    if "DBUS_SESSION_BUS_ADDRESS" in os.environ:
        env["DBUS_SESSION_BUS_ADDRESS"] = os.environ["DBUS_SESSION_BUS_ADDRESS"]
    for key, relative in (("HOME", "home"), ("XDG_DATA_HOME", "xdg/data"),
                          ("XDG_CONFIG_HOME", "xdg/config"), ("XDG_CACHE_HOME", "xdg/cache"),
                          ("TMPDIR", "tmp")):
        path = env_root / relative
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    command = [str(args.exe), "--profile", args.profile, "--data-root", str(args.data_root)]
    report = {"profile": args.profile, "origin_port": port}
    with (args.output / "owner.log").open("w") as log:
        owner = subprocess.Popen(command, cwd=args.cwd, env=env, stdout=log,
                                 stderr=subprocess.STDOUT)
        try:
            window, _ = await_window(owner.pid)
            time.sleep(1.3)
            second = subprocess.run(command, cwd=args.cwd, env=env,
                                    capture_output=True, text=True, timeout=15)
            report["duplicate"] = {"first_alive": owner.poll() is None,
                                   "second_exit": second.returncode,
                                   "second_output": second.stdout + second.stderr,
                                   "same_owner_pid": json.loads((root / "instance-owner.json").read_text())["pid"] == owner.pid}
            assert report["duplicate"]["first_alive"]
            assert report["duplicate"]["second_exit"] == 0
            assert report["duplicate"]["same_owner_pid"]
            (args.output / "duplicate-result.json").write_text(json.dumps(report, indent=2) + "\n")
            close_exact_window(window_for(owner.pid) or window)
            report["owner_normal_exit"] = owner.wait(timeout=20)
            assert report["owner_normal_exit"] == 0
        finally:
            if owner.poll() is None:
                owner.terminate()
                owner.wait(timeout=8)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(1)
    try:
        with (args.output / "occupied.log").open("w") as log:
            blocked = subprocess.Popen(command, cwd=args.cwd, env=env, stdout=log,
                                       stderr=subprocess.STDOUT)
            try:
                window, _ = await_window(blocked.pid)
                time.sleep(1.3)
                windows = owned_windows(blocked.pid)
                screenshots = []
                for index, (owned_window, title) in enumerate(windows):
                    screenshot = args.output / f"occupied-{index}.png"
                    try:
                        subprocess.run(["import", "-window", owned_window, str(screenshot)],
                                       check=True, timeout=4)
                        screenshots.append({"window": owned_window, "title": title,
                                            "path": str(screenshot)})
                    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                        pass
                report["occupied"] = {"listener_port": listener.getsockname()[1],
                                      "blocked_alive": blocked.poll() is None,
                                      "owner_record_exists": (root / "instance-owner.json").exists(),
                                      "windows": windows, "screenshots": screenshots}
                assert listener.getsockname()[1] == port
                report["occupied"]["dialog_dismissal"] = dismiss_owned_dialog(blocked.pid)
                try:
                    report["occupied"]["launcher_exit"] = blocked.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    report["occupied"]["launcher_exit"] = "close request timed out; exact launcher terminated"
                probe = socket.create_connection(("127.0.0.1", port), timeout=2)
                accepted, _ = listener.accept()
                probe.close()
                accepted.close()
                report["occupied"]["listener_still_accepts"] = True
                report["occupied"]["clean_dialog_exit"] = report["occupied"]["launcher_exit"] == 1
            finally:
                if blocked.poll() is None:
                    blocked.terminate()
                    blocked.wait(timeout=8)
    finally:
        listener.close()
    (args.output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    run()
