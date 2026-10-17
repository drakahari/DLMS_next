"""Delegate only confirmed web URLs to the existing Windows desktop shell.

The short native helper receives no DLMS/Firefox profile or user environment.
Explorer owns the ordinary browser association and its normal environment; it
also keeps a newly started browser outside DLMS's kill-on-close Job. Never swap
os.environ or DLL search state in the multithreaded application.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess


class HandoffUnconfirmed(OSError):
    """The shell may already have acted. Never retry automatically."""


def helper_context():
    # Use the OS API rather than mutable SystemRoot/PATH/profile variables.
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    get = kernel.GetWindowsDirectoryW
    get.argtypes, get.restype = [wintypes.LPWSTR, wintypes.UINT], wintypes.UINT
    output = ctypes.create_unicode_buffer(32768)
    count = get(output, len(output))
    if not 0 < count < len(output):
        raise OSError('The Windows system directory is unavailable')
    windows = Path(output.value)
    system = windows / 'System32'
    return system, {'SystemRoot': str(windows), 'WINDIR': str(windows),
                    'PATH': str(system)}


def dispatch(url):
    from .shell import allowed_external
    if not url.isValid() or not allowed_external(url):
        raise ValueError('Only a permitted HTTP(S) address can be opened externally')
    encoded = bytes(url.toEncoded())
    if not encoded or len(encoded) > 8192 or any(ch < 32 or ch == 127 for ch in encoded):
        raise ValueError('External address is invalid or too long')
    from .webview2_browser import host_executable
    helper = host_executable()
    cwd, environment = helper_context()
    def invoke():
        return subprocess.run([str(helper), '--external-browser'],
            input=encoded + b'\n', stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=cwd, env=environment, close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
    try:
        from PySide6.QtCore import QCoreApplication, QEventLoop, QThread, QTimer
        application = QCoreApplication.instance()
        if application is not None and QThread.currentThread() == application.thread():
            # The caller holds browser_dialog ownership while this bounded
            # nested loop keeps painting/input/timers responsive. Only the
            # subprocess wait runs on a worker; it never touches Qt widgets.
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix='browser-handoff') as executor:
                future = executor.submit(invoke)
                loop, timer = QEventLoop(), QTimer()
                timer.timeout.connect(lambda: loop.quit() if future.done() else None)
                timer.start(20)
                try:
                    while not future.done():
                        loop.exec()
                    result = future.result()
                finally:
                    timer.stop()
        else:
            result = invoke()
    except subprocess.TimeoutExpired as error:
        raise HandoffUnconfirmed('Browser handoff timed out; check your browser before retrying') from error
    if result.returncode != 0 or result.stdout != b'accepted\r\n':
        # Native messages never carry the URL, but do not expose even those
        # details in the page/status. A late COM failure may follow activation.
        raise HandoffUnconfirmed('Windows did not confirm browser activation; check your browser before retrying')
    return True
