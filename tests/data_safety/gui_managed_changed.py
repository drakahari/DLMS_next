"""Qt refusal of a changed accepted stage; leaves original receipts untouched."""
import argparse
import json
import sqlite3
from PySide6.QtCore import QUrl
from tests.gate1.qt_checks import QtChecks


def rows(path):
    with sqlite3.connect(path / "results.db") as conn:
        return [list(row) for row in conn.execute("SELECT id,title,source_file FROM quizzes ORDER BY id")]


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--profile",required=True);args=parser.parse_args()
    q=QtChecks(args.profile)
    root,backend=q.paths["root"],q.paths["backend"]
    token=(root/"gate-a-token.txt").read_text().strip()
    out={"before":rows(backend),"token":token}
    try:
        q.window.view.setUrl(QUrl(f"http://127.0.0.1:{q.window.port}/quiz-bundles/import/{token}"))
        q.wait("location.pathname === '/quiz-bundles'",20)
        out["review_refusal"]=q.js("document.body.innerText")
        out["review_screenshot"]=str(q.screenshot("gate-a-changed-review.png",width=1024,height=740))
        q.js("(()=>{let f=document.createElement('form');f.method='POST';f.action='/quiz-bundles/import/"+token+"/confirm';let x=document.createElement('input');x.name='confirm_import';x.value='yes';f.appendChild(x);document.body.appendChild(f);window.dlmsProtectForm(f);f.requestSubmit();return true})()")
        q.wait("location.pathname === '/quiz-bundles'",20)
        q.delay(0.7)
        out["confirm_refusal"]=q.js("document.body.innerText")
        out["after"]=rows(backend)
        out["confirm_screenshot"]=str(q.screenshot("gate-a-changed-confirm.png",width=1024,height=740))
        assert "accepted import's staged input is unavailable or changed" in out["review_refusal"]
        assert "accepted import's staged input is unavailable or changed" in out["confirm_refusal"]
        assert out["before"]==out["after"]
        out["pass"]=True
    finally:
        (root/"gate-a-changed.json").write_text(json.dumps(out,indent=2)+"\n")
        q.close()
    print(json.dumps({k:out.get(k) for k in ("pass","before","after")},indent=2))

if __name__=="__main__":main()
