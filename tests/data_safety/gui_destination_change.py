"""Qt destination title changes after bundle review but before confirmation."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
import traceback

from desktop.isolation import AREA, PROJECT
from tests.closure.gui_portable_content import quiz_semantics
from tests.gate1.qt_checks import QtChecks


def rows(db):
    with sqlite3.connect(db) as conn:
        return {table: [list(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
                for table in ("quizzes", "questions", "choices", "matching_pairs")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--phase", choices=("run", "reopen"), required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    root, backend = q.paths["root"], q.paths["backend"]
    db = backend / "results.db"
    out = {"profile": args.profile, "phase": args.phase}
    try:
        if args.phase == "run":
            before = rows(db)
            archive = AREA / "fixtures/closure-portable-media.zip"
            q.go("/quiz-bundles")
            q.window.file_selection_for_test = archive
            q.click_css('input[name="bundle_zip"]')
            q.js("document.querySelector('form[action=\"/quiz-bundles/import\"]').requestSubmit();true")
            q.wait("location.pathname.startsWith('/quiz-bundles/import/')", 25)
            token = q.js("location.pathname.split('/').pop()")
            assert q.js("!!document.querySelector('form[action$=\"/confirm\"]')")
            review = q.js("document.body.innerText")
            assert "Synthetic Portable Media" in review and "Synthetic Portable Media (Imported)" not in review
            text = (PROJECT / "fixtures/gate1-neutral-quiz.txt").read_text()
            q.js("""(async()=>{let f=new FormData();f.append('quiz_title','Synthetic Portable Media');
                 f.append('file',new File([TEXT],'synthetic.txt',{type:'text/plain'}));
                 let token=document.cookie.split('; ').find(x=>x.startsWith('dlms_csrf_token='));
                 f.append('csrf_token',decodeURIComponent(token?.split('=')[1]||''));
                 let r=await fetch('/process',{method:'POST',body:f,credentials:'same-origin'});
                 window.__destinationChangeStatus=r.status;})()""".replace("TEXT", json.dumps(text)))
            q.wait("window.__destinationChangeStatus !== undefined", 25)
            assert q.js("window.__destinationChangeStatus") == 200
            mid = rows(db)
            assert len(mid["quizzes"]) == len(before["quizzes"]) + 1
            assert mid["quizzes"][:len(before["quizzes"])] == before["quizzes"]
            q.js("(()=>{let f=document.querySelector('form[action$=\"/confirm\"]');f.elements.confirm_import.checked=true;f.requestSubmit();return true})()")
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if len(rows(db)["quizzes"]) == len(mid["quizzes"]) + 1:
                    break
                q.delay(.1)
            else:
                raise TimeoutError("Confirmed portable import did not finish")
            q.wait("location.pathname === '/quiz-bundles'", 20)
            feedback = q.js("document.body.innerText")
            after = rows(db)
            titles = [row[1] for row in after["quizzes"]]
            imported = quiz_semantics(db, backend, "Synthetic Portable Media (Imported)")
            out.update(token=token, before=before, mid=mid, after=after,
                       titles=titles, imported=imported,
                       feedback_excerpt=feedback[:850],
                       rename_reported="title was renamed" in feedback.lower(),
                       media_hashes=[x["media"].get("image_sha256") for x in imported["questions"]],
                       stage_removed=not (backend / "uploads/quiz_bundles" / token).exists(),
                       screenshot=str(q.screenshot("data-safety-destination-change.png")))
            out["pass"] = (after["quizzes"][:len(before["quizzes"])] == before["quizzes"]
                           and "Synthetic Portable Media" in titles
                           and "Synthetic Portable Media (Imported)" in titles
                           and out["rename_reported"] and any(out["media_hashes"]) and out["stage_removed"])
        else:
            prior = json.loads((root / "data-safety-destination-change-run.json").read_text())
            q.go("/quiz-bundles")
            current = rows(db)
            out.update(rows_equal=current == prior["after"],
                       imported_equal=quiz_semantics(db, backend, "Synthetic Portable Media (Imported)") == prior["imported"],
                       visible=q.js("document.body.innerText.includes('Synthetic Portable Media (Imported)')"))
            out["pass"] = out["rows_equal"] and out["imported_equal"] and out["visible"]
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (root / f"data-safety-destination-change-{args.phase}.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps({k: out.get(k) for k in ("profile", "phase", "titles", "pass", "error")}, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
