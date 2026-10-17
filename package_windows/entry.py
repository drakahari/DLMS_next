"""Normal Windows executable entry. No fault injection or original builder."""
from pathlib import Path
import argparse
import json
import os
import sys

MARKER = ".dlms-desktop-windows-candidate.json"
IDENTITY = {"kind": "dlms-desktop-windows-candidate", "version": 1}

def root_path(path, *, create=False):
    from desktop.windows_files import assert_path, owned
    root = Path(path)
    assert_path(root)
    payload = Path(sys.executable).resolve().parent
    if root.resolve().is_relative_to(payload) or payload.is_relative_to(root.resolve()):
        raise ValueError("Windows Desktop data must be outside the application payload")
    if create and not root.exists():
        root.mkdir(mode=0o700, parents=True)
        from desktop.profile_state import atomic_json
        atomic_json(root / MARKER, IDENTITY)
    owned(root, private=True)
    marker = root / MARKER
    assert_path(marker, leaf=True)
    if not marker.is_file() or marker.stat().st_size > 512 or json.loads(marker.read_text()) != IDENTITY:
        raise ValueError("Windows candidate data marker is missing or invalid; existing data was not adopted")
    return root.resolve()

def main():
    for key in tuple(os.environ):
        if key == "DLMS_DESKTOP_AUTOMATED" or key.startswith("DLMS_DESKTOP_TEST_"):
            os.environ.pop(key, None)
    argv = sys.argv[1:]
    if argv[:1] == ["--desktop-worker"]:
        if len(argv) < 2 or argv[1] not in {"backend", "adopt", "maintenance", "removal"}:
            raise ValueError("Unknown Windows Desktop worker")
        from desktop.windows_processes import bootstrap
        bootstrap()  # Authenticated inherited handle; no application import yet.
        root_path(os.environ["DLMS_DESKTOP_DATA_ROOT"])
        sys.argv = [sys.argv[0], *argv[2:]]
        module = __import__("desktop." + argv[1], fromlist=["main"])
        return module.main()
    parser = argparse.ArgumentParser(description="DLMS Desktop native Windows candidate")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--data-root", help="existing explicitly marked synthetic candidate data directory")
    parser.add_argument('--capture-window-events',action='store_true',help='Capture 30 minutes of bounded lifecycle/content-layer metadata, without page content or URLs')
    args = parser.parse_args(argv)
    from desktop.windows_processes import default_data_root
    raw = args.data_root or str(default_data_root())
    # Set the explicit root before importing isolation. Every later worker must
    # use this exact marker; no discovery of an original/installed DLMS root.
    os.environ["DLMS_DESKTOP_DATA_ROOT"] = raw
    os.environ["DLMS_DESKTOP_ROOT_KIND"] = "windows-candidate"
    root = root_path(raw, create=not bool(args.data_root))
    os.environ["DLMS_DESKTOP_DATA_ROOT"] = str(root)
    os.environ.pop("PYTHONPATH", None)
    os.environ.pop("PYTHONHOME", None)
    from desktop.__main__ import main as desktop_main
    return desktop_main(["--profile", args.profile, *(['--capture-window-events'] if args.capture_window_events else [])])

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        import traceback
        traceback.print_exc()
        # Windowed executable has no console. Fail visibly before any backend
        # starts; no native command bridge is exposed to page content.
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(exc), "DLMS Desktop could not start", 0x10)
        raise SystemExit(2)
