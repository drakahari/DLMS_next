"""Light, Dark, Ethereal at desktop/narrow/200% in Qt WebEngine."""
from __future__ import annotations

import argparse
import json
import traceback

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    a = p.parse_args()
    q = QtChecks(a.profile)
    out = {"profile": a.profile, "themes": []}
    try:
        q.go("/settings/appearance")
        options = json.loads(q.js("JSON.stringify([...document.querySelectorAll('#appearanceTheme option')].map(x=>({value:x.value,label:x.textContent.trim()})))"))
        for name in ("Light", "Dark", "Ethereal"):
            item = next(x for x in options if name.lower() in x["label"].lower())
            q.go("/settings/appearance")
            q.js("(()=>{const f=document.querySelector('form[action=\"/settings/appearance/save\"]');"
                 "f.elements.theme.value=" + json.dumps(item["value"]) + ";f.requestSubmit();return true})()")
            q.wait("location.pathname === '/settings/appearance' && location.search.includes('saved=1')", 15)
            q.go("/library")
            entry = {"name": name, "value": item["value"],
                     "saved": q.js("document.querySelector('#dlmsQuickTheme')?.value") == item["value"]}
            for label, width, zoom in (("desktop", 1280, 1.0), ("narrow", 640, 1.0), ("zoom200", 1280, 2.0)):
                entry[label + "_screenshot"] = str(q.screenshot(
                    f"completion-{name.lower()}-{label}.png", width=width, height=800, zoom=zoom))
                entry[label + "_overflow"] = q.js(
                    "document.documentElement.scrollWidth > document.documentElement.clientWidth")
            out["themes"].append(entry)
        q.window.view.setZoomFactor(1.0)
        q.go("/library")
        q.window.view.setFocus()
        q.click_css("#librarySearch")
        QTest.keyClicks(q.app.focusWidget() or q.window.view, "Focus")
        q.delay(.2)
        out["keyboard_focus"] = q.js("document.activeElement?.id")
        out["focus_outline"] = q.js("getComputedStyle(document.activeElement).outlineStyle")
        out["pass"] = (all(t["saved"] and not t["desktop_overflow"] and not t["narrow_overflow"]
                           and not t["zoom200_overflow"] for t in out["themes"])
                       and out["keyboard_focus"] == "librarySearch" and out["focus_outline"] == "solid")
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "completion-theme-scale.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
