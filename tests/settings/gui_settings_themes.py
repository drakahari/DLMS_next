"""Offscreen native-panel render and focus smoke at scoped Qt scale."""
from __future__ import annotations

import argparse
import json

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, automated=True)
    report = {"profile": args.profile, "screenshots": {}}
    try:
        q.go("/settings/reset-remove")
        q.window.resize(690, 760)
        for theme in ("light", "dark", "ethereal"):
            q.js(f"document.documentElement.dataset.theme={theme!r};true")
            q.window._settings_page_loaded(True)
            q.delay(.3)
            assert q.window._settings_ready("reset-remove")
            button = q.window.settings_buttons["exam"]
            button.setFocus()
            q.delay(.1)
            assert button.hasFocus() and button.accessibleName()
            target = q.paths["root"] / f"settings-{theme}-compact.png"
            assert q.window.grab().save(str(target))
            report["screenshots"][theme] = str(target)
        report["scale_factor"] = q.app.devicePixelRatio()
        report["pass"] = True
    finally:
        (q.paths["root"] / "settings-themes.json").write_text(json.dumps(report, indent=2) + "\n")
        q.close()
    print(json.dumps(report, indent=2))
    return 0 if report.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
