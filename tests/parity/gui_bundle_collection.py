"""Qt collection export and every inner-bundle import with exact synthetic content."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
import traceback
import zipfile

from desktop.isolation import PROJECT, profile_paths
from tests.gate1.qt_checks import QtChecks


def semantics(db):
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT id,title FROM quizzes ORDER BY title").fetchall()
        result = {}
        for qid, title in rows:
            questions = conn.execute("SELECT id,question_text,question_type FROM questions WHERE quiz_id=? ORDER BY question_number", (qid,)).fetchall()
            result[title] = [{"text": text, "type": typ,
                              "choices": conn.execute("SELECT choice_order,label,text,is_correct FROM choices WHERE question_id=? ORDER BY choice_order", (question_id,)).fetchall()}
                             for question_id, text, typ in questions]
        return result


def wait_count(q, db, wanted, label):
    deadline = time.monotonic() + 80
    while time.monotonic() < deadline:
        with sqlite3.connect(db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM quizzes").fetchone()[0]
        if count == wanted:
            return
        q.delay(.2)
    raise TimeoutError(f"{label}: expected {wanted}, got {count}")


def export_collection(q, out):
    text = (PROJECT / "fixtures" / "gate1-neutral-quiz.txt").read_text()
    db = q.paths["backend"] / "results.db"
    q.go("/library")
    script = """window.__coll={done:0,error:null};(async()=>{try{
      let csrf=document.cookie.split('; ').find(x=>x.startsWith('dlms_csrf_token='));
      let token=decodeURIComponent(csrf?.split('=')[1]||'');
      for(let i=1;i<=101;i++){
        let f=new FormData(); f.append('quiz_title','Parity Coll '+String(i).padStart(3,'0'));
        f.append('file',new File([TEXT],'neutral.txt',{type:'text/plain'})); f.append('csrf_token',token);
        let r=await fetch('/process',{method:'POST',body:f,credentials:'same-origin'});
        if(!r.ok) throw Error('item '+i+' HTTP '+r.status);
        window.__coll.done=i;
      }
    }catch(e){window.__coll.error=String(e)}})();true""".replace("TEXT", json.dumps(text))
    q.js(script)
    q.wait("window.__coll?.done===101 || !!window.__coll?.error", 180)
    out["import_progress"] = json.loads(q.js("JSON.stringify(window.__coll)"))
    if out["import_progress"]["error"]:
        raise RuntimeError(out["import_progress"]["error"])
    wait_count(q, db, 101, "source quiz publication")
    out["source_semantics"] = semantics(db)
    q.go("/quiz-bundles")
    out["candidate_count"] = q.js("document.querySelectorAll('input[name=quiz_ids]').length")
    q.js("document.getElementById('selectAllBundleQuizzes').click();true")
    out["selected_count"] = q.js("[...document.querySelectorAll('input[name=quiz_ids]')].filter(x=>x.checked).length")
    before = {str(p) for p in q.paths["downloads"].rglob("*.zip")}
    q.js("document.getElementById('bundleDownload').click();true")
    q.delay(.8)
    if q.js("!!document.getElementById('bundleDownloadTop')"):
        q.js("document.getElementById('bundleDownloadTop').click();true")
    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        candidates = [p for p in q.paths["downloads"].rglob("*.zip") if str(p) not in before]
        if candidates and any(x.get("state") == "completed" for x in q.window.download_results):
            break
        q.delay(.2)
    else:
        raise TimeoutError("Collection download")
    path = candidates[0]
    out["collection_path"] = str(path)
    out["collection_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(path) as outer:
        out["outer_crc_bad"] = outer.testzip()
        inventory = json.loads(outer.read("inventory.json"))
        out["inventory"] = inventory
        out["outer_names"] = outer.namelist()
        part_data = []
        for part in inventory["bundles"]:
            content = outer.read(part["filename"])
            with zipfile.ZipFile(__import__("io").BytesIO(content)) as inner:
                manifest = json.loads(inner.read("dlms-quiz-bundle.json"))
                bad = inner.testzip()
            part_data.append({"name": part["filename"], "sha256": hashlib.sha256(content).hexdigest(),
                              "crc_bad": bad, "manifest_quiz_count": len(manifest["quizzes"]),
                              "manifest_titles": [quiz["title"] for quiz in manifest["quizzes"]]})
        out["parts"] = part_data
    out["screenshot"] = str(q.screenshot("parity-collection-export.png"))
    titles = set(out["source_semantics"])
    out["pass"] = bool(out["import_progress"]["done"] == out["candidate_count"] == out["selected_count"] == 101
                       and out["outer_crc_bad"] is None and inventory["selected_quiz_count"] == 101
                       and len(inventory["bundles"]) >= 2
                       and len(out["outer_names"]) == len(set(out["outer_names"]))
                       and set(out["outer_names"]) == {"inventory.json", "READ-ME.txt"} | {p["name"] for p in part_data}
                       and all(p["crc_bad"] is None and p["sha256"] == inventory["bundles"][i]["sha256"]
                               and p["manifest_quiz_count"] == inventory["bundles"][i]["quiz_count"] for i,p in enumerate(part_data))
                       and {title for p in part_data for title in p["manifest_titles"]} == titles)


def import_parts(q, out, source_profile):
    source = json.loads((profile_paths(source_profile)["root"] / "parity-collection-export.json").read_text())
    path = source["collection_path"]
    if hashlib.sha256(__import__("pathlib").Path(path).read_bytes()).hexdigest() != source["collection_sha256"]:
        raise ValueError("Source collection changed")
    db = q.paths["backend"] / "results.db"
    out["part_results"] = []
    with zipfile.ZipFile(path) as outer:
        for part in source["inventory"]["bundles"]:
            inner_path = q.paths["tmp"] / part["filename"]
            inner_path.write_bytes(outer.read(part["filename"]))
            if hashlib.sha256(inner_path.read_bytes()).hexdigest() != part["sha256"]:
                raise ValueError("Inner bundle hash mismatch")
            q.go("/quiz-bundles")
            q.window.file_selection_for_test = inner_path
            q.click_css('input[name="bundle_zip"]')
            q.js("document.querySelector('form[action=\"/quiz-bundles/import\"]').requestSubmit();true")
            q.wait("location.pathname.startsWith('/quiz-bundles/import/')", 40)
            review_path = q.js("location.pathname")
            q.js("(()=>{let f=document.querySelector('form[action$=\"/confirm\"]');"
                 "f.elements.confirm_import.checked=true;f.requestSubmit();return true})()")
            wait_count(q, db, sum(x["count"] for x in out["part_results"]) + part["quiz_count"], "inner publication")
            out["part_results"].append({"name": part["filename"], "review_path": review_path,
                                         "count": part["quiz_count"]})
    out["receiver_semantics"] = semantics(db)
    out["content_equal"] = json.loads(json.dumps(out["receiver_semantics"])) == source["source_semantics"]
    q.go("/library")
    out["library_count"] = q.js("document.querySelectorAll('.library-quiz-card').length")
    out["screenshot"] = str(q.screenshot("parity-collection-import.png", width=800, height=760))
    out["pass"] = bool(len(out["part_results"]) == len(source["parts"]) and out["content_equal"]
                       and len(out["receiver_semantics"]) == 101 and out["library_count"] == 101)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--phase", choices=("export", "import", "reopen"), required=True)
    p.add_argument("--source-profile", help="Project-local source profile for inner-bundle import")
    a = p.parse_args()
    q = QtChecks(a.profile)
    out = {"profile": a.profile, "phase": a.phase}
    try:
        if a.phase == "export":
            export_collection(q, out)
        elif a.phase == "import":
            if not a.source_profile:
                raise ValueError("--source-profile is required for import")
            import_parts(q, out, a.source_profile)
        else:
            prior = json.loads((q.paths["root"] / "parity-collection-import.json").read_text())
            out["receiver_semantics"] = semantics(q.paths["backend"] / "results.db")
            out["content_equal"] = json.loads(json.dumps(out["receiver_semantics"])) == prior["receiver_semantics"]
            out["pass"] = out["content_equal"] and len(out["receiver_semantics"]) == 101
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / f"parity-collection-{a.phase}.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps({k:v for k,v in out.items() if k not in ("source_semantics","receiver_semantics","inventory")}, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
