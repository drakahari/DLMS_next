"""Stable desktop-entry identity for the task-owned Qt window."""

DESKTOP_FILE_ID = "io.github.drakahari.DLMSDesktop"


def windows_application_id() -> str:
    import sys
    selected = sys.modules.get("package_windows_webview2")
    webview2 = (sys.platform == "win32" and selected is not None
                and getattr(selected, "ACTIVE", False) is True)
    return DESKTOP_FILE_ID + (".WebView2Candidate" if webview2 else ".WindowsCandidate")


def configure_application_identity(application) -> None:
    """Advertise the same ID as the proposed per-user desktop entry."""
    import sys
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        function = ctypes.WinDLL("shell32").SetCurrentProcessExplicitAppUserModelID
        function.argtypes, function.restype = [wintypes.LPCWSTR], ctypes.c_long
        if function(windows_application_id()) != 0:
            raise RuntimeError("Windows could not set the Desktop application identity")
    from pathlib import Path
    appimage = (getattr(sys, "frozen", False) and
                (Path(sys._MEIPASS) / "desktop_assets/appimage-info.json").is_file())
    application.setDesktopFileName(DESKTOP_FILE_ID + ".AppImageTest" if appimage else DESKTOP_FILE_ID)
