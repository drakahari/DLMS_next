"""Explicit source-only Windows WebView2 validation entry, separate from Qt."""
import os


def main():
    if os.name!='nt':raise RuntimeError('The WebView2 candidate is Windows only')
    import package_windows_webview2
    package_windows_webview2.ACTIVE=True
    from .__main__ import main as desktop_main
    return desktop_main()

if __name__=='__main__':raise SystemExit(main())
