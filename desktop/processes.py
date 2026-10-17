"""Linux cleanup of exact task-owned descendants after a backend leader exits."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import sys
import time


def _owned_pids(group: int, nonce: str) -> list[int]:
    if not Path("/proc").is_dir():
        return []
    marker = f"DLMS_DESKTOP_NONCE={nonce}".encode()
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            if int(fields[2]) != group:  # state, parent PID, process group
                continue
            if marker in (entry / "environ").read_bytes().split(b"\0"):
                found.append(int(entry.name))
        except (OSError, ValueError, IndexError):
            continue
    return found


def _signal_identity(pid: int, group: int, nonce: str, action: signal.Signals):
    """Open a pidfd, then verify group and nonce before signaling that identity."""
    try:
        fd = os.pidfd_open(pid)
    except (OSError, AttributeError):
        return
    try:
        if pid in _owned_pids(group, nonce):
            signal.pidfd_send_signal(fd, action)
    except (OSError, ProcessLookupError):
        pass
    finally:
        os.close(fd)


def reap_owned_group(group: int, nonce: str, *, exclude: set[int] | None = None) -> list[int]:
    """Terminate only Linux PIDs bearing this exact per-launch nonce and group."""
    if os.name == "nt":
        from .windows_processes import reap
        if exclude:
            raise RuntimeError("Windows job cleanup cannot exclude job members")
        return reap(group, nonce)
    if sys.platform == "darwin":
        from .macos_processes import reap
        return reap(group, nonce, exclude=exclude)
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        return []  # Native-platform process trees remain a later qualification gate.
    excluded = exclude or set()
    for pid in _owned_pids(group, nonce):
        if pid in excluded:
            continue
        _signal_identity(pid, group, nonce, signal.SIGTERM)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and any(pid not in excluded for pid in _owned_pids(group, nonce)):
        time.sleep(0.05)
    for pid in _owned_pids(group, nonce):
        if pid in excluded:
            continue
        _signal_identity(pid, group, nonce, signal.SIGKILL)
    return [pid for pid in _owned_pids(group, nonce) if pid not in excluded]
