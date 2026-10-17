"""Host-display smoke for the relocated Fedora development package.

This driver never reads a Desktop profile outside the explicit disposable root.
It controls only windows owned by the subprocess it starts.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import time

from PIL import Image


def window_for(pid: int) -> str | None:
    result = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True, check=True)
    for line in result.stdout.splitlines():
        columns = line.split(None, 4)
        if len(columns) == 5 and columns[2] == str(pid) and columns[4].endswith("DLMS Desktop"):
            return columns[0]
    return None


def await_window(pid: int, timeout: float = 40) -> tuple[str, float]:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        found = window_for(pid)
        if found:
            return found, time.monotonic() - start
        time.sleep(0.1)
    raise RuntimeError(f"Packaged launcher {pid} did not open a window")


def close_exact_window(window: str) -> None:
    """Send WM_DELETE_WINDOW to a single Xwayland window, bypassing WM policy."""
    x11 = ctypes.CDLL("libX11.so.6")
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                              ctypes.c_long, ctypes.c_void_p]
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]

    class ClientMessageData(ctypes.Union):
        _fields_ = [("b", ctypes.c_char * 20), ("s", ctypes.c_short * 10),
                    ("l", ctypes.c_long * 5)]

    class ClientMessage(ctypes.Structure):
        _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong),
                    ("send_event", ctypes.c_int), ("display", ctypes.c_void_p),
                    ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong),
                    ("format", ctypes.c_int), ("data", ClientMessageData)]

    display = x11.XOpenDisplay(None)
    if not display:
        raise RuntimeError("Cannot open the scoped X11 display")
    try:
        event = ClientMessage()
        event.type = 33  # ClientMessage
        event.display = display
        event.window = int(window, 16)
        event.message_type = x11.XInternAtom(display, b"WM_PROTOCOLS", 0)
        event.format = 32
        event.data.l[0] = x11.XInternAtom(display, b"WM_DELETE_WINDOW", 0)
        event.data.l[1] = 0
        if not x11.XSendEvent(display, event.window, 0, 0, ctypes.byref(event)):
            raise RuntimeError("WM_DELETE_WINDOW was not sent")
        x11.XFlush(display)
    finally:
        x11.XCloseDisplay(display)


def owned_process_snapshot(root_pid: int) -> list[dict]:
    """Read only this launcher's live descendants and their mapped file paths."""
    pending = [root_pid]
    result = []
    while pending:
        pid = pending.pop(0)
        proc = Path("/proc") / str(pid)
        if not proc.exists():
            continue
        try:
            children = (proc / "task" / str(pid) / "children").read_text().split()
            pending.extend(int(child) for child in children)
            status = (proc / "status").read_text()
            rss = next((line.split()[1] for line in status.splitlines()
                        if line.startswith("VmRSS:")), "0")
            try:
                rollup = (proc / "smaps_rollup").read_text()
                pss = next((line.split()[1] for line in rollup.splitlines()
                            if line.startswith("Pss:")), "0")
            except OSError:
                pss = "0"
            maps = (proc / "maps").read_text().splitlines()
            mapped = sorted({line.split(None, 5)[5] for line in maps
                             if len(line.split(None, 5)) == 6 and line.split(None, 5)[5].startswith("/")})
            result.append({"pid": pid, "exe": os.readlink(proc / "exe"),
                           "rss_kib": int(rss), "pss_kib": int(pss),
                           "mapped_files": mapped})
        except (OSError, ValueError):
            continue
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hold-seconds", type=float, default=0)
    args = parser.parse_args()
    args.exe = args.exe.resolve()
    args.data_root = args.data_root.resolve()
    args.output = args.output.resolve()
    profile_manifest = args.data_root / "profiles" / args.profile / "desktop-profile.json"
    manifest_before = profile_manifest.exists()
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
    args.output.mkdir(parents=True, exist_ok=True)
    log_path = args.output / "launcher.log"
    started = time.monotonic()
    with log_path.open("w") as log:
        process = subprocess.Popen([str(args.exe), "--profile", args.profile,
                                    "--data-root", str(args.data_root)], cwd=args.cwd,
                                   env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            window, window_seconds = await_window(process.pid)
            capture = args.output / "window.png"
            backend_ready_seconds = None
            paint_seconds = None
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                if not manifest_before and backend_ready_seconds is None and profile_manifest.exists():
                    backend_ready_seconds = time.monotonic() - started
                current = window_for(process.pid)
                if not current:
                    time.sleep(0.2)
                    continue
                window = current
                try:
                    subprocess.run(["import", "-window", window, str(capture)], check=True,
                                   timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                    time.sleep(0.2)
                    continue
                with Image.open(capture) as frame:
                    red, green, blue = frame.convert("RGB").getpixel((100, 100))
                if max(red, green, blue) - min(red, green, blue) > 25:
                    paint_seconds = time.monotonic() - started
                    break
                time.sleep(0.2)
            if paint_seconds is None:
                raise RuntimeError("Packaged page did not paint within 40 seconds")
            time.sleep(args.hold_seconds)
            owned = owned_process_snapshot(process.pid)
            close_exact_window(window_for(process.pid) or window)
            try:
                code = process.wait(timeout=35)
            except subprocess.TimeoutExpired:
                raise RuntimeError("Packaged window did not exit after normal close")
            deadline = time.monotonic() + 5
            residual = [item["pid"] for item in owned if Path("/proc", str(item["pid"])).exists()]
            while residual and time.monotonic() < deadline:
                time.sleep(0.1)
                residual = [pid for pid in residual if Path("/proc", str(pid)).exists()]
            owner = args.data_root / "profiles" / args.profile / "instance-owner.json"
            report = {"pid": process.pid, "window": window, "window_seconds": window_seconds,
                      "backend_ready_seconds": backend_ready_seconds,
                      "first_usable_paint_seconds": paint_seconds,
                      "exit_seconds": time.monotonic() - started, "exit_code": code,
                      "owned_processes_at_paint": owned,
                      "residual_owned_pids_after_exit": residual,
                      "screenshot": str(capture), "owner_record_after_exit": owner.exists(),
                      "log": str(log_path)}
            (args.output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
            if code != 0 or residual:
                raise RuntimeError(f"Packaged close left exit={code}, owned processes={residual}")
            print(json.dumps({key: value for key, value in report.items()
                              if key != "owned_processes_at_paint"}
                             | {"owned_process_count": len(owned),
                                "owned_rss_kib": sum(item["rss_kib"] for item in owned),
                                "owned_pss_kib": sum(item["pss_kib"] for item in owned)}, indent=2))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=8)


if __name__ == "__main__":
    main()
