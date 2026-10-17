"""Fedora PID identity check before contacting an existing Desktop window."""
from __future__ import annotations

import json
from pathlib import Path
import os
import sys

from .isolation import AREA, FROZEN, assert_safe_leaf


def _windows_webview2_active() -> bool:
    selected = sys.modules.get("package_windows_webview2")
    return os.name == "nt" and selected is not None and getattr(selected, "ACTIVE", False) is True


def windows_source_launch_matches(arguments: list[str], name: str) -> bool:
    module = "desktop.webview2_entry" if _windows_webview2_active() else "desktop"
    return (arguments[1:3] == ["-m", module] and arguments.count("--profile") == 1
            and not any(item.startswith("--profile=") for item in arguments)
            and arguments[arguments.index("--profile") + 1:arguments.index("--profile") + 2] == [name])


def windows_default_data_root() -> Path | None:
    """Match the original OS argv's renderer-specific omitted-root meaning."""
    if FROZEN and _windows_webview2_active():
        from .windows_processes import captured_webview2_default_root
        return captured_webview2_default_root()
    from .windows_processes import default_data_root
    root = default_data_root()
    return root.parent / "WebView2Candidate" if _windows_webview2_active() else root


def windows_launch_matches(arguments: list[str], name: str, root: Path, default_root: Path | None) -> bool:
    """Parse only complete normal-package options, rejecting every duplicate form."""
    options = {}
    index = 1
    while index < len(arguments):
        item = arguments[index]
        key, separator, value = item.partition("=")
        if key=='--capture-window-events':
            if separator or key in options:return False
            options[key]=True;index+=1;continue
        if key not in {"--profile", "--data-root"} or key in options:
            return False
        if not separator:
            index += 1
            if index >= len(arguments) or arguments[index].startswith("--"):
                return False
            value = arguments[index]
        if not value:
            return False
        options[key] = value
        index += 1
    raw_root = options.get('--data-root', default_root)
    if raw_root is None:
        return False
    selected_root = Path(raw_root)
    return (options.get("--profile", "default") == name and selected_root.is_absolute()
            and os.path.normcase(str(selected_root)) == os.path.normcase(str(root)))


def _single_argument(cmdline: list[bytes], option: bytes) -> bytes | None:
    """Return one complete option value; duplicate or truncated options fail closed."""
    if cmdline.count(option) != 1:
        return None
    index = cmdline.index(option)
    return cmdline[index + 1] if index + 1 < len(cmdline) else None


def process_start_ticks(pid: int) -> int:
    if os.name == "nt":
        from .windows_processes import identity
        return identity(pid)["start"]
    if sys.platform == "darwin":
        from .macos_processes import identity
        return identity(pid)["start"]
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return int(fields[19])  # field 22, after comm and first two fields


def verified_instance(path: Path, name: str) -> str | None:
    assert_safe_leaf(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pid = data["pid"]
        if (data["name"] != name or not isinstance(pid, int) or pid <= 0
                or data["start_ticks"] != process_start_ticks(pid)):
            return None
        if os.name == "nt":
            from .windows_processes import identity, arguments
            found, me = identity(pid), identity(os.getpid())
            if found["image"] != me["image"] or found["sid"] != me["sid"]:
                return None
            args = arguments(pid)
            if "--desktop-worker" in args:
                return None
            if FROZEN:
                # Captured before HOME/LocalAppData is scoped to this profile;
                # never infer the real default from the synthetic environment.
                if not windows_launch_matches(args, name, AREA, windows_default_data_root()):
                    return None
            elif not windows_source_launch_matches(args, name):
                return None
            if identity(pid) != found:
                return None
            from .windows_files import owned
            owned(path, private=True)
            secret = data["secret"]
            return secret if isinstance(secret, str) and len(secret) == 64 else None
        if sys.platform == "darwin":
            from .macos_processes import identity, arguments_environment, launch_matches, _same_birth
            found, me = identity(pid), identity(os.getpid())
            status = path.stat()
            if (found["uid"] != os.getuid() or found["image"] != me["image"]
                    or status.st_uid != os.getuid() or status.st_mode & 0o077):
                return None
            args, _environment = arguments_environment(pid)
            if not launch_matches(args, name, AREA, frozen=FROZEN):
                return None
            after = identity(pid)
            if not _same_birth(found, after) or found["version"] != after["version"]:
                return None
            secret = data["secret"]
            return secret if isinstance(secret, str) and len(secret) == 64 else None
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        if FROZEN:
            root_kind = os.environ.get("DLMS_DESKTOP_ROOT_KIND", "disposable")
            if root_kind not in {"disposable", "installed-pilot"}:
                return None
            root_option = (b"--installed-pilot-root" if root_kind == "installed-pilot"
                           else b"--data-root")
            other_option = (b"--data-root" if root_option == b"--installed-pilot-root"
                            else b"--installed-pilot-root")
            same_executable = Path(f"/proc/{pid}/exe").resolve() == Path(sys.executable).resolve()
            if not same_executable:
                from .appimage_runtime import same_image_executable
                same_executable = same_image_executable(pid)
            if (not same_executable or Path(f"/proc/{pid}").stat().st_uid != os.getuid()
                    or b"--desktop-worker" in cmdline or other_option in cmdline
                    or _single_argument(cmdline, b"--profile") != name.encode()
                    or _single_argument(cmdline, root_option) != str(AREA).encode()):
                return None
        elif not (b"-m" in cmdline and b"desktop" in cmdline and b"--profile" in cmdline
                  and name.encode() in cmdline):
            return None
        secret = data["secret"]
        return secret if isinstance(secret, str) and len(secret) == 64 else None
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return None
