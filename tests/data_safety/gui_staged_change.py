"""Actual Qt review/confirm rejects a changed staged bundle or Study Pack."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
import traceback

from desktop.isolation import AREA
from tests.gate1.qt_checks import QtChecks


def inventory(backend: Path) -> dict:
    with sqlite3.connect(backend / "results.db") as conn:
        tables = {table: [list(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
                  for table in ("quizzes", "questions", "choices", "matching_pairs", "attempts", "study_responses")}
    files = {path.relative_to(backend).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for folder in ("config", "data", "quizzes", "quiz_assets", "content_packs")
             for path in (backend / folder).rglob("*") if path.is_file()}
    return {"tables": tables, "files": files}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--kind", choices=("bundle", "pack"), required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    backend, root = q.paths["backend"], q.paths["root"]
    out = {"profile": args.profile, "kind": args.kind}
    try:
        before = inventory(backend)
        if args.kind == "bundle":
            original = AREA / "fixtures/closure-portable-media.zip"
            replacement = AREA / "fixtures/closure-unusual-choices.zip"
            q.go("/quiz-bundles")
            q.window.file_selection_for_test = original
            q.click_css('input[name="bundle_zip"]')
            q.js("document.querySelector('form[action=\"/quiz-bundles/import\"]').requestSubmit();true")
            q.wait("location.pathname.startsWith('/quiz-bundles/import/')", 25)
            token = q.js("location.pathname.split('/').pop()")
            assert q.js("!!document.querySelector('form[action$=\"/confirm\"]')")
            staged = backend / "uploads/quiz_bundles" / token / "bundle.zip"
            assert staged.is_file() and original.is_file() and replacement.is_file()
            staged.write_bytes(replacement.read_bytes())  # still a valid format-2 bundle, different reviewed bytes
            q.js("(()=>{const f=document.querySelector('form[action$=\"/confirm\"]');f.elements.confirm_import.checked=true;f.requestSubmit();return true})()")
            q.wait("location.pathname === '/quiz-bundles' || document.body.innerText.includes('not imported')", 25)
            text = q.js("document.body.innerText")
            out["visible_error"] = ("unavailable" in text.lower() or "not imported" in text.lower())
            out["stage_preserved"] = staged.is_file()
        else:
            original = AREA / "fixtures/closure-pack-datasets.zip"
            q.go("/content-packs")
            q.window.file_selection_for_test = original
            q.click_css('input[name="pack_zip"]')
            q.js("document.querySelector('form[action=\"/content-packs/import\"]').requestSubmit();true")
            q.wait("location.pathname.startsWith('/content-packs/import/')", 25)
            token = q.js("location.pathname.split('/').pop()")
            assert q.js("!!document.getElementById('packReviewInstallForm')")
            manifest = backend / "content_pack_staging" / token / "extracted/DLMS_Study_closure_datasets/manifest.json"
            assert manifest.is_file()
            value = json.loads(manifest.read_text())
            value["name"] = "Changed After Review Synthetic Pack"
            manifest.write_text(json.dumps(value, indent=2) + "\n")  # remains valid but review is stale
            q.js("(()=>{const f=document.getElementById('packReviewInstallForm');f.elements.confirm_install.checked=true;f.requestSubmit();return true})()")
            q.wait("location.pathname === '/content-packs' || document.body.innerText.includes('not installed')", 25)
            text = q.js("document.body.innerText")
            out["visible_error"] = ("not installed" in text.lower() or "unavailable" in text.lower())
            out["stage_preserved"] = manifest.is_file()
        out["message_excerpt"] = text[-850:]
        out["unchanged"] = inventory(backend) == before
        out["screenshot"] = str(q.screenshot(f"data-safety-{args.kind}-stale-review.png", width=1030, height=760))
        out["pass"] = out["visible_error"] and out["unchanged"] and out["stage_preserved"]
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (root / f"data-safety-{args.kind}-stale-review.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps({k: out.get(k) for k in ("profile", "kind", "visible_error", "unchanged", "pass", "error")}, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
