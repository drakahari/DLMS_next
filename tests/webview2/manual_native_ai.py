"""Owner-only, bounded synthetic Server walkthrough of a normal executable.

No renderer instrumentation, native input automation, browser dispatch override,
production endpoint, Local backend or personal profile. Close DLMS normally.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / '.gate1/windows-native'
PAGE = b'''<!doctype html><html><head><meta charset="utf-8"><title>Synthetic Server AI check</title>
<style>body{font:18px system-ui;margin:3em;max-width:850px;background:#252038;color:#eee}
button,a{font:inherit;margin:10px;padding:12px}a{color:#ace}textarea{width:95%;height:100px}</style></head>
<body><h1>Synthetic Server AI check</h1><p>No real quiz or personal data.</p>
<textarea id="prompt">Synthetic practice question: Which number is even? A. 3 B. 4. Answer: B.</textarea>
<button onclick="document.querySelector('#prompt').select();document.execCommand('copy');document.querySelector('#status').textContent='Synthetic prompt copied; nothing submitted.'">Copy synthetic prompt only</button>
<p>Use Desktop's bottom-right <b>AI websites</b> menu, then ChatGPT, Claude or Gemini.
It opens only the website; paste manually if you choose.</p><p id="status">Clipboard not changed yet.</p>
<p><a href="https://chatgpt.com/" target="_blank" rel="noopener noreferrer">Ordinary external link: still requires confirmation</a></p>
<p>This fixture is not a captured DLMS page. Actual DLMS page controls are covered separately by instrumented tests.</p>
</body></html>'''


def main():
    sys.path.insert(0, str(ROOT))  # Absolute-script walkthrough works from any cwd.
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    exe, out = args.exe.absolute(), args.output.absolute()
    if not exe.is_relative_to(WORK) or not out.is_relative_to(WORK) or out.exists():
        raise ValueError('Use an existing project-local candidate and fresh project-local output')
    from desktop.windows_files import assert_path
    assert_path(exe, leaf=True); assert_path(out)
    if not exe.is_file(): raise ValueError('Candidate executable is missing')
    out.mkdir(mode=0o700)
    from package_windows.entry import root_path
    data = root_path(out / 'data', create=True)
    records = []
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            records.append({'local_token_present': bool(self.headers.get('X-DLMS-Desktop-Token')
                                                       or self.headers.get('X-DLMS-Desktop-Nonce'))})
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(PAGE)))
            self.end_headers(); self.wfile.write(PAGE)
        def do_POST(self): self.send_error(405)
    server = ThreadingHTTPServer(('127.0.0.2', 0), Fixture)
    origin = 'http://127.0.0.2:' + str(server.server_port)
    shell = data / 'shell/walkserver'
    shell.mkdir(mode=0o700, parents=True)
    from desktop.server_mode import default_config, configured_server
    config = default_config('walkserver')
    config.update(mode='server', server=configured_server(config, origin, 'Synthetic AI walkthrough', private_http_opt_in=True))
    (shell / 'mode.json').write_text(json.dumps(config), encoding='utf-8')
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    proc = None
    started = time.monotonic()
    print('Opening the normal candidate with a fresh Server-only test profile.\n'
          'Copy synthetic prompt, then AI websites > provider. Repeat with keyboard.\n'
          'Ordinary link must still ask. Close DLMS normally; this fixture lasts at most 15 minutes.', flush=True)
    try:
        with (out / 'launcher.log').open('w', encoding='utf-8') as log:
            proc = subprocess.Popen([str(exe), '--data-root', str(data), '--profile', 'walkserver'],
                                    cwd=out, stdout=log, stderr=subprocess.STDOUT)
            while proc.poll() is None and time.monotonic() - started < 900:
                time.sleep(.25)
            if proc.poll() is None:
                print('Synthetic server capture expired. DLMS was left open; close it normally.', flush=True)
    finally:
        server.shutdown(); server.server_close()
        (out / 'result.json').write_text(json.dumps({'normal_package':True,'app_test_hooks':False,
            'physical_acceptance':'owner reports separately','fixture_not_captured_dlms_ui':True,
            'observed_request_count':len(records),
            'local_token_headers_absent':bool(records) and not any(r['local_token_present'] for r in records),
            'data_root':str(data),'profile':'walkserver','exit':proc.poll() if proc else None,
            'app_terminated_by_harness':False}, indent=2)+'\n')


if __name__ == '__main__': main()
