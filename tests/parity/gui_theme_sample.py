"""Sample additional existing themes, compact layout, zoom and Qt keyboard focus."""
from __future__ import annotations

import argparse
import json
import sqlite3
import traceback

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    a = p.parse_args()
    q = QtChecks(a.profile)
    out = {"profile": a.profile, "themes": []}
    try:
        db = q.paths["backend"] / "results.db"
        with sqlite3.connect(db) as conn:
            before = {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
                      for t in ("questions","choices","study_responses","attempts")}
        q.go("/settings/appearance")
        options = json.loads(q.js("JSON.stringify([...document.querySelectorAll('#appearanceTheme option')].map(x=>({value:x.value,label:x.textContent.trim()})))"))
        out["available_count"] = len(options)
        selected = [x for x in options if not any(name.lower() in x["label"].lower() for name in ("Light","Dark","Ethereal"))][:4]
        for item in selected:
            q.window.view.setZoomFactor(1.0)
            q.go("/settings/appearance")
            q.js("(()=>{let f=document.querySelector('form[action=\"/settings/appearance/save\"]');"
                 "f.elements.theme.value=" + json.dumps(item["value"]) + ";f.requestSubmit();return true})()")
            q.wait("location.pathname === '/settings/appearance' && location.search.includes('saved=1')", 15)
            q.go("/library")
            entry = {"id": item["value"], "label": item["label"],
                     "quick_theme": q.js("document.querySelector('#dlmsQuickTheme')?.value"),
                     "quiz_count": q.js("document.querySelectorAll('.library-quiz-card').length")}
            entry["compact_screenshot"] = str(q.screenshot(f"parity-theme-{item['value']}-compact.png", width=640, height=760))
            entry["compact_horizontal_overflow"] = q.js("document.documentElement.scrollWidth > document.documentElement.clientWidth")
            entry["scaled_screenshot"] = str(q.screenshot(f"parity-theme-{item['value']}-scaled.png", width=960, height=760, zoom=1.5))
            entry["scaled_horizontal_overflow"] = q.js("document.documentElement.scrollWidth > document.documentElement.clientWidth")
            out["themes"].append(entry)
        q.go("/library")
        q.window.view.setZoomFactor(1.0)
        q.window.view.setFocus()
        q.click_css("#librarySearch")
        out["keyboard_before"] = q.js("document.activeElement?.outerHTML")
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        # The real pointer establishes focus; Qt key events then exercise input.
        out["qt_focus_widget"] = type(q.app.focusWidget()).__name__
        QTest.keyClicks(q.app.focusWidget() or q.window.view, "Parity")
        q.delay(.2)
        out["keyboard_active"] = q.js("document.activeElement?.id")
        out["keyboard_search_value"] = q.js("document.getElementById('librarySearch').value")
        out["keyboard_focus_outline"] = q.js("getComputedStyle(document.activeElement).outlineStyle")
        out["keyboard_screenshot"] = str(q.screenshot("parity-keyboard-search.png", width=800, height=760))
        with sqlite3.connect(db) as conn:
            out["canonical_unchanged"] = all(conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() == before[t] for t in before)
        out["pass"] = bool(len(out["themes"]) == 4 and out["available_count"] >= 7
                           and all(x["id"] == x["quick_theme"] and x["quiz_count"] >= 1
                                   and not x["compact_horizontal_overflow"] and not x["scaled_horizontal_overflow"]
                                   for x in out["themes"])
                           and out["keyboard_active"] == "librarySearch" and out["keyboard_search_value"] == "Parity"
                           and out["keyboard_focus_outline"] == "solid"
                           and out["canonical_unchanged"])
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "parity-theme-sample.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
