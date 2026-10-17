"""Native file selection boundaries and unsupported OCR input in Qt."""
from __future__ import annotations

import argparse
import json
from urllib.parse import urlsplit

from desktop.isolation import PROJECT
from tests.gate1.gui_ocr_pdf import upload
from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    result = {}
    try:
        from PySide6.QtWebEngineCore import QWebEnginePage
        from PySide6.QtWidgets import QFileDialog
        q.go("/pdf-import")
        page = q.window.view.page()
        original = QFileDialog.getOpenFileName
        QFileDialog.getOpenFileName = staticmethod(lambda *a, **kw: ("", ""))
        try:
            result["cancelled"] = page.chooseFiles(QWebEnginePage.FileSelectionMode.FileSelectOpen, [], ["image/png"]) == []
        finally:
            QFileDialog.getOpenFileName = original
        q.window.file_selection_for_test = PROJECT / "AGENTS.md"
        result["outside_disposable_rejected"] = page.chooseFiles(QWebEnginePage.FileSelectionMode.FileSelectOpen, [], ["image/png"]) == []
        result["boundary_message"] = q.window.statusBar().currentMessage()
        q.window.file_selection_for_test = PROJECT / ".gate1" / "fixtures" / "gate1-ocr.png"
        selected = page.chooseFiles(QWebEnginePage.FileSelectionMode.FileSelectOpen, [], ["image/png"])
        result["synthetic_selected"] = len(selected) == 1 and selected[0].endswith("gate1-ocr.png")
        invalid = upload(q, PROJECT / "fixtures" / "gate1-neutral-quiz.txt",
            "/pdf-import/screenshots", "screenshots", "text/plain",
            {"rights_ok": "on", "quiz_title": "Block C invalid image"})
        result["unsupported_upload_status"] = invalid["status"]
        q.go(urlsplit(invalid["url"]).path)
        q.wait("document.body.innerText.includes('unsupported screenshot type')", 20)
        result["unsupported_message"] = q.js("document.body.innerText.slice(-350)")
        result["pass"] = bool(result["cancelled"] and result["outside_disposable_rejected"]
            and "refused" in result["boundary_message"].lower() and result["synthetic_selected"]
            and result["unsupported_upload_status"] == 200
            and "unsupported screenshot type" in result["unsupported_message"])
    finally:
        (q.paths["root"] / "blockc-file-picker.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps(result, indent=2))
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
