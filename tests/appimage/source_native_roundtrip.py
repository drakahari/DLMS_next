"""Supplementary Ubuntu source Qt checks, never presented as frozen-button tests."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from tests.package.normal_local_settings_smoke import descendants, starttime, stop_exact_owned


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--continue-after-foundation', action='store_true',
                   help='Preserve successful foundation evidence; resume retained ubqt02 fixture')
    a = p.parse_args()
    out = a.output.absolute()
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    for key, leaf in [('HOME','home'),('XDG_DATA_HOME','data'),('XDG_CONFIG_HOME','config'),
                      ('XDG_CACHE_HOME','cache'),('TMPDIR','tmp'),('XDG_RUNTIME_DIR','runtime')]:
        d = out / leaf
        d.mkdir(mode=0o700)
        env[key] = str(d)
    folder = Path.cwd() / '.gate1' / 'native-visible-Documents'
    checks = [('tests.gate1.gui_foundation', 'ubqt02', ['--phase','create']),
              ('tests.gate1.gui_foundation', 'ubqt02', ['--phase','reopen']),
              ('tests.gate1.gui_exam_recovery', 'ubqt02', ['--phase','create']),
              ('tests.gate1.gui_exam_recovery', 'ubqt02', ['--phase','reopen']),
              ('tests.daily_backup.gui_workflow', 'ubqt02', ['--phase','export','--folder',str(folder)]),
              ('tests.daily_backup.gui_workflow', 'ubrestore02', ['--phase','import','--folder',str(folder)]),
              ('tests.daily_backup.gui_workflow', 'ubrestore02', ['--phase','reopen','--folder',str(folder)]),
              ('tests.server_mode.gui_synthetic_mode', 'ubserver02', [])]
    if a.continue_after_foundation:
        checks = checks[2:]
    rows = []
    for i, (module, profile, extra) in enumerate(checks):
        cmd = [sys.executable, '-m', module, '--profile', profile, *extra]
        with (out / f'{i}.log').open('w') as log:
            proc = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            known = {proc.pid:starttime(proc.pid)}
            try:
                deadline = time.monotonic() + 120
                while proc.poll() is None and time.monotonic() < deadline:
                    known.update({pid:starttime(pid) for pid in descendants(proc.pid)})
                    time.sleep(.1)
                assert proc.poll() == 0, (module, proc.poll(), str(out / f'{i}.log'))
                rows.append(dict(module=module, profile=profile, arguments=extra, passed=True))
                print(module, profile, 'passed', flush=True)
            finally:
                assert not stop_exact_owned(proc, known)
        (out / 'result.json').write_text(json.dumps(dict(source_Qt_only=True,
            checks=rows, normal_native_button_acceptance=False, owned_cleanup=True), indent=2)+'\n')


if __name__ == '__main__':
    main()
