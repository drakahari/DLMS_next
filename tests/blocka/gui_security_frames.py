"""Actual Qt hostile-frame initiator check; no owner network setting changes."""
from __future__ import annotations

import argparse
import json

from tests.gate1.qt_checks import QtChecks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile)
    try:
        port = q.window.port
        q.js(f"""(()=>{{
          const frame=document.createElement('iframe');
          frame.setAttribute('sandbox','allow-scripts allow-forms');
          frame.srcdoc=`<script>fetch('http://127.0.0.1:{port}/_desktop/recovery/capabilities',{{headers:{{'X-DLMS-Recovery-Client':'1'}}}}).catch(()=>{{}});const f=document.createElement('form');f.method='POST';f.action='http://127.0.0.1:{port}/pdf-import/ocr/AAAAAAAAAAAAAAAA/start';document.documentElement.append(f);f.submit();</script>`;
          document.body.appendChild(frame);
          return true;
        }})()""")
        q.delay(1)
        denied = list(q.window.interceptor.denied_initiators)
        q.go("/static/help-troubleshooting.html")
        q.wait("document.querySelector('#localDesktopReconnect')?.innerText.includes('DLMS Desktop manages')")
        help_text = q.js("document.querySelector('#localDesktopReconnect').innerText")
        result = {"hostile_frame_denied": any(path == "/_desktop/recovery/capabilities" for path, _ in denied),
                  "hostile_pdf_form_denied": any(path == "/pdf-import/ocr/AAAAAAAAAAAAAAAA/start" for path, _ in denied),
                  "denied_initiators": denied, "legitimate_page": bool(q.js("document.body.innerText.includes('DLMS')")),
                  "desktop_help_text": help_text}
        (q.paths["root"] / "security-frames.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return 0 if result["hostile_frame_denied"] and result["hostile_pdf_form_denied"] and result["legitimate_page"] else 1
    finally:
        q.close()


if __name__ == "__main__":
    raise SystemExit(main())
