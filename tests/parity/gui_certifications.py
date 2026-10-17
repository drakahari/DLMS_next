"""Qt certification, renewal, training, credit and attachment fidelity."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sqlite3
import time
import traceback

from tests.gate1.qt_checks import QtChecks


def until(q, fn, label, timeout=20):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        value=fn()
        if value:return value
        q.delay(.12)
    raise TimeoutError(label)


def table(db, name):
    with sqlite3.connect(db) as c:
        return c.execute(f"SELECT * FROM {name} ORDER BY 1").fetchall()


def pixel_hash(content):
    from PIL import Image
    image = Image.open(io.BytesIO(content)).convert("RGBA")
    return hashlib.sha256(image.tobytes()).hexdigest()


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--profile",required=True)
    p.add_argument("--reopen",action="store_true")
    a=p.parse_args()
    q=QtChecks(a.profile)
    db=q.paths["backend"]/"results.db"
    out={"profile":a.profile,"reopen":a.reopen}
    try:
        if not a.reopen:
            from PIL import Image
            badge=q.paths["tmp"]/"parity-badge.png"
            Image.new("RGB",(36,36),(10,70,180)).save(badge)
            out["badge_sha256"]=hashlib.sha256(badge.read_bytes()).hexdigest()
            out["badge_pixel_sha256"]=pixel_hash(badge.read_bytes())
            q.go("/certifications/new")
            q.js("(()=>{let f=document.querySelector('form.cert-form');f.elements.field_name.value='Parity Credential';f.elements.field_issuer.value='Neutral Issuer';f.elements.field_earned.value='2025-04-03';f.elements.field_expiration.value='2027-04-03';return true})()")
            q.window.file_selection_for_test=badge
            q.click_css("input[name=badge]")
            out["badge_selected"]=q.js("document.querySelector('input[name=badge]').files[0]?.name")
            q.js("document.querySelector('form.cert-form').requestSubmit();true")
            credential=until(q,lambda: next((r for r in table(db,"certifications") if json.loads(r[1]).get("name")=="Parity Credential"),None),"certification save")
            cid=credential[0]
            out["credential_id"]=cid
            out["credential_data"]=json.loads(credential[1])
            out["attachment_rows"]=[(r[0],r[1],r[2],hashlib.sha256(r[3]).hexdigest()) for r in table(db,"certification_attachments")]
            out["attachment_pixel_sha256"]=[pixel_hash(r[3]) for r in table(db,"certification_attachments")]
            out["detail_screenshot"]=str(q.screenshot("parity-certification.png"))
            q.go(f"/certifications/{cid}/edit")
            q.js("(()=>{let f=document.querySelector('form.cert-form');f.elements.field_name.value='Parity Credential Edited';f.elements.field_expiration.value='2027-06-03';f.requestSubmit();return true})()")
            until(q,lambda: any(json.loads(r[1]).get("name")=="Parity Credential Edited" for r in table(db,"certifications")),"certification edit")
            out["edited_data"]=json.loads(table(db,"certifications")[0][1])
            q.go(f"/certifications/{cid}/cycles/new")
            q.js("(()=>{let f=document.querySelector('form.cert-form');f.elements.field_expiration.value='2029-06-03';f.elements.field_renewed.value='2027-05-01';f.requestSubmit();return true})()")
            until(q,lambda: len(table(db,"certification_cycles"))==2,"renewal save")
            out["cycles"]=[(r[0],r[3],json.loads(r[2])) for r in table(db,"certification_cycles")]
            current=max(out["cycles"],key=lambda x:x[1])
            q.go("/certifications/training/new")
            q.js("(()=>{let f=document.querySelector('form.cert-form');f.elements.field_name.value='Parity Workshop';f.elements.field_provider.value='Neutral Trainer';f.elements.field_completed.value='2026-03-12';f.elements.duration_hours.value='2';f.elements.duration_minutes.value='30';f.requestSubmit();return true})()")
            training=until(q,lambda: next((r for r in table(db,"certification_training") if json.loads(r[1]).get("name")=="Parity Workshop"),None),"training save")
            tid=training[0]
            out["training_id"]=tid
            out["training_data"]=json.loads(training[1])
            q.go(f"/certifications/{cid}/cycles/{current[0]}/allocate?training={tid}")
            q.js("(()=>{let f=document.querySelector('form.cert-form');f.elements.field_proposed.value='2.5';f.elements.duration_hours.value='2';f.elements.duration_minutes.value='30';f.elements.field_submitted.value='2';f.elements.field_accepted.value='1.5';f.requestSubmit();return true})()")
            allocation=until(q,lambda: next((r for r in table(db,"certification_allocations") if r[2]==tid),None),"allocation save")
            out["allocation"]=(allocation[0],allocation[1],allocation[2],json.loads(allocation[3]))
            q.go(f"/certifications/{cid}")
            out["detail_has_workshop"]=q.js("document.body.innerText.includes('Parity Workshop')")
            out["detail_has_renewal"]=q.js("document.body.innerText.includes('2029-06-03')")
            out["final_screenshot"]=str(q.screenshot("parity-certification-renewal.png"))
        else:
            prior=json.loads((q.paths["root"]/"parity-certifications.json").read_text())
            cid=prior["credential_id"]
            out["credential_id"]=cid
            out["edited_data"]=json.loads(table(db,"certifications")[0][1])
            out["cycles"]=[(r[0],r[3],json.loads(r[2])) for r in table(db,"certification_cycles")]
            out["training_id"]=prior["training_id"]
            out["training_data"]=json.loads(table(db,"certification_training")[0][1])
            allocation=table(db,"certification_allocations")[0]
            out["allocation"]=(allocation[0],allocation[1],allocation[2],json.loads(allocation[3]))
            out["attachment_rows"]=[(r[0],r[1],r[2],hashlib.sha256(r[3]).hexdigest()) for r in table(db,"certification_attachments")]
            out["attachment_pixel_sha256"]=[pixel_hash(r[3]) for r in table(db,"certification_attachments")]
            q.go(f"/certifications/{cid}")
            out["detail_has_workshop"]=q.js("document.body.innerText.includes('Parity Workshop')")
            out["detail_has_renewal"]=q.js("document.body.innerText.includes('2029-06-03')")
            out["final_screenshot"]=str(q.screenshot("parity-certification-reopen.png"))
            out["records_match_prior"]=all(json.loads(json.dumps(out.get(key)))==prior.get(key) for key in
                                           ("edited_data","cycles","training_id","training_data","allocation","attachment_rows","attachment_pixel_sha256"))
        out["pass"]=bool(out.get("detail_has_workshop") and out.get("detail_has_renewal")
                         and out["edited_data"].get("earned")=="2025-04-03"
                         and any(c[2].get("expiration")=="2027-06-03" for c in out["cycles"])
                         and len(out["cycles"])==2 and out["training_data"].get("duration_minutes")==150
                         and out["allocation"][3].get("submitted")==2
                         and out["allocation"][3].get("accepted")==1.5
                         and (out.get("records_match_prior") if a.reopen else
                              out.get("badge_selected")=="parity-badge.png" and
                              len(out.get("attachment_rows",[]))==1 and
                              out["attachment_rows"][0][2]==out["attachment_rows"][0][3] and
                              out["attachment_pixel_sha256"]==[out["badge_pixel_sha256"]]))
    except Exception as exc:
        out["error"]=f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"]/("parity-certifications-reopen.json" if a.reopen else "parity-certifications.json")).write_text(json.dumps(out,indent=2)+"\n")
        q.close()
    print(json.dumps(out,indent=2))
    return 0 if out.get("pass") else 1


if __name__=="__main__":
    raise SystemExit(main())
