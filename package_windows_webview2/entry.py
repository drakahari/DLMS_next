"""Normal WebView2 package entry, retaining authenticated Desktop worker bootstrap."""
import os
import sys


def default_data_root():
    from desktop.windows_processes import default_data_root as qt_candidate_root
    return qt_candidate_root().parent / "WebView2Candidate"


def main():
    import package_windows_webview2
    package_windows_webview2.ACTIVE = True
    from package_windows.entry import main as existing_entry, root_path
    # Worker argv/environment are authenticated by the existing entry before
    # importing application modules. Never rewrite or interpret those arguments.
    if sys.argv[1:2] != ["--desktop-worker"] and "--data-root" not in sys.argv[1:] and not any(
            item.startswith("--data-root=") for item in sys.argv[1:]):
        from desktop.windows_files import lexical, assert_path
        root = lexical(default_data_root())
        assert_path(root)
        root = root.resolve()
        # First-root marker publication imports isolation via profile_state.
        # Bind its explicit area before that import, as the normal entry does.
        os.environ['DLMS_DESKTOP_DATA_ROOT'] = str(root)
        os.environ['DLMS_DESKTOP_ROOT_KIND'] = 'windows-candidate'
        root = root_path(root, create=True)
        from desktop.windows_processes import capture_webview2_default_root
        capture_webview2_default_root(str(root))
        sys.argv.extend(["--data-root", str(root)])
    return existing_entry()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        import traceback
        traceback.print_exc()
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(exc), "DLMS Desktop WebView2 could not start", 0x10)
        raise SystemExit(2)
