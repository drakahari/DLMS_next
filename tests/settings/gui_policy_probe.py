"""Inspect policy support inside this project's isolated Qt WebEngine page."""
from __future__ import annotations

import json
import http.client
import argparse
from tests.gate1.qt_checks import QtChecks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, automated=True)
    try:
        result = {}
        for path in ("/", "/library", "/settings/backup", "/history"):
            q.go(path)
            browser = json.loads(q.js("JSON.stringify({features:document.featurePolicy?.allowedFeatures(),"
                "paymentType:typeof PaymentRequest,usbType:typeof navigator.usb,"
                "camera:document.featurePolicy?.allowsFeature('camera'),"
                "microphone:document.featurePolicy?.allowsFeature('microphone'),"
                "geolocation:document.featurePolicy?.allowsFeature('geolocation')})"))
            conn = http.client.HTTPConnection("127.0.0.1", q.window.port, timeout=5)
            conn.request("GET", path, headers={"Host": f"127.0.0.1:{q.window.port}",
                         "X-DLMS-Desktop-Token": q.window.nonce})
            response = conn.getresponse()
            header = response.getheader("Permissions-Policy")
            response.read()
            conn.close()
            assert response.status == 200
            assert header == "camera=(), geolocation=(), microphone=()", (path, header)
            assert browser["paymentType"] == browser["usbType"] == "undefined"
            assert "payment" not in browser["features"] and "usb" not in browser["features"]
            assert all(browser[key] is False for key in ("camera", "microphone", "geolocation"))
            result[path] = {"policy": header, **browser}
        print(json.dumps(result, indent=2), flush=True)
    finally:
        q.close()


if __name__ == "__main__":
    main()
