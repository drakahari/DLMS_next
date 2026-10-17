"""Create a neutral hotspot through real Qt pointer controls for pointer grading."""
from __future__ import annotations

import argparse
import base64
import json
import traceback

from desktop.isolation import AREA
from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    a = p.parse_args()
    q = QtChecks(a.profile)
    out = {"profile": a.profile}
    try:
        image = AREA / "fixtures" / "gate1-ocr.png"
        q.go("/study-packs/image-builder")
        payload = base64.b64encode(image.read_bytes()).decode()
        q.js("""(()=>{const data=atob(""" + json.dumps(payload) + """),bytes=new Uint8Array(data.length);
          for(let i=0;i<data.length;i++)bytes[i]=data.charCodeAt(i);
          const dt=new DataTransfer();dt.items.add(new File([bytes],'neutral-target.png',{type:'image/png'}));
          document.querySelector('[name=study_images]').files=dt.files;
          document.querySelector('.image-builder-upload-form').requestSubmit();return true})()""")
        q.wait("document.getElementById('builderForm') !== null", 25)
        q.js("""(()=>{const f=document.getElementById('builderForm');f.elements.pack_title.value='Completion Hotspot';
          f.elements.subject.value='General';f.elements.source_note.value='Synthetic project fixture';
          f.elements.rights_ok.checked=true;const c=document.querySelector('.image-builder-question-card');
          c.querySelector('.q-text').value='Find the synthetic target.';
          const t=c.querySelector('.q-type');t.value='hotspot';t.dispatchEvent(new Event('change'));
          c.querySelector('.hotspot-label').value='Target';return true})()""")
        q.click_css(".image-builder-hotspot-stage")
        out["stage_shape"] = json.loads(q.js("JSON.stringify(document.querySelector('.image-builder-question-card')._shape)"))
        if not out["stage_shape"].get("center"):
            raise AssertionError("Qt pointer did not place hotspot center")
        q.click_css("#builderForm button[type=submit]")
        q.wait("location.pathname.startsWith('/quizzes/')", 30)
        out["pass"] = True
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "completion-hotspot-pointer-setup.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
