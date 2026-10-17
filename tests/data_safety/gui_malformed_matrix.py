"""Fixed bounded malformed-import matrix in a populated real Qt profile."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
import traceback

from desktop.isolation import AREA
from tests.gate1.qt_checks import QtChecks


CASES = (
    ("ordinary-truncated.zip", "bundle"),
    ("ordinary-invalid-manifest.zip", "bundle"),
    ("ordinary-unsafe-path.zip", "bundle"),
    ("ordinary-missing-media.zip", "bundle"),
    ("ordinary-inconsistent-media.zip", "bundle"),
    ("pack-missing-manifest.zip", "pack"),
    ("pack-unsafe-link.zip", "pack"),
)


def snapshot(backend: Path) -> dict:
    with sqlite3.connect(backend / "results.db") as conn:
        tables = {name: [list(row) for row in conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid')]
                  for name in ("quizzes", "questions", "choices", "matching_pairs", "attempts", "study_responses")}
    files = {path.relative_to(backend).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for folder in ("config", "quizzes", "quiz_assets", "data", "content_packs")
             for path in (backend / folder).rglob("*") if path.is_file()}
    stage = {path.relative_to(backend).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for folder in ("uploads/quiz_bundles", "content_pack_staging")
             for path in (backend / folder).rglob("*") if path.is_file()}
    return {"tables": tables, "files": files, "staging": stage}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--phase", choices=("run", "reopen"), required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    root, backend = q.paths["root"], q.paths["backend"]
    out = {"profile": args.profile, "phase": args.phase, "cases": []}
    try:
        if args.phase == "run":
            baseline = snapshot(backend)
            for name, kind in CASES:
                archive = AREA / "fixtures/data-safety-invalid" / name
                assert archive.is_file() and archive.stat().st_size < 4 * 1024 * 1024
                if kind == "bundle":
                    q.go("/quiz-bundles")
                    q.window.file_selection_for_test = archive
                    q.click_css('input[name="bundle_zip"]')
                    q.js("document.querySelector('form[action=\"/quiz-bundles/import\"]').requestSubmit();true")
                    q.wait("document.body.innerText.includes('not a valid, safe DLMS portable quiz bundle')", 20)
                    message = "not a valid, safe DLMS portable quiz bundle"
                else:
                    q.go("/content-packs")
                    q.window.file_selection_for_test = archive
                    q.click_css('input[name="pack_zip"]')
                    q.js("document.querySelector('form[action=\"/content-packs/import\"]').requestSubmit();true")
                    q.wait("location.pathname.startsWith('/content-packs/import/') || document.body.innerText.includes('could not be validated')", 20)
                    message = "INSTALL BLOCKED" if q.js("location.pathname.startsWith('/content-packs/import/')") else "Study Pack ZIP could not be validated"
                after = snapshot(backend)
                result = {"archive": name, "kind": kind, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                          "visible_error": message in q.js("document.body.innerText"),
                          "canonical_unchanged": after["tables"] == baseline["tables"] and after["files"] == baseline["files"],
                          "stage_state": "retained invalid review" if kind == "pack" and message == "INSTALL BLOCKED" else "cleaned on refusal"}
                result["staging_expected"] = (after["staging"] == baseline["staging"] if kind == "bundle" else
                                              len(after["staging"]) >= len(baseline["staging"]))
                assert result["visible_error"] and result["canonical_unchanged"] and result["staging_expected"], result
                out["cases"].append(result)
            out["baseline"] = baseline
            out["after"] = snapshot(backend)
            out["screenshot"] = str(q.screenshot("data-safety-malformed-refusal.png", width=1030, height=760))
        else:
            prior = json.loads((root / "data-safety-malformed-run.json").read_text())
            assert len(prior["cases"]) == len(CASES)
            out["unchanged_after_restart"] = snapshot(backend) == prior["after"]
            assert out["unchanged_after_restart"]
        out["pass"] = True
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (root / f"data-safety-malformed-{args.phase}.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps({k: out.get(k) for k in ("profile", "phase", "pass", "error")}, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
