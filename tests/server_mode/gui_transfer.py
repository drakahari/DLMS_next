"""Synthetic Server upload/download through the unprivileged Qt browser."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time

from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt

from desktop.isolation import AREA
from desktop.server_mode import configured_server, write_config
from tests.gate1.qt_checks import QtChecks


PAYLOAD = b"synthetic server transfer check\n"


class Handler(BaseHTTPRequestHandler):
    uploaded: bytes | None = None

    def do_GET(self):
        if self.path == "/download":
            self.send_response(200)
            self.send_header("Content-Disposition", "attachment; filename=server-synthetic.txt")
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(PAYLOAD)))
            self.end_headers()
            self.wfile.write(PAYLOAD)
            return
        body = (b"<html><body><label>Upload synthetic file <input id='upload' type='file'></label>"
                b"<a id='download' href='/download'>Download synthetic file</a></body></html>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        Handler.uploaded = body
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"accepted")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    uploads = AREA / "server-uploads"
    uploads.mkdir(mode=0o700, exist_ok=True)
    fixture = uploads / f"{args.profile}-synthetic.txt"
    fixture.write_bytes(PAYLOAD)
    server = ThreadingHTTPServer(("127.0.0.2", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    q = None
    try:
        q = QtChecks(args.profile, automated=True)
        origin = f"http://127.0.0.2:{server.server_port}"
        config = dict(q.window.mode_config,
                      server=configured_server(q.window.mode_config, origin, "Transfer fixture", private_http_opt_in=True))
        write_config(args.profile, config)
        q.window.mode_config = config
        q.window._update_mode_toolbar()
        assert q.window.switch_to_server()
        q.wait("document.readyState === 'complete' && !!document.querySelector('#upload')", 20)
        point = json.loads(q.js("JSON.stringify((()=>{const r=document.querySelector('#upload').getBoundingClientRect();"
                                 "return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)}})())"))
        q.window.file_selection_for_test = fixture
        location = QPoint(point["x"], point["y"])
        target = q.window.view.childAt(location) or q.window.view
        QTest.mouseClick(target, Qt.MouseButton.LeftButton,
                         pos=target.mapFrom(q.window.view, location))
        q.wait("document.querySelector('#upload').files.length === 1", 10)
        q.js("window.uploadStatus='pending';const form=new FormData();form.append('file',document.querySelector('#upload').files[0]);"
             "fetch('/upload',{method:'POST',body:form}).then(r=>window.uploadStatus=r.status);true")
        q.wait("window.uploadStatus === 200", 10)
        assert Handler.uploaded is not None and PAYLOAD in Handler.uploaded
        q.js("document.querySelector('#download').click(); true")
        deadline = time.monotonic() + 10
        while not any(item["state"] == "completed" for item in q.window.download_results) and time.monotonic() < deadline:
            q.delay(.1)
        completed = [item for item in q.window.download_results if item["state"] == "completed"]
        assert completed, q.window.download_results
        downloaded = Path(completed[-1]["path"])
        assert downloaded.read_bytes() == PAYLOAD
        assert downloaded.is_relative_to(q.window.server_paths["downloads"])
        assert not list(q.paths["downloads"].iterdir())
        result = {"server_upload_bytes": len(PAYLOAD), "server_download_match": True,
                  "server_download": str(downloaded), "local_downloads_untouched": True}
        (q.paths["root"] / "server-transfer.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
        return 0
    finally:
        if q is not None:
            q.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
