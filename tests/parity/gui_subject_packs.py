"""Install synthetic IT/Medical packs and create actual subject matching quizzes in Qt."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
import traceback
import zipfile

from tests.gate1.qt_checks import QtChecks


def pack_zip(path, domain):
    pack_id = f"parity_{domain}"
    folder = f"DLMS_Study_{pack_id}"
    manifest = {"schema_version": 1, "id": pack_id, "name": f"Parity {domain.title()} Pack",
                "version": "1.0.0", "content_domain": "medical" if domain == "medical" else "it_cybersecurity",
                "datasets": [{"id": "terms", "title": f"{domain.title()} Terms", "type": "matching", "path": "data/terms.json"}],
                "image_datasets": [], "quiz_datasets": []}
    terms = {"schema_version": 1, "id": "terms", "title": f"{domain.title()} Terms",
             "source": {"organization": "Synthetic Test", "license": "CC0"},
             "terms": [{"term": f"{domain.title()} Alpha", "definition": "First neutral item."},
                       {"term": f"{domain.title()} Beta", "definition": "Second neutral item."}]}
    validation = {"schema_version": 1, "pack_id": pack_id, "overall_status": "PASS", "checks": []}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, obj in (("manifest.json", manifest), ("data/terms.json", terms),
                          ("PACK_VALIDATION.json", validation)):
            z.writestr(f"{folder}/{name}", json.dumps(obj))
    return pack_id, folder, manifest, terms


def wait_db(q, db, title_fragment):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        with sqlite3.connect(db) as conn:
            found = conn.execute("SELECT id,title FROM quizzes WHERE title LIKE ? ORDER BY id DESC LIMIT 1",
                                 (f"%{title_fragment}%",)).fetchone()
        if found:
            return found
        q.delay(.1)
    raise TimeoutError(f"Subject quiz {title_fragment} was not committed")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--reopen", action="store_true")
    a = p.parse_args()
    q = QtChecks(a.profile)
    out = {"profile": a.profile, "reopen": a.reopen}
    root = q.paths["backend"]
    db = root / "results.db"
    try:
        if not a.reopen:
            invalid = q.paths["tmp"] / "parity-invalid-pack.zip"
            invalid.write_bytes(b"not a zip")
            with sqlite3.connect(db) as conn:
                initial_count = conn.execute("SELECT COUNT(*) FROM quizzes").fetchone()[0]
            q.go("/content-packs")
            q.window.file_selection_for_test = invalid
            q.click_css('input[name="pack_zip"]')
            q.js("document.querySelector('form[action=\"/content-packs/import\"]').requestSubmit();true")
            q.wait("document.body.innerText.includes('could not be validated')", 20)
            out["invalid_message"] = q.js("document.body.innerText.includes('could not be validated')")
            out["invalid_screenshot"] = str(q.screenshot("parity-pack-invalid.png"))
            with sqlite3.connect(db) as conn:
                out["invalid_preserved_quiz_count"] = conn.execute("SELECT COUNT(*) FROM quizzes").fetchone()[0] == initial_count
            out["domains"] = {}
            for domain in ("it", "medical"):
                archive = q.paths["tmp"] / f"parity-{domain}-pack.zip"
                pack_id, folder, manifest, terms = pack_zip(archive, domain)
                item = {"archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "pack_id": pack_id, "folder": folder}
                q.go("/content-packs")
                q.window.file_selection_for_test = archive
                q.click_css('input[name="pack_zip"]')
                q.js("document.querySelector('form[action=\"/content-packs/import\"]').requestSubmit();true")
                q.wait("location.pathname.startsWith('/content-packs/import/')", 20)
                item["review_valid"] = q.js("!!document.getElementById('packReviewInstallForm')")
                item["review_screenshot"] = str(q.screenshot(f"parity-{domain}-pack-review.png"))
                q.js("(()=>{let f=document.getElementById('packReviewInstallForm');f.elements.confirm_install.checked=true;f.requestSubmit();return true})()")
                q.wait("location.pathname === '/content-packs'", 20)
                installed = root / "content_packs" / folder
                item["manifest_equal"] = json.loads((installed / "manifest.json").read_text()) == manifest
                item["terms_equal"] = json.loads((installed / "data/terms.json").read_text()) == terms
                item["installed_hashes"] = {str(path.relative_to(installed)): hashlib.sha256(path.read_bytes()).hexdigest()
                                            for path in installed.rglob("*") if path.is_file()}
                q.go(f"/{domain}/matching")
                item["matching_visible"] = q.js(f"document.body.innerText.includes('{domain.title()} Terms')")
                item["matching_screenshot"] = str(q.screenshot(f"parity-{domain}-matching.png"))
                form_action = "/medical/generate" if domain == "medical" else "/study-packs/generate"
                q.js("(()=>{let f=document.querySelector('form[action=\"" + form_action + "\"]');f.requestSubmit();return true})()")
                q.wait("location.pathname.startsWith('/quizzes/')", 25)
                quiz = wait_db(q, db, domain.title())
                item["quiz"] = quiz
                with sqlite3.connect(db) as conn:
                    questions = conn.execute("SELECT id,question_text,question_type FROM questions WHERE quiz_id=? ORDER BY question_number", (quiz[0],)).fetchall()
                    item["questions"] = questions
                    item["pairs"] = [conn.execute("SELECT pair_order,left_text,right_text FROM matching_pairs WHERE question_id=? ORDER BY pair_order", (row[0],)).fetchall() for row in questions]
                item["quiz_screenshot"] = str(q.screenshot(f"parity-{domain}-quiz.png"))
                out["domains"][domain] = item
        else:
            prior = json.loads((q.paths["root"] / "parity-subject-packs.json").read_text())
            out["domains"] = {}
            for domain, earlier in prior["domains"].items():
                installed = root / "content_packs" / earlier["folder"]
                hashes = {str(path.relative_to(installed)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in installed.rglob("*") if path.is_file()}
                q.go(f"/{domain}/matching")
                with sqlite3.connect(db) as conn:
                    questions = conn.execute("SELECT id,question_text,question_type FROM questions WHERE quiz_id=? ORDER BY question_number", (earlier["quiz"][0],)).fetchall()
                    pairs = [conn.execute("SELECT pair_order,left_text,right_text FROM matching_pairs WHERE question_id=? ORDER BY pair_order", (row[0],)).fetchall() for row in questions]
                out["domains"][domain] = {"pack_hashes_match": hashes == earlier["installed_hashes"],
                                          "matching_visible": q.js(f"document.body.innerText.includes('{domain.title()} Terms')"),
                                          "quiz_rows_match": json.loads(json.dumps((questions,pairs))) == [earlier["questions"],earlier["pairs"]]}
        out["pass"] = (all(item["pack_hashes_match"] and item["matching_visible"] and item["quiz_rows_match"]
                           for item in out["domains"].values())
                       if a.reopen else
                       out["invalid_message"] and out["invalid_preserved_quiz_count"] and
                       all(item["review_valid"] and item["manifest_equal"] and item["terms_equal"]
                           and item["matching_visible"] and len(item["questions"]) >= 1
                           and all(pairs == [(1, f"{domain.title()} Alpha", "First neutral item."),
                                             (2, f"{domain.title()} Beta", "Second neutral item.")]
                                   for pairs in item["pairs"])
                           for domain, item in out["domains"].items()))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / ("parity-subject-packs-reopen.json" if a.reopen else "parity-subject-packs.json")).write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
