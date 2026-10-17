"""Use neutral synthetic PNG/PDF sources from inside Qt WebEngine."""
from __future__ import annotations

import base64
import argparse
import json
import os
from pathlib import Path
import time
import traceback
from urllib.parse import urlsplit

from desktop.isolation import FROZEN, PROJECT
from tests.gate1.qt_checks import QtChecks
from tests.gate1.lifecycle_integration import live_pid, owned_descendants


def upload(q, path: Path, target: str, field: str, media: str, extras: dict[str, str]):
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    script = """(async()=>{const bin=atob(DATA),bytes=new Uint8Array(bin.length);
      for(let i=0;i<bin.length;i++)bytes[i]=bin.charCodeAt(i);
      const form=new FormData();form.append(FIELD,new File([bytes],NAME,{type:MEDIA}));
      for(const [k,v] of Object.entries(EXTRAS))form.append(k,v);
      const response=await fetch(TARGET,{method:'POST',body:form,credentials:'same-origin'});
      window.__gate1Upload=JSON.stringify({status:response.status,url:response.url,html:(await response.text()).slice(0,800)});})()"""
    for key, value in {"DATA": encoded, "FIELD": field, "NAME": path.name,
                       "MEDIA": media, "EXTRAS": extras, "TARGET": target}.items():
        script = script.replace(key, json.dumps(value))
    q.js("window.__gate1Upload=null; true")
    q.js(script)
    q.wait("!!window.__gate1Upload", 35)
    return json.loads(q.js("window.__gate1Upload"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="ocr03")
    args = parser.parse_args()
    q = QtChecks(args.profile)
    result = {}
    try:
        fixtures = q.paths["root"] / "fixtures" if FROZEN else PROJECT / ".gate1" / "fixtures"
        q.go("/pdf-import")
        q.window.file_selection_for_test = fixtures / "gate1-ocr.png"
        q.click_css("#pdfOcrUploadForm input[type=file]")
        result["chooser_override_consumed"] = q.window.file_selection_for_test is None
        result["picker_input_state"] = q.js("JSON.stringify({disabled:document.querySelector('#pdfOcrUploadForm input[type=file]').disabled,files:document.querySelector('#pdfOcrUploadForm input[type=file]').files.length})")
        q.wait("document.querySelector('#pdfOcrUploadForm input[type=file]').files.length === 1")
        result["qt_file_selection"] = q.js("document.querySelector('#pdfOcrUploadForm input[type=file]').files[0].name")
        result["ocr_available"] = q.js("!document.querySelector('#pdfOcrUploadForm input[type=file]').disabled")
        if result["ocr_available"]:
            staged = upload(q, fixtures / "gate1-ocr.png", "/pdf-import/screenshots", "screenshots", "image/png", {"rights_ok": "on", "quiz_title": "Gate 1 OCR Synthetic"})
            result["ocr_stage"] = {"status": staged["status"], "url": staged["url"]}
            if "/pdf-import/screenshots/process/" in staged["url"]:
                from PySide6.QtCore import QUrl
                q.window.view.setUrl(QUrl(staged["url"]))
                q.wait("location.pathname.startsWith('/pdf-import/review/') || document.body.innerText.includes('OCR complete')", 35)
                result["ocr_page"] = json.loads(q.js("JSON.stringify({path:location.pathname,recognized:[...document.querySelectorAll('input,textarea')].some(x=>x.value.includes('Which shape has three sides?')),images:[...document.images].map(x=>({src:x.getAttribute('src'),loaded:x.complete&&x.naturalWidth>0})).filter(x=>x.src?.startsWith('/')).slice(0,8)})"))
                draft_id = result["ocr_page"]["path"].rsplit("/", 1)[-1]
                draft = json.loads((q.paths["backend"] / "pdf_import_drafts" / f"{draft_id}.json").read_text())
                result["ocr_draft"] = {"questions": len(draft.get("questions", [])), "fixture_text_detected": "Which shape has three sides?" in json.dumps(draft.get("questions", []))}
                result["ocr_screenshot"] = str(q.screenshot("ocr-review.png"))
            else:
                result["ocr_error"] = staged["html"]
        q.go("/pdf-import")
        pdf = upload(q, fixtures / "gate1-scanned.pdf", "/pdf-import/analyze", "pdf_file", "application/pdf", {"rights_ok": "on", "quiz_title": "Gate 1 Scanned PDF", "pdf_content_type": "question_bank"})
        result["pdf_stage"] = {"status": pdf["status"], "url": pdf["url"], "title": pdf["html"][:150]}
        pdf_path = urlsplit(pdf["url"]).path
        if pdf_path.startswith("/pdf-import/") and pdf_path != "/pdf-import":
            q.go(pdf_path)
            result["pdf_page"] = json.loads(q.js("JSON.stringify({path:location.pathname,offer:document.body.innerText.includes('Some PDF Pages Have Limited Text'),available:document.body.innerText.includes('OCR available'),eligible:document.querySelectorAll('input[name=ocr_pages]').length})"))
            result["pdf_screenshot"] = str(q.screenshot("pdf-import.png"))
            if result["pdf_page"]["available"] and result["pdf_page"]["eligible"]:
                q.js("document.querySelector('input[name=ocr_pages]').click(); document.querySelector('.pdf-ocr-page-selection button[type=submit]').click(); true")
                q.wait("location.pathname.startsWith('/pdf-import/review/') || document.body.innerText.includes('Processing paused')", 45)
                q.wait("[...document.images].some(x=>x.getAttribute('src')?.startsWith('/pdf-import/ocr/')&&x.complete&&x.naturalWidth>0)", 15)
                result["pdf_ocr_page"] = json.loads(q.js("JSON.stringify({path:location.pathname,recognized:[...document.querySelectorAll('input,textarea')].some(x=>x.value.includes('Which shape has three sides?')),images:[...document.images].map(x=>({src:x.getAttribute('src'),loaded:x.complete&&x.naturalWidth>0})).filter(x=>x.src?.startsWith('/')).slice(0,8)})"))
                pdf_draft_id = result["pdf_ocr_page"]["path"].rsplit("/", 1)[-1]
                pdf_draft = json.loads((q.paths["backend"] / "pdf_import_drafts" / f"{pdf_draft_id}.json").read_text())
                result["pdf_ocr_draft"] = {"questions": len(pdf_draft.get("questions", [])), "fixture_text_detected": "Which shape has three sides?" in json.dumps(pdf_draft.get("questions", []))}
                result["pdf_ocr_screenshot"] = str(q.screenshot("pdf-ocr-review.png"))
        result["status"] = "pass" if (result["chooser_override_consumed"]
                                       and result["qt_file_selection"] == "gate1-ocr.png"
                                       and result["ocr_stage"]["status"] == 200
                                       and result["ocr_draft"]["questions"] >= 1
                                       and result["ocr_draft"]["fixture_text_detected"]
                                       and result["ocr_page"]["recognized"]
                                       and any(image["loaded"] for image in result["ocr_page"]["images"])
                                       and result["pdf_page"]["offer"]
                                       and result.get("pdf_ocr_page", {}).get("recognized")
                                       and result.get("pdf_ocr_draft", {}).get("fixture_text_detected")
                                       and any(image["loaded"] for image in result.get("pdf_ocr_page", {}).get("images", []))) else "fail"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        descendants = owned_descendants(os.getpid())
        q.close()
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and any(live_pid(pid) for pid in descendants):
            q.app.processEvents()
            time.sleep(0.05)
        result["task_descendants_at_window_close"] = [pid for pid in descendants if live_pid(pid)]
        (q.paths["root"] / "ocr-pdf-evidence.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
