"""A synthetic server redirect cannot escape its exact WebEngine origin."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import sys
import threading
import time

from desktop.isolation import AREA, isolated_environment, profile_paths
from desktop.server_mode import configured_server, default_config, write_config


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(302)
        self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/_desktop/ready")
        self.end_headers()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.2", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    paths = profile_paths(args.profile)
    config = default_config(args.profile)
    config["server"] = configured_server(config, f"http://127.0.0.2:{server.server_port}/",
                                         "Redirect fixture", private_http_opt_in=True)
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
        deadline = time.monotonic() + 12
        while not window.server_unreachable and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.05)
        assert window.server_unreachable and window.backend is None
        assert any("127.0.0.1" in item for item in (window.blocked_urls + window.server_interceptor.blocked))
        result = {"redirect_to_local_blocked": True, "server_origin": config["server"]["origin"]}
        output = AREA / "server-mode-acceptance" / f"{args.profile}-redirect.json"
        output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2))
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
