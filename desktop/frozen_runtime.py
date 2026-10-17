"""Source-mode and PyInstaller child dispatch without changing app contracts."""
from __future__ import annotations

import os
import hashlib
from pathlib import Path
import sys

from .isolation import FROZEN, PROJECT


def spawn_process(command, *, bound=None, **kwargs):
    if os.name == "nt":
        from .windows_processes import spawn
        return spawn(command, bound=bound, **kwargs)
    if sys.platform == "darwin":
        from .macos_processes import spawn
        return spawn(command, bound=bound, **kwargs)
    import subprocess
    return subprocess.Popen(command, **kwargs)


def child_command(role: str, *args: str) -> list[str]:
    if role not in {"backend", "adopt", "maintenance", "removal"}:
        raise ValueError("Unknown Desktop worker role")
    if FROZEN:
        return [sys.executable, "--desktop-worker", role, *args]
    if sys.platform == "darwin" and getattr(sys.modules.get("package_macos"), "ACTIVE", False):
        return [sys.executable, "-m", "package_macos", "--desktop-worker", role, *args]
    return [sys.executable, "-m", f"desktop.{role}", *args]


def source_environment(env: dict[str, str], *, include_app: bool = True) -> None:
    from .webview2_runtime import active as webview2_active
    if webview2_active():
        env['DLMS_WINDOWS_WEBVIEW2_POLICY'] = '1'
    if not FROZEN:
        roots = (PROJECT,)
        env["PYTHONPATH"] = os.pathsep.join(str(root) for root in roots)


def source_import_path() -> None:
    if not FROZEN:
        sys.path.insert(0, str(PROJECT))


def abstract_instance_socket() -> bool:
    """Fedora package IPC avoids Linux's 108-byte filesystem socket limit."""
    return FROZEN and sys.platform.startswith("linux")


def instance_socket_name(profile_root: Path) -> str:
    if os.name == "nt":
        from .windows_processes import current, process_sid
        identity = (process_sid(current()) + ":" + os.path.normcase(str(profile_root.resolve()))).encode("utf-8")
        return "dlms-desktop-" + hashlib.sha256(identity).hexdigest()
    if sys.platform == "darwin":
        from .macos_processes import instance_socket_name as macos_socket_name
        return macos_socket_name(profile_root)
    if abstract_instance_socket():
        identity = f"{os.getuid()}:{profile_root.resolve()}".encode("utf-8")
        return "dlms-desktop-" + hashlib.sha256(identity).hexdigest()
    return str(profile_root / "instance.sock")
