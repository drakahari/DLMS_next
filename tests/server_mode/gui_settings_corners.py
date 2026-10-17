"""Native Settings frame and focus checks in the actual Qt window."""
from __future__ import annotations

import argparse
import json

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, automated=True)
    results = {}
    try:
        for path, label in (("/settings/backup", "backup"), ("/settings/reset-remove", "reset")):
            q.go(path)
            q.delay(.5)
            assert q.window.settings_panel.isVisible()
            panel = q.window.settings_panel
            for width, zoom in ((1280, 1), (690, 1), (1280, 2)):
                q.window.resize(width, 850)
                q.window.view.setZoomFactor(zoom)
                q.delay(.3)
                expected_radius = 0 if width < 780 else 24
                assert panel.shell.radius == expected_radius
                assert panel.shell.outline.radius == expected_radius
                if expected_radius:
                    assert panel.shell.outline.isVisible()
                    assert panel.shell.outline.geometry() == panel.shell.rect()
                assert panel.buttons["backup" if label == "backup" else "exam"].isVisible()
                output = q.paths["root"] / f"server-block-{label}-{width}-{zoom}.png"
                assert q.window.grab().save(str(output))
                results[f"{label}-{width}-{zoom}"] = str(output)
            q.window.resize(1280, 850)
        output = q.paths["root"] / "settings-corner-result.json"
        output.write_text(json.dumps(results, indent=2))
        print(json.dumps(results, indent=2))
    finally:
        q.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
