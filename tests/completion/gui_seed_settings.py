"""Set a nondefault theme through Qt before synthetic settings-reset tests."""
from __future__ import annotations

import argparse
import json
import traceback

from tests.gate1.qt_checks import QtChecks


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    name = p.parse_args().profile
    q = QtChecks(name)
    out = {"profile": name}
    try:
        q.go("/settings/appearance")
        out["before"] = q.js("document.getElementById('appearanceTheme').value")
        q.js("document.getElementById('appearanceTheme').value='ethereal';true")
        q.click_css('form[action="/settings/appearance/save"] button[type=submit]')
        q.wait("location.pathname === '/settings/appearance' && location.search.includes('saved=1')")
        out["after"] = q.js("document.getElementById('appearanceTheme').value")
        out["pass"] = out["before"] != "ethereal" and out["after"] == "ethereal"
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        (q.paths["root"] / "completion-seed-settings.json").write_text(json.dumps(out, indent=2) + "\n")
        q.close()
    print(json.dumps(out, indent=2))
    return 0 if out.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
