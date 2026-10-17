"""Check keyboard focus and Study copy in Qt, restoring the owner's clipboard."""
from __future__ import annotations

import json
import traceback
import argparse

from tests.gate1.qt_checks import QtChecks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    result = {}
    from PySide6.QtCore import QMimeData, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtGui import QGuiApplication
    clipboard = QGuiApplication.clipboard()
    previous = QMimeData()
    for fmt in clipboard.mimeData().formats():
        if fmt not in {"SAVE_TARGETS", "TARGETS", "MULTIPLE", "TIMESTAMP"}:
            previous.setData(fmt, clipboard.mimeData().data(fmt))
    try:
        q.go("/library")
        target = q.window.view.childAt(q.window.view.rect().center()) or q.window.view
        target.setFocus()
        QTest.keyClick(target, Qt.Key.Key_Tab)
        q.delay(0.15)
        result["tab_focus"] = q.js("JSON.stringify({tag:document.activeElement?.tagName,label:document.activeElement?.getAttribute('aria-label'),text:document.activeElement?.innerText?.slice(0,80)})")

        url = q.js("document.querySelector('a[href^=\"/quizzes/\"]')?.getAttribute('href')")
        if not url:
            raise RuntimeError("No synthetic quiz link in Library")
        q.go(url)
        if q.js("!!document.querySelector('.quiz-recovery-resume')"):
            q.js("document.querySelector('.quiz-recovery-resume').click(); true")
        else:
            q.js("document.querySelector('.study-mode-btn').click(); true")
        q.wait("document.getElementById('studyCopyBtn') && getComputedStyle(document.getElementById('studyCopyBtn')).display !== 'none'")
        q.click_css("#studyCopyBtn")
        q.delay(0.5)
        result["copy_status"] = q.js("document.getElementById('questionCopyStatus')?.innerText")
        result["clipboard_matches_question"] = "Which shape has three sides?" in clipboard.text() or "What is two plus two?" in clipboard.text()
        result["screenshot"] = str(q.screenshot("study-copy.png"))
        result["status"] = "pass" if result["clipboard_matches_question"] and result["tab_focus"] else "fail"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        clipboard.setMimeData(previous)
        (q.paths["root"] / "clipboard-focus-evidence.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
