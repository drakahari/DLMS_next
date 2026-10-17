"""A task-owned self-signed HTTPS fixture must not gain a certificate bypass."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import threading
import time

from desktop.isolation import AREA, isolated_environment, profile_paths
from desktop.server_mode import configured_server, default_config, write_config


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<html><body>Untrusted synthetic HTTPS page</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    run = AREA / "server-mode-acceptance" / f"{args.profile}-bad-cert"
    run.mkdir(mode=0o700, parents=True, exist_ok=False)
    cert, key = run / "cert.pem", run / "key.pem"
    with (run / "openssl.log").open("w") as log:
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-keyout", str(key), "-out", str(cert), "-days", "1",
                        "-subj", "/CN=127.0.0.2"], check=True, stdout=log, stderr=subprocess.STDOUT)
    server = ThreadingHTTPServer(("127.0.0.2", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"https://127.0.0.2:{server.server_port}"
    paths = profile_paths(args.profile)
    config = default_config(args.profile)
    config["server"] = configured_server(config, origin, "Bad certificate fixture", private_http_opt_in=False)
    config["mode"] = "server"
    write_config(args.profile, config)
    env = isolated_environment(paths)
    os.environ.clear()
    os.environ.update(env)
    os.environ["DLMS_DESKTOP_AUTOMATED"] = "1"
    from PySide6.QtWidgets import QApplication
    from desktop.shell import DesktopWindow
    app = QApplication(sys.argv[:1])
    window = DesktopWindow(paths, args.profile)
    window.show()
    window.start()
    try:
        deadline = time.monotonic() + 15
        while not window.server_unreachable and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.05)
        assert window.server_unreachable and not window.view.isVisible()
        assert "Certificate errors" in window.server_status.text()
        assert window.backend is None
        result = {"bad_certificate_blocked": True, "origin": origin}
        (run / "result.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    finally:
        window.close()
        app.processEvents()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
