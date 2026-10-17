"""Explicit Fedora package entry and frozen worker multiplexer.

The installed pilot uses a distinct, installer-created synthetic root. Neither
launch form searches for or falls back to an existing DLMS profile.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
from pathlib import Path
import re
import sys

# Shared flock survives only the intentional guard exec. Each runtime keeps its
# descriptors close-on-exec so unrelated external applications cannot retain it.
_INSTALL_LOCKS = {}


def _seal_private_descriptors():
    """Fedora exec boundary: retain ownership here, prevent external inheritance.

    Do this before starting Qt/threads, and again before external dispatch. The
    verified same-process guard handoff below is the sole intentional exception.
    Standard streams remain available for ordinary launch logging.
    """
    if sys.platform == "darwin":
        from .macos_processes import seal_private_descriptors
        seal_private_descriptors()
        return
    if os.name == "nt":
        # UCRT low-level descriptors have an 8192-entry ceiling. The stdio
        # stream limit is smaller and would miss valid os.open/dup2 descriptors;
        # Python's msvcrt module has no getmaxstdio API. Do not change CRT limits.
        for fd in range(3, 8192):
            try:
                os.set_inheritable(fd, False)
            except OSError as exc:
                if exc.errno != errno.EBADF:
                    raise
        return
    try:
        descriptors = os.listdir("/proc/self/fd")
        for name in descriptors:
            fd = int(name)
            if fd < 3:
                continue
            try:
                os.set_inheritable(fd, False)
            except OSError as exc:
                if exc.errno != errno.EBADF:  # enumeration handle has closed
                    raise
    except (OSError, ValueError) as exc:
        raise ValueError("Cannot secure private descriptors before launching another program") from exc


def _exec_active(path, argv):
    """Carry tracked installation locks across one validated same-process exec."""
    try:
        for fd in _INSTALL_LOCKS.values():
            os.set_inheritable(fd, True)
        os.execv(path, argv)
    finally:
        # Reached only if exec fails; never leave external launches inheritable.
        for fd in _INSTALL_LOCKS.values():
            os.set_inheritable(fd, False)


def _installation_read_lock(opt):
    import fcntl
    key = str(opt)
    if key in _INSTALL_LOCKS:
        return
    leaf = opt / 'manual-replacement.lock'
    if not leaf.exists() and not leaf.is_symlink():
        return  # Legacy install; existing instance/writer locks still apply.
    fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        import stat
        if st.st_uid != os.getuid() or st.st_mode & 0o077 or not stat.S_ISREG(st.st_mode):
            raise ValueError('Installation lock identity is unsafe')
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('Installation replacement is active; launch refused') from exc
        os.set_inheritable(fd, False)
        _INSTALL_LOCKS[key] = fd
    except BaseException:
        os.close(fd)
        raise


_MARKER = ".dlms-desktop-disposable.json"
_MARKER_VALUE = {"kind": "dlms-desktop-fedora-package-feasibility", "version": 1}
_PILOT_MARKER = ".dlms-desktop-installed-pilot.json"
_PILOT_PROFILE = "pilot01"
_ROLES = {"backend", "adopt", "maintenance", "removal"}
_CHECKS = {
    "linux-ai-parity": "tests.linux_windows.gui_matrix",
    "linux-export-parity": "tests.linux_windows.gui_exports",
    "ordinary-files": "tests.file_selection.gui_workflows",
    "ordinary-file-boundary": "tests.file_selection.gui_boundary",
    "ordinary-file-focus": "tests.file_selection.gui_focus",
    "daily-downloads": "tests.daily_use.gui_downloads",
    "daily-certifications": "tests.daily_use.journeys_certifications",
    "daily-validation": "tests.daily_use.journeys_validation",
    "server-navigation": "tests.server_mode.gui_navigation_surface",
    "shutdown": "tests.shutdown.gui_lifecycle",
    "foundation": "tests.gate1.gui_foundation",
    "compatibility": "tests.gate1.gui_compatibility",
    "ocr-pdf": "tests.gate1.gui_ocr_pdf",
    "clipboard": "tests.gate1.gui_clipboard_focus",
    "study-pending": "tests.gate1.gui_study_pending",
    "exam-recovery": "tests.gate1.gui_exam_recovery",
    "gate-a-retry": "tests.data_safety.gui_managed_retry",
    "gate-a-stage": "tests.data_safety.managed_import_smoke",
    "gate-a-audit": "tests.data_safety.audit_managed_import",
    "gate-a-completed-repeat": "tests.package.gui_completed_import",
    "matching": "tests.parity.gui_matching_mixed",
    "durable-crash": "tests.blocka.gui_durable_crash",
    "adopt-backup": "tests.blockb.gui_menu_adoption",
    "installed-adopt-backup": "tests.blockb.gui_menu_adoption",
    "installed-daily-backup": "tests.daily_backup.gui_workflow",
    "adopt-reopen": "tests.blockb.gui_adoption",
    "maintenance-scope": "tests.completion.gui_maintenance_scope",
    "pending-import-gate": "tests.data_safety.gui_pending_import_gate",
    "mixed-quiz": "tests.package.gui_mixed_packaged",
}


def _root(path: str, *, kind: str = "disposable", profile: str | None = None,
          require_active_executable: bool = True) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute() or not candidate.is_dir() or candidate.is_symlink():
        if kind == "disposable":
            raise ValueError("Packaged Desktop needs an existing absolute disposable data directory")
        raise ValueError("Packaged Desktop needs an existing absolute installed-pilot data directory")
    for component in (candidate, *candidate.parents):
        if component.is_symlink():
            raise ValueError("Disposable data path contains a symlink")
    payload = Path(sys._MEIPASS).resolve()
    resolved = candidate.resolve()
    if resolved.is_relative_to(payload) or payload.is_relative_to(resolved):
        raise ValueError("Disposable data must be separate from the application payload")
    if kind not in {"disposable", "installed-pilot"}:
        raise ValueError("Unknown packaged Desktop data-root kind")
    marker = candidate / (_MARKER if kind == "disposable" else _PILOT_MARKER)
    if marker.is_symlink() or not marker.is_file() or marker.stat().st_size > 512:
        raise ValueError("Scoped data root marker is missing or unsafe")
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Scoped data root marker is unreadable") from exc
    if kind == "disposable":
        if value != _MARKER_VALUE:
            raise ValueError("Disposable data root marker does not match this feasibility build")
    else:
        if len(candidate.parents) < 3 or candidate != candidate.parents[2] / ".local/share/dlms-desktop-pilot":
            raise ValueError("Installed pilot root is outside its dedicated per-user namespace")
        from .management_state import assert_resolved
        assert_resolved(candidate.parents[2])
        install_manifest = candidate.parents[2] / ".local/opt/dlms-desktop/pilot-install.json"
        for component in (install_manifest, *install_manifest.parents):
            if component == candidate.parents[2]:
                break
            if component.is_symlink():
                raise ValueError("Installed pilot manifest path contains a symlink")
        if getattr(sys, "frozen", False):
            _installation_read_lock(install_manifest.parent)
        if (install_manifest.is_symlink() or not install_manifest.is_file()
                or install_manifest.stat().st_size > 131072):
            raise ValueError("Installed pilot manifest is unavailable or unsafe")
        try:
            installed = json.loads(install_manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Installed pilot manifest needs inspection") from exc
        if (not isinstance(value, dict)
                or set(value) != {"kind", "version", "uid", "root", "profile", "install_id"}
                or value["kind"] != "dlms-desktop-installed-synthetic-pilot"
                or value["version"] != 1 or value["uid"] != os.getuid()
                or value["root"] != str(candidate) or value["profile"] != _PILOT_PROFILE
                or not isinstance(value["install_id"], str)
                or re.fullmatch(r"[0-9a-f]{32}", value["install_id"]) is None
                or not isinstance(installed, dict) or installed.get("phase") != "complete"
                or installed.get("install_id") != value["install_id"]
                or installed.get("owned_paths", {}).get("data") != str(candidate)
                or (profile is not None and profile != value["profile"])):
            raise ValueError("Installed pilot identity does not match this root and profile")
        # A replacement is a code transaction. Reject an incomplete receipt,
        # a stale pointer, or an executable reached through the wrong version.
        # The application never chooses a different version or data root here.
        opt_root = install_manifest.parent
        if (opt_root / "pilot-replacement.json").exists() or (opt_root / "pilot-replacement.json").is_symlink():
            raise ValueError("Installed pilot replacement needs reconciliation")
        from .install_manifest import validate_paths
        _inventories, active, _guard = validate_paths(installed, candidate.parents[2])
        target = f"versions/{active}"
        if getattr(sys, "frozen", False) and require_active_executable:
            selected_exe = opt_root / target / "DLMS-Desktop" / "DLMS-Desktop"
            if (selected_exe.is_symlink() or not selected_exe.is_file()
                    or Path(sys.executable).resolve() != selected_exe.resolve()):
                raise ValueError("Installed pilot executable does not match the active version")
        if candidate.stat().st_uid != os.getuid() or candidate.stat().st_mode & 0o077:
            raise ValueError("Installed pilot data root is not privately owned")
    return candidate


def main(*, instrumented: bool = False) -> int:
    if not getattr(sys, "frozen", False):
        raise RuntimeError("This entry point is only for a frozen Desktop build")
    _seal_private_descriptors()
    argv = sys.argv[1:]
    if argv[:1] == ['--appimage-launch']:
        from .appimage_runtime import launch
        launch(argv[1:])
        raise AssertionError('AppImage exec unexpectedly returned')
    if argv[:1] == ['--manage']:
        from package_fedora.manage import main as manage_main
        return manage_main(argv[1:])
    if not instrumented and argv[:1] == ["--pilot-launch"]:
        parser = argparse.ArgumentParser(description="Pilot same-process launcher identity gate")
        parser.add_argument("--pilot-launch", action="store_true", required=True)
        parser.add_argument("--profile", required=True)
        parser.add_argument("--installed-pilot-root", required=True)
        args = parser.parse_args(argv)
        root = Path(args.installed_pilot_root)
        if args.profile != _PILOT_PROFILE or not root.is_absolute():
            raise ValueError("Pilot launcher identity is invalid")
        _root(str(root), kind="installed-pilot", profile=args.profile,
              require_active_executable=False)
        from .install_manifest import decode
        installed = root.parents[2] / ".local/opt/dlms-desktop/pilot-install.json"
        _, _, guard = decode(json.loads(installed.read_text()), root.parents[2])
        expected_guard = installed.parent / 'versions' / guard / 'DLMS-Desktop/DLMS-Desktop'
        if Path(sys.executable).resolve() != expected_guard.resolve():
            raise ValueError("Pilot launcher guard does not match the manifest")
        selected = root.parents[2] / ".local/opt/dlms-desktop/current/DLMS-Desktop/DLMS-Desktop"
        _exec_active(str(selected), [str(selected), "--profile", args.profile,
                                 "--installed-pilot-root", str(root)])
        raise AssertionError("Pilot launcher exec unexpectedly returned")
    if not instrumented:
        for key in tuple(os.environ):
            if key == "DLMS_DESKTOP_AUTOMATED" or key.startswith("DLMS_DESKTOP_TEST_"):
                os.environ.pop(key, None)
        if any(arg.startswith(("--automated", "--fail-", "--pause-", "--synthetic-child", "--close-after-ready")) for arg in argv):
            raise ValueError("Development fault-injection options are unavailable in the normal package")
    if len(argv) >= 2 and argv[0] == "--desktop-worker":
        role = argv[1]
        if role not in _ROLES or not os.environ.get("DLMS_DESKTOP_DATA_ROOT"):
            raise ValueError("Desktop worker role or scoped data root is missing")
        _root(os.environ["DLMS_DESKTOP_DATA_ROOT"],
              kind=os.environ.get("DLMS_DESKTOP_ROOT_KIND", "disposable"))
        owner_key = {"backend": "DLMS_DESKTOP_PARENT_PID", "adopt": "DLMS_DESKTOP_ADOPT_OWNER_SECRET",
                     "maintenance": "DLMS_DESKTOP_MAINT_OWNER_SECRET",
                     "removal": "DLMS_DESKTOP_REMOVE_OWNER_SECRET"}[role]
        if not os.environ.get(owner_key):
            raise ValueError("Packaged Desktop worker has no owning launcher context")
        sys.argv = [sys.argv[0], *argv[2:]]
        module = __import__(f"desktop.{role}", fromlist=["main"])
        return int(module.main() or 0)
    if instrumented and len(argv) >= 2 and argv[0] == "--packaged-check":
        check = argv[1]
        if check not in _CHECKS:
            raise ValueError("Unknown instrumented package check")
        parser = argparse.ArgumentParser(description="Instrumented packaged Qt check")
        parser.add_argument("--profile", required=True)
        roots = parser.add_mutually_exclusive_group(required=True)
        roots.add_argument("--data-root")
        roots.add_argument("--installed-pilot-root")
        args, extras = parser.parse_known_args(argv[2:])
        kind = "installed-pilot" if args.installed_pilot_root else "disposable"
        if kind == "installed-pilot" and check not in {"installed-adopt-backup", "installed-daily-backup"}:
            raise ValueError("Installed-layout acceptance is limited to the adoption check")
        root = _root(args.installed_pilot_root or args.data_root, kind=kind,
                     profile=args.profile)
        os.environ["DLMS_DESKTOP_DATA_ROOT"] = str(root)
        os.environ["DLMS_DESKTOP_ROOT_KIND"] = kind
        os.environ.pop("PYTHONPATH", None)
        os.environ.pop("PYTHONHOME", None)
        if check == "gate-a-stage":
            if len(extras) != 1 or extras[0] not in {"data-safety-two.zip", "closure-portable-media.zip"}:
                raise ValueError("Instrumented stage requires one approved synthetic bundle name")
            sys.argv = [sys.argv[0], args.profile, "stage-seed", extras[0]]
        else:
            sys.argv = [sys.argv[0], "--profile", args.profile, *extras]
        module = __import__(_CHECKS[check], fromlist=["main"])
        return int(module.main() or 0)
    parser = argparse.ArgumentParser(description="DLMS Desktop Fedora development package")
    parser.add_argument("--profile", required=True)
    roots = parser.add_mutually_exclusive_group(required=True)
    roots.add_argument("--data-root", help="pre-marked disposable Desktop data directory")
    roots.add_argument("--installed-pilot-root", help="installer-created synthetic pilot root")
    args, extras = parser.parse_known_args(argv)
    if extras and not instrumented:
        parser.error("Unrecognized or development-only option: " + " ".join(extras))
    kind = "installed-pilot" if args.installed_pilot_root else "disposable"
    root = _root(args.installed_pilot_root or args.data_root, kind=kind, profile=args.profile)
    os.environ["DLMS_DESKTOP_DATA_ROOT"] = str(root)
    os.environ["DLMS_DESKTOP_ROOT_KIND"] = kind
    os.environ.pop("PYTHONPATH", None)
    os.environ.pop("PYTHONHOME", None)
    from .__main__ import main as desktop_main
    return desktop_main(["--profile", args.profile, *extras])
