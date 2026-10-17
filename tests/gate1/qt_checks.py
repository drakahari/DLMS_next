"""Small synchronous driver for checks inside the actual Qt WebEngine view."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

from desktop.isolation import isolated_environment, profile_paths


class QtChecks:
    def __init__(self, name: str, *, pause_action: str | None = None, fail_action_cleanup: bool = False,
                 fail_action_accept: bool = False, drop_cleaned_exam_reply: bool = False,
                 abort_request: str | None = None, fail_request_cleanup: bool = False,
                 pause_backup_iteration: bool = False, pause_publication: bool = False,
                 pause_settings_write: bool = False, automated: bool = False,
                 maintenance_abort: str | None = None, abort_import_at: str | None = None,
                 fail_import_receipt: bool = False, fail_import_cleanup: bool = False,
                 normal_identity: bool = False):
        self.paths = profile_paths(name)
        env = isolated_environment(self.paths)
        os.environ.clear()
        os.environ.update(env)
        os.environ["PYTHONNOUSERSITE"] = "1"
        if automated or pause_action or fail_action_cleanup or fail_action_accept or drop_cleaned_exam_reply or abort_request or fail_request_cleanup or pause_backup_iteration or pause_publication or pause_settings_write or abort_import_at or fail_import_receipt or fail_import_cleanup:
            os.environ["DLMS_DESKTOP_AUTOMATED"] = "1"
        if abort_import_at:
            os.environ["DLMS_DESKTOP_TEST_ABORT_IMPORT_AT"] = abort_import_at
        if fail_import_receipt:
            os.environ["DLMS_DESKTOP_TEST_FAIL_IMPORT_RECEIPT"] = "1"
        if fail_import_cleanup:
            os.environ["DLMS_DESKTOP_TEST_FAIL_IMPORT_CLEANUP"] = "1"
        if pause_backup_iteration:
            os.environ["DLMS_DESKTOP_TEST_PAUSE_BACKUP_ITERATION"] = "1"
        if pause_publication:
            os.environ["DLMS_DESKTOP_TEST_PAUSE_PUBLICATION"] = "1"
        if pause_settings_write:
            os.environ["DLMS_DESKTOP_TEST_PAUSE_SETTINGS_WRITE"] = "1"
        if maintenance_abort:
            if not automated:
                raise ValueError("Maintenance abort hooks require explicit disposable automation")
            os.environ["DLMS_DESKTOP_TEST_MAINTENANCE_ABORT"] = maintenance_abort
        if pause_action:
            os.environ["DLMS_DESKTOP_TEST_PAUSE_PHASE"] = pause_action
        if fail_action_cleanup:
            os.environ["DLMS_DESKTOP_TEST_FAIL_ACTION_CLEANUP"] = "1"
        if fail_action_accept:
            os.environ["DLMS_DESKTOP_TEST_FAIL_ACTION_ACCEPT"] = "1"
        if drop_cleaned_exam_reply:
            os.environ["DLMS_DESKTOP_TEST_DROP_CLEANED_EXAM_REPLY"] = "1"
        if abort_request:
            os.environ["DLMS_DESKTOP_TEST_ABORT_REQUEST"] = abort_request
        if fail_request_cleanup:
            os.environ["DLMS_DESKTOP_TEST_FAIL_REQUEST_CLEANUP"] = "1"
        from PySide6.QtWidgets import QApplication
        from desktop.shell import DesktopWindow

        self.app = QApplication(sys.argv[:1])
        if normal_identity:
            from desktop.identity import configure_application_identity
            configure_application_identity(self.app)
        self.window = DesktopWindow(self.paths, name)
        self.window.show()
        self.window.start()
        self.wait("document.readyState === 'complete' && location.pathname === '/'", 30)
        deadline=time.monotonic()+30
        while self.window.view.page().isLoading() and time.monotonic()<deadline:
            self.delay(.05)
        if self.window.view.page().isLoading():
            raise TimeoutError('Initial Qt document load did not finish')

    def js(self, expression: str, timeout: float = 10):
        answer = self.window._evaluate_browser(expression, round(timeout * 1000))
        if not answer["done"]:
            raise TimeoutError(f"JavaScript did not return: {expression[:100]}")
        return answer["value"]

    def wait(self, expression: str, timeout: float = 12):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.window.view is not None and self.js(expression, 3):
                return True
            self.delay(0.12)
        raise TimeoutError(f"Qt WebEngine condition failed: {expression[:140]}")

    def delay(self, seconds: float):
        from PySide6.QtCore import QEventLoop, QTimer

        loop = QEventLoop()
        QTimer.singleShot(round(seconds * 1000), loop.quit)
        loop.exec()

    def go(self, path: str):
        from PySide6.QtCore import QUrl

        view=self.window.view
        target=QUrl(f"http://127.0.0.1:{self.window.port}{path}")
        finished=[]
        def loaded(ok):
            if view.url().path()==target.path():finished.append(ok)
        view.loadFinished.connect(loaded)
        try:
            view.setUrl(target)
            deadline=time.monotonic()+30
            while not finished and time.monotonic()<deadline:self.delay(.05)
            if not finished or finished[-1] is not True:
                raise TimeoutError(f'Qt document load did not succeed: {path}')
            self.wait(f"location.pathname === {urlsplit(path).path!r} && document.readyState === 'complete'")
        finally:
            view.loadFinished.disconnect(loaded)

    def screenshot(self, name: str, *, width=1280, height=850, zoom=1.0) -> Path:
        output = self.paths["root"] / name
        self.window.resize(width, height)
        self.window.view.setZoomFactor(zoom)
        self.delay(0.85)
        if not self.window.view.grab().save(str(output)):
            raise RuntimeError(f"Cannot save Qt window screenshot: {output}")
        return output

    def click_css(self, selector: str):
        """Send a real Qt pointer click at an element in the embedded page."""
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        encoded = repr(selector)
        self.js(f"document.querySelector({encoded}).scrollIntoView({{block:'center'}}); true")
        self.delay(0.2)
        position = self.js(f"JSON.stringify((()=>{{let r=document.querySelector({encoded}).getBoundingClientRect();return {{x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)}}}})())")
        import json
        point = json.loads(position)
        location = QPoint(point["x"], point["y"])
        target = self.window.view.childAt(location) or self.window.view
        print(f"Qt click {selector}: {point} on {type(target).__name__}", flush=True)
        QTest.mouseClick(target, Qt.MouseButton.LeftButton,
                         pos=target.mapFrom(self.window.view, location))
        self.delay(0.1)

    def close(self):
        self.window.close()
        self.app.processEvents()
