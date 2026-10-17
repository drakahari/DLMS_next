"""Separate-process selected theme and navigation-visibility acceptance."""
from __future__ import annotations

import argparse
import http.client
import json

from tests.gate1.qt_checks import QtChecks


def run(profile: str, phase: str):
    q = QtChecks(profile, automated=True)
    result = {"profile": profile, "phase": phase}
    try:
        if phase == "configure":
            q.go("/settings/appearance")
            q.js("window._themeResult='pending'; fetch('/api/theme',{method:'POST',"
                 "headers:{'Content-Type':'application/json'},"
                 "body:JSON.stringify({theme:'omarchy-lumon'})})"
                 ".then(r=>window._themeResult=r.ok?'ok':'failed'); true")
            q.wait("window._themeResult === 'ok'")
            q.go("/settings/layout")
            q.js("document.querySelector('input[name=study_area_it]').checked=false;"
                 "document.querySelector('input[name=show_certifications]').checked=false;"
                 "document.querySelector('form[action=\"/settings/layout/save\"]').requestSubmit(); true")
            q.wait("location.pathname === '/settings/layout' && location.search.includes('saved=1')")
        q.go("/settings/backup")
        assert q.window._settings_ready("backup")
        panel = q.window.settings_panel
        assert panel._theme == "omarchy-lumon", panel._theme
        assert q.window._mode_theme == "omarchy-lumon", "mode control must match the selected web theme"
        paths = [button.property("navPath") for button in panel.nav_buttons]
        assert "/it" not in paths and "/certifications" not in paths
        assert "/library" in paths and "/settings" in paths and "/settings/backup" in paths
        assert panel.buttons["backup"].isVisible()
        result["persisted_theme"] = panel._theme
        result["hidden_nav"] = ["/it", "/certifications"]
        conn = http.client.HTTPConnection("127.0.0.1", q.window.port, timeout=5)
        conn.request("GET", "/settings/backup", headers={
            "Host": f"127.0.0.1:{q.window.port}", "X-DLMS-Desktop-Token": q.window.nonce})
        response = conn.getresponse()
        policy = response.getheader("Permissions-Policy")
        response.read()
        conn.close()
        assert response.status == 200
        assert policy == "camera=(), geolocation=(), microphone=()"
        result["permissions_policy"] = policy
        result["pass"] = True
    finally:
        (q.paths["root"] / f"sidebar-persistence-{phase}.json").write_text(json.dumps(result, indent=2) + "\n")
        q.close()
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--phase", choices=("configure", "reopen"), required=True)
    args = parser.parse_args()
    run(args.profile, args.phase)


if __name__ == "__main__":
    main()
