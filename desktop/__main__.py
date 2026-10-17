"""Run an explicitly named disposable DLMS Desktop profile."""
from __future__ import annotations

import argparse
import os
import sys

from .isolation import assert_safe_leaf, isolated_environment, profile_paths
from .ownership import verified_instance
from .server_mode import read_config, server_environment, shell_root


def main(argv=None) -> int:
    if os.name == "nt":
        from .windows_processes import own_launcher
        own_launcher()
    # Resolve only the configured chooser location before sandboxing application
    # HOME/XDG. This does not enumerate the folder or share it with the backend.
    from PySide6.QtCore import QStandardPaths
    from pathlib import Path
    documents_folder = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
                            or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.HomeLocation))
    from .webview2_runtime import active as webview2_active
    selection_private_roots = None
    backup_chooser_folders = None
    if os.name == 'nt' and webview2_active():
        from .windows_backup_chooser import configured_folders
        backup_chooser_folders = configured_folders()
        from .webview2_file_selection import _known_private_roots
        try:
            selection_private_roots = _known_private_roots()
        except (OSError, ValueError, RuntimeError) as exc:
            print(f'Windows file-selection protection metadata is unavailable: {exc}', file=sys.stderr)
            return 2
    parser = argparse.ArgumentParser(description="Disposable DLMS Desktop Fedora foundation")
    parser.add_argument("--profile", required=True, help="name under .gate1/profiles; never an existing DLMS profile")
    parser.add_argument("--debug-mix-timing", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument('--capture-window-events',action='store_true',help='Capture bounded lifecycle/content-layer metadata for 30 minutes; no page content or URLs')
    parser.add_argument("--automated", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--close-after-ready", type=float, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--synthetic-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--fail-backend", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--fail-manifest", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--pause-action", choices=("accepted", "committed"), help=argparse.SUPPRESS)
    parser.add_argument("--fail-action-cleanup", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--fail-action-accept", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        selected = read_config(args.profile)
    except (ValueError, OSError) as exc:
        print(f"Desktop mode selection needs inspection: {exc}", file=sys.stderr)
        return 2
    from .removal import read_tombstone, reconcile as reconcile_removal
    try:
        if selected["mode"] == "server":
            # The Server startup path does not adopt, reset, or reconcile a
            # Local dataset. A missing Local root is never recreated here;
            # explicit return to Local will refuse until ownership is clear.
            paths = profile_paths(args.profile, create=False)
        else:
            paths = None
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Desktop profile identity needs inspection: {exc}", file=sys.stderr)
        return 2
    try:
        if selected["mode"] == "server":
            tombstone = None
        else:
            tombstone = read_tombstone(args.profile)
        if tombstone is not None:
            paths = profile_paths(args.profile, create=False)
            env = isolated_environment(paths)
            os.environ.clear()
            os.environ.update(env)
            result = reconcile_removal(args.profile)
            if result["phase"] == "removed":
                print(f"Disposable profile {args.profile} was intentionally removed. Use a new profile name to start fresh; retained synthetic recovery evidence remains outside the removed target.")
                return 0
            print(f"Disposable profile {args.profile} removal is {result['phase']}; normal startup is blocked.", file=sys.stderr)
            return 2
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Disposable profile removal needs inspection: {exc}", file=sys.stderr)
        return 2
    # A rollback may have moved backend away. Reconcile before create=True can
    # recreate that directory and turn a recoverable rename into ambiguity.
    try:
        from .maintenance import read_marker, reconcile as reconcile_maintenance
        marker = read_marker(args.profile) if selected["mode"] == "local" else None
        if marker is not None:
            probe = profile_paths(args.profile, create=False)
            preflight_env = isolated_environment(probe)
            os.environ.clear()
            os.environ.update(preflight_env)
            result = reconcile_maintenance(args.profile)
            if result["phase"] not in {"rolled_back", "committed", "browser_check_pending", "browser_done"}:
                raise RuntimeError("Maintenance result has not been established")
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Disposable profile maintenance needs inspection: {exc}", file=sys.stderr)
        return 2
    try:
        paths = paths or profile_paths(args.profile)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    env = server_environment(args.profile) if selected["mode"] == "server" else isolated_environment(paths)
    os.environ.clear()
    os.environ.update(env)
    os.environ["PYTHONNOUSERSITE"] = "1"
    if args.debug_mix_timing:
        os.environ["DLMS_DESKTOP_DEBUG_MIX_TIMING"] = "1"
    if args.automated:
        os.environ["DLMS_DESKTOP_AUTOMATED"] = "1"
    if args.close_after_ready > 0:
        os.environ["DLMS_DESKTOP_CLOSE_AFTER_READY_MS"] = str(round(args.close_after_ready * 1000))
    if args.synthetic_child and args.automated:
        os.environ["DLMS_DESKTOP_TEST_CHILD"] = "1"
    if args.fail_backend and args.automated:
        os.environ["DLMS_DESKTOP_TEST_FAIL_BACKEND"] = "1"
    if args.fail_manifest and args.automated:
        os.environ["DLMS_DESKTOP_TEST_FAIL_MANIFEST"] = "1"
    if args.pause_action and args.automated:
        os.environ["DLMS_DESKTOP_TEST_PAUSE_PHASE"] = args.pause_action
    if args.fail_action_cleanup and args.automated:
        os.environ["DLMS_DESKTOP_TEST_FAIL_ACTION_CLEANUP"] = "1"
    if args.fail_action_accept and args.automated:
        os.environ["DLMS_DESKTOP_TEST_FAIL_ACTION_ACCEPT"] = "1"

    # Import Qt only after HOME/XDG/TMP and application data have been scoped.
    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication
    from .identity import configure_application_identity
    from .frozen_runtime import instance_socket_name
    from .shell import DesktopWindow, send_focus
    from .webview2_runtime import active as webview2_active
    if webview2_active():
        from .webview2_shell import DesktopWindow

    if sys.platform == 'darwin':
        from .macos_application import MacApplication
        application = MacApplication(sys.argv[:1])
    else:
        application = QApplication(sys.argv[:1])
    # Wayland advertises this exact desktop-file base name as the top-level
    # app ID. It identifies a future launcher; it does not install one.
    configure_application_identity(application)
    owner_root = shell_root(args.profile)
    instance_path = owner_root / "instance.lock"
    assert_safe_leaf(instance_path)
    lock = QLockFile(str(instance_path))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        secret = verified_instance(owner_root / "instance-owner.json", args.profile)
        if secret and send_focus(instance_socket_name(owner_root), secret):
            print("DLMS Desktop is already open for this disposable profile; focused its window.")
            return 0
        print("DLMS Desktop profile is locked, but window ownership could not be verified; no IPC or second backend was started.", file=sys.stderr)
        return 2
    try:
        try:
            selection_options = {'selection_private_roots': selection_private_roots,
                                 'backup_chooser_folders': backup_chooser_folders} if os.name == 'nt' and webview2_active() else {}
            window = DesktopWindow(paths, args.profile, documents_folder=documents_folder, **selection_options)
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"DLMS Desktop could not own this profile window: {exc}", file=sys.stderr)
            return 2
        if args.capture_window_events:
            from .window_events import WindowEvents
            try:
                window.window_events=WindowEvents(window)
                application.aboutToQuit.connect(lambda:window.window_events.stop('closing'))
            except (OSError,ValueError):
                window.statusBar().showMessage('Window event capture unavailable; no diagnostic log was opened.')
        if sys.platform == 'darwin':
            application.bind_window(window)
        window.show()
        window.start()
        if window.failed_reason and args.automated:
            window.close()
            return 1
        code = application.exec()
        return 1 if window.failed_reason else code
    finally:
        if 'window' in locals():
            window.close()
        lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
