"""Representative navigation, appearance, native adapter and download checks."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import traceback
import zipfile
import sqlite3
import tempfile

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="token01")
    args = parser.parse_args()
    q = QtChecks(args.profile)
    result = {"checks": {}, "screenshots": []}

    def file_facts(path: Path):
        payload = path.read_bytes()
        report = {"name": path.name, "path": str(path), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        if path.suffix.lower() in {".zip", ".apkg"}:
            with zipfile.ZipFile(path) as archive:
                report["zip_entries"] = len(archive.namelist())
                report["zip_integrity"] = archive.testzip() is None
        if path.suffix.lower() == ".pdf":
            report["pdf_magic"] = payload.startswith(b"%PDF-")
            from pypdf import PdfReader
            with path.open("rb") as stream:
                pages = PdfReader(stream).pages
                report["pdf_pages"] = len(pages)
                report["pdf_library_text"] = any("quizzes" in (page.extract_text() or "").lower() for page in pages)
        return report

    def new_downloads(before: set[str], suffix: str):
        return [file_facts(p) for p in q.paths["downloads"].rglob(f"*{suffix}")
                if str(p.relative_to(q.paths["downloads"])) not in before]

    def record(name, value):
        result["checks"][name] = value
        print(name, json.dumps(value), flush=True)

    try:
        record("dashboard", q.js("document.body.innerText.includes('Quiz Library')"))
        result["screenshots"].append(str(q.screenshot("dashboard-default.png")))
        q.go("/library")
        record("library_quiz", q.js("document.body.innerText.includes('Gate 1 Neutral Quiz')"))
        result["screenshots"].append(str(q.screenshot("library-wide.png")))
        result["screenshots"].append(str(q.screenshot("library-narrow.png", width=640, height=850)))
        result["screenshots"].append(str(q.screenshot("library-scaled.png", width=800, height=700, zoom=1.5)))
        q.go("/help/")
        record("help", q.js("document.querySelector('h1')?.innerText || document.title"))
        result["screenshots"].append(str(q.screenshot("help-wide.png")))
        q.go("/settings/appearance")
        options = json.loads(q.js("JSON.stringify([...document.querySelectorAll('#appearanceTheme option')].map(x=>({value:x.value,label:x.textContent.trim()})))"))
        record("theme_options", options)
        for label in ("Light", "Dark", "Ethereal"):
            match = next((item for item in options if label.lower() in item["label"].lower()), None)
            if not match:
                record(f"theme_{label.lower()}", "missing")
                continue
            q.js(f"document.getElementById('appearanceTheme').value={json.dumps(match['value'])}; document.querySelector('form[action=\"/settings/appearance/save\"] button[type=submit]').click(); true")
            q.wait("location.pathname === '/settings/appearance' && location.search.includes('saved=1')")
            q.go("/")
            theme = json.loads(q.js("JSON.stringify({body:document.body.getAttribute('data-theme'),html:document.documentElement.getAttribute('data-theme'),className:document.body.className})"))
            record(f"theme_{label.lower()}", theme)
            result["screenshots"].append(str(q.screenshot(f"dashboard-{label.lower()}.png")))
            q.go("/settings/appearance")

        q.go("/anki")
        record("anki_form", json.loads(q.js("JSON.stringify({present:!!document.querySelector('form[action=\"/anki/export/quiz\"]'),selects:[...document.querySelectorAll('form[action=\"/anki/export/quiz\"] select')].map(x=>({name:x.name,options:x.options.length}))})")))
        before = {str(p.relative_to(q.paths["downloads"])) for p in q.paths["downloads"].rglob("*") if p.is_file()}
        q.js("document.querySelector('form[action=\"/anki/export/quiz\"] select').selectedIndex=1; true")
        q.js("document.querySelector('form[action=\"/anki/export/quiz\"] button[type=submit]').click(); true")
        q.delay(2)
        record("anki_downloads", new_downloads(before, ".apkg"))
        if result["checks"]["anki_downloads"]:
            package = Path(result["checks"]["anki_downloads"][0]["path"])
            with zipfile.ZipFile(package) as archive, tempfile.TemporaryDirectory(dir=q.paths["tmp"]) as temporary:
                database = Path(temporary) / "collection.anki2"
                database.write_bytes(archive.read("collection.anki2"))
                with sqlite3.connect(database) as conn:
                    note = conn.execute("SELECT flds FROM notes LIMIT 1").fetchone()
                    record("anki_content", {"notes": conn.execute("SELECT count(*) FROM notes").fetchone()[0],
                        "cards": conn.execute("SELECT count(*) FROM cards").fetchone()[0],
                        "expected_answer": bool(note and "B. Four" in note[0])})
        before_repeat = {str(p.relative_to(q.paths["downloads"])) for p in q.paths["downloads"].rglob("*") if p.is_file()}
        q.js("document.querySelector('form[action=\"/anki/export/quiz\"] button[type=submit]').click(); true")
        q.delay(2)
        record("anki_repeat", new_downloads(before_repeat, ".apkg"))
        record("anki_page_after", q.js("JSON.stringify({url:location.href,text:document.body.innerText.slice(0,250)})"))

        q.go("/quiz-bundles")
        record("bundle_candidates", q.js("document.querySelectorAll('#portableBundleExportForm input[name=quiz_ids]').length"))
        before = {str(p.relative_to(q.paths["downloads"])) for p in q.paths["downloads"].rglob("*") if p.is_file()}
        q.js("document.querySelector('#portableBundleExportForm input[name=quiz_ids]').click(); document.getElementById('bundleDownload').click(); true")
        q.delay(1)
        if q.js("!!document.getElementById('bundleDownloadTop')"):
            q.js("document.getElementById('bundleDownloadTop').click(); true")
        q.delay(2)
        record("bundle_downloads", [p for p in new_downloads(before, ".zip") if "Bundle" in p["name"]])
        if result["checks"]["bundle_downloads"]:
            with zipfile.ZipFile(result["checks"]["bundle_downloads"][0]["path"]) as archive:
                bundle = json.loads(archive.read("dlms-quiz-bundle.json"))
                record("bundle_content", {"format": bundle.get("format"),
                    "questions": sum(len(quiz.get("questions", [])) for quiz in bundle.get("quizzes", [])),
                    "correct_four": any(choice.get("label") == "B" and choice.get("text") == "Four" and choice.get("is_correct")
                        for quiz in bundle.get("quizzes", []) for question in quiz.get("questions", [])
                        for choice in question.get("choices", []))})

        q.go("/settings/backup")
        before = {str(p.relative_to(q.paths["downloads"])) for p in q.paths["downloads"].rglob("*") if p.is_file()}
        q.js("document.querySelector('form[action=\"/settings/backup/create\"] button').click(); true")
        q.delay(3)
        record("backup_downloads", [p for p in new_downloads(before, ".zip") if "backup" in p["name"]])

        q.go("/library")
        q.window._print_pdf()
        q.delay(3)
        record("print_pdf", [file_facts(p) for p in q.window.pdf_files if p.exists()])
        record("native_transfer_states", {"downloads": q.window.download_results,
                                           "pdf": q.window.pdf_results})

        # Exercise a real main-frame click while intercepting OS-browser launch.
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import QMessageBox
        original = QDesktopServices.openUrl
        original_question = QMessageBox.question
        opened = []
        QDesktopServices.openUrl = lambda url: opened.append(url.toString()) or True
        QMessageBox.question = lambda *args: QMessageBox.StandardButton.Yes
        try:
            q.js("(()=>{let a=document.createElement('a');a.href='https://example.org/gate1';a.textContent='External test';document.body.append(a);a.click();return true})()")
            q.delay(0.5)
        finally:
            QDesktopServices.openUrl = original
            QMessageBox.question = original_question
        record("external_link", opened)
        QMessageBox.question = lambda *args: QMessageBox.StandardButton.No
        try:
            q.js("location.href='https://example.org/unexpected'; true")
            q.delay(0.5)
        finally:
            QMessageBox.question = original_question
        record("unexpected_navigation", {"still_local": q.js(f"location.origin==='http://127.0.0.1:{q.window.port}'"), "blocked": q.window.blocked_urls[-3:]})

        checks = result["checks"]
        required = [checks["dashboard"], checks["library_quiz"], checks["help"] == "Help Center",
                    checks["anki_form"]["present"], checks["bundle_candidates"] >= 1,
                    len(checks["anki_downloads"]) == 1, len(checks["anki_repeat"]) == 1,
                    checks["anki_downloads"][0]["path"] != checks["anki_repeat"][0]["path"],
                    checks["anki_content"]["expected_answer"], checks["anki_content"]["cards"] >= 1,
                    len(checks["bundle_downloads"]) == 1, checks["bundle_content"]["correct_four"],
                    len(checks["backup_downloads"]) == 1, len(checks["print_pdf"]) == 1,
                    checks["external_link"] == ["https://example.org/gate1"],
                    checks["unexpected_navigation"]["still_local"],
                    "https://example.org/unexpected" in checks["unexpected_navigation"]["blocked"],
                    len(checks["native_transfer_states"]["downloads"]) >= 4,
                    all(item["state"] == "completed" for item in checks["native_transfer_states"]["downloads"]),
                    len(checks["native_transfer_states"]["pdf"]) == 1,
                    checks["native_transfer_states"]["pdf"][0]["state"] == "completed"]
        for key in ("anki_downloads", "bundle_downloads", "backup_downloads"):
            required.extend(p["zip_integrity"] and p["zip_entries"] > 0 for p in checks[key])
        required.extend(p["pdf_magic"] and p["bytes"] > 0 and p["pdf_library_text"] for p in checks["print_pdf"])
        required.extend(checks.get(f"theme_{name}") != "missing" for name in ("light", "dark", "ethereal"))
        result["status"] = "pass" if all(required) else "fail"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "compatibility-evidence.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
