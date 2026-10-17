"""Synthetic Law packet, case, notes and IRAC through the real Qt window."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import traceback
from pathlib import Path

from tests.gate1.qt_checks import QtChecks


PACKET = """Sources Used
Synthetic classroom facts only.

1. Case Brief
Neutral v. Example, 1 Fict. 2 (2025)
Issue: whether a blue token was delivered.
Rule: deliver the token as agreed.
Holding: delivery occurred.

2. Socratic Review
1. What token was promised?

2A. Socratic Answer Key
1. A blue token.

3. IRAC Drill
Issue: whether the blue token was delivered.
Rule: deliver as agreed.
Application: the receipt lists a blue token.
Conclusion: delivery occurred.

4. Rule Flashcards
Front: What was promised?
Back: A blue token.
"""


def find_case(root: Path):
    candidates = list((root / "law" / "cases").glob("*.json"))
    if len(candidates) != 1:
        return None
    p = candidates[0]
    return p, json.loads(p.read_text())


def wait_file(q, path: Path, predicate, label: str):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        data = json.loads(path.read_text())
        if predicate(data):
            return data
        q.delay(.1)
    raise TimeoutError(label)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--reopen", action="store_true")
    a = p.parse_args()
    q = QtChecks(a.profile)
    root = q.paths["backend"]
    out = {"profile": a.profile, "reopen": a.reopen}
    try:
        if not a.reopen:
            q.go("/law/create")
            q.js("(()=>{let f=document.querySelector('form');f.elements.case_name.value='Neutral v. Example';"
                 "f.elements.course.value='Torts';f.requestSubmit();return true})()")
            q.wait("!!document.querySelector('textarea') && document.querySelector('textarea').value.includes('Neutral v. Example')", 15)
            out["prompt_has_case"] = q.js("document.querySelector('textarea').value.includes('Neutral v. Example')")
            q.go("/law/import")
            q.js("(()=>{let f=document.querySelector('form[action=\"/law/import\"]');"
                 "f.elements.raw_packet.value=" + json.dumps(PACKET) + ";"
                 "f.requestSubmit(f.querySelector('button[value=save_and_preview]'));return true})()")
            q.wait("location.pathname.startsWith('/law/imports/')", 20)
            out["import_path"] = q.js("location.pathname")
            out["preview_has_irac"] = q.js("document.body.textContent.includes('whether the blue token was delivered')")
            out["preview_screenshot"] = str(q.screenshot("parity-law-preview.png"))
            raw_files = list((root / "law" / "imports").glob("*.txt"))
            out["raw_files"] = [(p.name, hashlib.sha256(p.read_bytes()).hexdigest()) for p in raw_files]
            q.js("document.querySelector('form[action$=\"/create_case\"]').requestSubmit();true")
            q.wait("location.pathname.startsWith('/law/cases/')", 20)
            case = find_case(root)
            if not case:
                raise RuntimeError("Expected one synthetic Law case")
            path, data = case
            out["case_path"] = str(path)
            out["case_id"] = data["id"]
            out["case_initial"] = data
            out["detail_screenshot"] = str(q.screenshot("parity-law-case.png"))
            q.js("(()=>{let f=document.querySelector('form[action$=\"/update_notes\"]');"
                 "f.elements.student_notes.value='Synthetic private study note';f.requestSubmit();return true})()")
            wait_file(q, path, lambda d: d.get("student_notes") == "Synthetic private study note", "Law notes commit")
            q.wait("document.querySelector('#lawStudentNotes')?.value.includes('Synthetic private study note')", 20)
            q.js("(()=>{let f=document.querySelector('form[action$=\"/update_irac_response\"]');"
                 "f.elements.irac_issue.value='Was delivery recorded?';"
                 "f.elements.irac_rule.value='Use the receipt.';"
                 "f.elements.irac_analysis.value='The receipt is synthetic.';"
                 "f.elements.irac_conclusion.value='Yes.';f.requestSubmit();return true})()")
            wait_file(q, path, lambda d: d.get("irac_student_response", {}).get("issue") == "Was delivery recorded?", "Law IRAC commit")
            q.wait("document.querySelector('#lawIracIssue')?.value.includes('Was delivery recorded?')", 20)
            out["case_final"] = json.loads(path.read_text())
            out["case_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            out["final_screenshot"] = str(q.screenshot("parity-law-irac.png"))
        else:
            prior = json.loads((q.paths["root"] / "parity-law.json").read_text())
            path, data = find_case(root)
            out["case_id"] = data["id"]
            out["case_final"] = data
            out["case_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            out["records_match_prior"] = out["case_sha256"] == prior["case_sha256"] and data == prior["case_final"]
            q.go(f"/law/cases/{out['case_id']}")
            out["detail_visible"] = q.js("document.body.innerText.includes('Neutral v. Example')")
            out["final_screenshot"] = str(q.screenshot("parity-law-reopen.png"))
        data = out["case_final"]
        out["pass"] = bool(data.get("title") == "Neutral v. Example"
                           and data.get("sections", {}).get("case_brief", "").startswith("Neutral v. Example")
                           and data.get("student_notes") == "Synthetic private study note"
                           and data.get("irac_student_response", {}).get("issue") == "Was delivery recorded?"
                           and (out.get("records_match_prior") and out.get("detail_visible") if a.reopen else
                                out.get("prompt_has_case") and out.get("preview_has_irac")
                                and len(out.get("raw_files", [])) == 1))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / ("parity-law-reopen.json" if a.reopen else "parity-law.json")).write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
