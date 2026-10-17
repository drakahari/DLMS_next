"""Reopen retained normal-package data, optionally using official extract-and-run."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
from tests.package.normal_local_settings_smoke import backend_nonce, descendants, request, starttime, stop_exact_owned


def main():
    p = argparse.ArgumentParser()
    for name in ('launcher', 'normal-evidence', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--extract-and-run', action='store_true')
    a = p.parse_args()
    out = a.output.absolute(); out.mkdir(mode=0o700, parents=True, exist_ok=False)
    base = a.normal_evidence.absolute()
    env = dict(PATH='/nonexistent', LANG='C.UTF-8', QT_QPA_PLATFORM='offscreen')
    for key, leaf in [('HOME','home'),('XDG_DATA_HOME','data'),('XDG_CONFIG_HOME','config'),
                      ('XDG_CACHE_HOME','cache'),('TMPDIR','tmp'),('XDG_RUNTIME_DIR','runtime')]:
        env[key] = str(base / leaf)
    if a.extract_and_run:
        env['APPIMAGE_EXTRACT_AND_RUN'] = '1'
    state = base / 'data/dlms-desktop-appimage-test/profiles/appimage01'
    identity = json.loads((state / 'desktop-profile.json').read_text())
    expected = json.loads((base / 'records.json').read_text())
    with (out / 'launch.log').open('w') as log:
        proc = subprocess.Popen([str(a.launcher.absolute()), '--profile', 'appimage01'],
                                env=env, cwd=out, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        known = {proc.pid:starttime(proc.pid)}
        try:
            end = time.monotonic() + 40
            while time.monotonic() < end:
                assert proc.poll() is None
                known.update({pid:starttime(pid) for pid in descendants(proc.pid)})
                owner = backend_nonce(proc.pid)
                if owner:
                    try:
                        if request(identity['port'], owner[1], 'GET', '/_desktop/ready')[0] == 200:
                            break
                    except OSError:
                        pass
                time.sleep(.1)
            else:
                raise TimeoutError('retained profile readiness')
            assert json.loads((state / 'desktop-profile.json').read_text()) == identity
            with sqlite3.connect(f"file:{state / 'backend/results.db'}?mode=ro", uri=True) as c:
                actual = {table:[list(row) for row in c.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in expected}
            assert actual == expected
            assert request(identity['port'], owner[1], 'GET', '/study-history')[0] == 200
            assert request(identity['port'], owner[1], 'POST', '/api/shutdown')[0] == 200
            assert proc.wait(timeout=30) == 0
            (out / 'result.json').write_text(json.dumps(dict(passed=True,
                official_extract_and_run=a.extract_and_run, normal_FUSE_launch=False,
                same_profile_origin=True, exact_records=True), indent=2)+'\n')
        finally:
            assert not stop_exact_owned(proc, known)


if __name__ == '__main__':
    main()
