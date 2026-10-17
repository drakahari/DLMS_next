"""Exact accepted Law text in a fresh normal package across process reopen; no hooks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from desktop.windows_files import assert_path, owned, pinned_parents
from package_windows_webview2.acceptance import payload_binding
from tests.windows.normal_candidate import request
from tests.windows.normal_processes import descendants, identity, alive, backend_nonce


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    for name in ('exe', 'inventory', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    exe = args.exe.resolve(strict=True)
    out = args.output.absolute()
    work = (ROOT / '.gate1/windows-native').resolve(strict=True)
    if not exe.is_relative_to(work) or not out.resolve(strict=False).is_relative_to(work):
        raise ValueError('Only this worktree normal payload and new synthetic output are permitted')
    if out.exists():
        raise FileExistsError('Preserve prior evidence; use a new output')
    with pinned_parents(out):
        assert_path(out)
        out.mkdir(mode=0o700)
        owned(out, private=True)
    binding = payload_binding(exe, args.inventory)
    data = out / 'Synthetic Law café 日本 with spaces'
    data.mkdir(mode=0o700)
    (data / '.dlms-desktop-windows-candidate.json').write_text(json.dumps({'kind': 'dlms-desktop-windows-candidate', 'version': 1}))
    profile = 'lawtext01'
    state = data / 'profiles' / profile
    report = {'normal_package': True, 'app_test_hooks': False, 'physical_acceptance': False,
              'workflow_transport': 'authenticated owned-backend HTTP', 'runs': [],
              'passed': False, 'harness_sha256': sha(Path(__file__)), **binding}
    expected = None
    cases = {
        'lf': '  Café 日本 Ω\nfirst\nlast\n',
        'crlf': '  Café 日本 Ω\r\nfirst\r\nlast\r\n',
        'mixed': '  Café 日本 Ω\r\nfirst\nsecond\rthird\r\nlast\n',
    }
    saved_names = {}
    env = {k: v for k, v in os.environ.items() if not k.startswith(('DLMS_', 'QUIZAPP_', 'QTWEBENGINE_', 'PYTHON'))}
    env['PATH'] = str(out / 'no-host-tools')
    try:
        for run in range(2):
            observed = {}
            port = nonce = None
            with (out / f'launcher-{run}.log').open('w') as log:
                proc = subprocess.Popen([str(exe), '--profile', profile, '--data-root', str(data)],
                                        cwd=out, env=env, stdout=log, stderr=subprocess.STDOUT)
                observed[proc.pid] = identity(proc.pid)['start']
                try:
                    deadline = time.monotonic() + 60
                    while time.monotonic() < deadline:
                        assert proc.poll() is None, f'normal launcher exited {proc.returncode}'
                        for pid in descendants(proc.pid):
                            try:
                                observed[pid] = identity(pid)['start']
                            except OSError:
                                pass
                        owner = backend_nonce(proc.pid, exe, {})
                        manifest_path = state / 'desktop-profile.json'
                        if owner and manifest_path.is_file():
                            manifest = json.loads(manifest_path.read_text())
                            port, nonce = manifest['port'], owner[1]
                            try:
                                if request(port, nonce, 'GET', '/_desktop/ready', headers={'X-DLMS-Desktop-Nonce': nonce})[0] == 200:
                                    break
                            except OSError:
                                pass
                        time.sleep(.1)
                    else:
                        raise TimeoutError('normal package did not become ready')
                    headers = {'Origin': f'http://127.0.0.1:{port}', 'Sec-Fetch-Site': 'same-origin'}
                    code, body, response = request(port, nonce, 'GET', '/api/csrf-token', headers=headers | {'X-DLMS-CSRF-Refresh': '1'})
                    assert code == 200
                    csrf = json.loads(body)['csrf_token']
                    headers.update({'Cookie': '; '.join(v.split(';', 1)[0] for v in response['_set_cookies']), 'X-CSRFToken': csrf})
                    if run == 0:
                        for name, raw in cases.items():
                            values = {'case_slug': name, 'raw_packet': raw, 'action': 'save_and_preview', 'csrf_token': csrf}
                            code, body, response = request(port, nonce, 'POST', '/law/import', urlencode(values).encode(),
                                                           headers | {'Content-Type': 'application/x-www-form-urlencoded'})
                            assert code == 302, (name, code, body[:500])
                            location = response.get('Location', '')
                            assert location.startswith('/law/imports/') and location.endswith('.txt'), location
                            saved_names[name] = location.rsplit('/', 1)[1]
                    current = {}
                    for name, raw in cases.items():
                        filename = saved_names[name]
                        path = state / 'backend/law/imports' / filename
                        assert path.read_bytes() == raw.encode('utf-8'), (name, 'disk bytes changed')
                        code, body, _ = request(port, nonce, 'GET', '/law/imports/' + filename)
                        assert code == 200 and raw.encode('utf-8') in body, (name, code, 'preview changed separators')
                        current[name] = {'filename': filename, 'utf8_sha256': sha(path), 'bytes': len(path.read_bytes())}
                    assert len(list((state / 'backend/law/imports').glob('*.txt'))) == len(cases)
                    if expected is None:
                        expected = current
                    else:
                        assert current == expected, 'Law packet bytes/names changed across normal process reopen'
                    for pid in descendants(proc.pid):
                        try:
                            observed[pid] = identity(pid)['start']
                        except OSError:
                            pass
                    assert request(port, nonce, 'POST', '/api/shutdown')[0] == 200
                    assert proc.wait(timeout=40) == 0
                    deadline = time.monotonic() + 8
                    while any(alive(pid, birth) for pid, birth in observed.items()) and time.monotonic() < deadline:
                        time.sleep(.1)
                    assert not any(alive(pid, birth) for pid, birth in observed.items())
                    report['runs'].append({'run': run, 'exact_cleanup': True, 'uuid': manifest['uuid'], 'port': port,
                                           'law_packets': current})
                finally:
                    if proc.poll() is None:
                        if port and nonce:
                            try:
                                request(port, nonce, 'POST', '/api/shutdown')
                                proc.wait(timeout=15)
                            except (OSError, subprocess.TimeoutExpired):
                                pass
                        if proc.poll() is None:
                            report['forced_test_cleanup'] = True
                            proc.kill()
                            proc.wait(timeout=10)
        assert report['runs'][0]['uuid'] == report['runs'][1]['uuid']
        assert report['runs'][0]['port'] == report['runs'][1]['port']
        assert payload_binding(exe, args.inventory) == binding
        report.update(passed=True, payload_verified_before_and_after=True,
                      exact_lf_crlf_mixed_unicode=True, separate_normal_process_reopen=True)
    finally:
        (out / 'result.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('Normal package accepted Law Unicode/LF/CRLF/mixed text and separate-process reopen passed.')


if __name__ == '__main__':
    main()
