"""Read-only inventory of live controls in the actual disposable Qt window."""
from __future__ import annotations

import argparse
import json

from tests.gate1.qt_checks import QtChecks


PAGES = (
    "/library", "/quiz-bundles", "/certifications", "/it", "/medical", "/law",
    "/external-ai/quiz-builder", "/admin/maintenance", "/exam-plans",
    "/certifications/new", "/medical/matching", "/medical/anatomy",
    "/law/create", "/law/import", "/content-packs", "/study-packs",
    "/create_short_quiz", "/quiz-composer", "/admin/image-editor",
    "/settings/reset-remove", "/settings/backup", "/pdf-import", "/study-next",
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    args = p.parse_args()
    q = QtChecks(args.profile)
    output = {}
    try:
        for path in PAGES:
            try:
                q.go(path)
                output[path] = json.loads(q.js("""JSON.stringify({
                    title:document.title,pathname:location.pathname,
                    forms:[...document.forms].map(f=>({action:f.getAttribute('action'),method:f.method,
                        fields:[...f.querySelectorAll('input,select,textarea,button')].map(e=>({tag:e.tagName,
                            name:e.name||'',id:e.id||'',type:e.type||'',text:(e.textContent||'').trim().slice(0,80)}))})),
                    links:[...document.querySelectorAll('main a[href]')].map(a=>({href:a.getAttribute('href'),text:a.innerText.trim().slice(0,80)})).slice(0,70),
                    buttons:[...document.querySelectorAll('main button')].map(b=>({id:b.id||'',text:b.innerText.trim().slice(0,80)})).slice(0,70)
                })"""))
            except Exception as exc:
                output[path] = {"error": f"{type(exc).__name__}: {exc}"}
        target = q.paths["root"] / "parity-dom-inventory.json"
        target.write_text(json.dumps(output, indent=2) + "\n")
        print(target)
        return 0
    finally:
        q.close()


if __name__ == "__main__":
    raise SystemExit(main())
