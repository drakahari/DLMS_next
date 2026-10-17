"""Selectable PDF terminology Review & Repair in the actual Qt window."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import traceback

from desktop.isolation import AREA
from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--reopen", action="store_true")
    a = p.parse_args()
    q = QtChecks(a.profile)
    out = {"profile": a.profile, "reopen": a.reopen}
    try:
        fixture = AREA / "fixtures" / "completion-glossary.pdf"
        out["fixture_sha256"] = hashlib.sha256(fixture.read_bytes()).hexdigest()
        if not a.reopen:
            q.go("/pdf-import")
            encoded = base64.b64encode(fixture.read_bytes()).decode()
            q.js("""(()=>{const data=atob(""" + json.dumps(encoded) + """),bytes=new Uint8Array(data.length);
              for(let i=0;i<data.length;i++)bytes[i]=data.charCodeAt(i);
              const f=document.querySelector('form[action="/pdf-import/analyze"]'),dt=new DataTransfer();
              dt.items.add(new File([bytes],'completion-glossary.pdf',{type:'application/pdf'}));
              f.elements.pdf_file.files=dt.files;f.elements.quiz_title.value='Completion Terminology';
              f.elements.pdf_content_type.value='glossary';f.elements.rights_ok.checked=true;
              f.requestSubmit();return true})()""")
            q.delay(1.5)
            out["after_submit_url"] = q.js("location.href")
            out["after_submit_excerpt"] = q.js("document.body.innerText.slice(-700)")
            out["blocked_urls"] = list(q.window.blocked_urls)
            q.wait("location.pathname.startsWith('/pdf-import/review/') && !!document.querySelector('#pdfTermReviewForm')", 8)
            out["detected_count"] = q.js("document.querySelectorAll('.pdf-term-review-card').length")
            out["terms_before"] = json.loads(q.js("JSON.stringify([...document.querySelectorAll('.pdf-term-review-card')].map(c=>({term:c.querySelector('[data-term-role=term]').value,definition:c.querySelector('[data-term-role=definition]').value})))"))
            q.js("""(()=>{let cards=[...document.querySelectorAll('.pdf-term-review-card')];
              cards[0].querySelector('[data-term-role=definition]').value='Edited definition for this synthetic term.';
              cards[cards.length-1].querySelector('[data-term-role=exclude]').checked=true;
              document.getElementById('pdfTermReviewForm').requestSubmit();return true})()""")
            q.wait("location.pathname.startsWith('/pdf-import/terms/')", 25)
        bank_files = list((q.paths["backend"] / "pdf_terminology_banks").glob("*.json"))
        if len(bank_files) != 1:
            raise AssertionError(f"Expected one saved terminology bank: {bank_files}")
        bank = json.loads(bank_files[0].read_text())
        if a.reopen:
            q.go(f"/pdf-import/terms/{bank['id']}")
        out["bank_file"] = str(bank_files[0].relative_to(q.paths["backend"]))
        out["terms_after"] = bank.get("terms")
        out["bank_sha256"] = hashlib.sha256(bank_files[0].read_bytes()).hexdigest()
        out["ui_title"] = q.js("document.body.innerText.includes('Completion Terminology')")
        out["pass"] = (len(bank.get("terms", [])) == 5 and out["ui_title"]
                       and bank["terms"][0]["definition"] == 'Edited definition for this synthetic term.'
                       and bank["terms"][-1]["active"] is False
                       and all(term["active"] for term in bank["terms"][:-1]))
        out["screenshot"] = str(q.screenshot("completion-terminology-reopen.png" if a.reopen else "completion-terminology-saved.png", width=1000, height=800))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / ("completion-terminology-reopen.json" if a.reopen else "completion-terminology.json")).write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
