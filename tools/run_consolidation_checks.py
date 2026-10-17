"""Explicit application/platform test scopes; no release or installation action."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LINUX_CONTRACTS = (
    'backup_binding', 'blocka', 'blockb', 'blockc', 'daily_backup',
    'daily_feedback', 'daily_use', 'data_safety', 'file_selection',
    'linux_windows', 'server_mode', 'session_browser', 'settings',
    'shutdown', 'package', 'appimage', 'minimal_bundle', 'gate1', 'completion',
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scope', choices=('application', 'desktop-linux', 'windows-portable', 'windows-native'))
    parser.add_argument('--basetemp', type=Path, required=True)
    args = parser.parse_args()
    temporary = args.basetemp.absolute()
    if temporary.exists() or temporary.is_symlink():
        parser.error('Use a fresh basetemp; prior failure evidence must be retained')
    temporary.parent.mkdir(parents=True, exist_ok=True)
    temporary.mkdir(mode=0o700)
    environment = os.environ.copy()
    environment.setdefault('QT_QPA_PLATFORM', 'offscreen')
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    # This private checkout has independent Git metadata. A public ordinary
    # checkout needs no override; subprocess hygiene checks must support both.
    if (ROOT / '.dlms-git').is_dir():
        environment.update(GIT_DIR=str(ROOT / '.dlms-git'), GIT_WORK_TREE=str(ROOT))
    prefix = [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-m', 'not browser']
    if args.scope == 'windows-native' and os.name != 'nt':
        parser.error('Native Windows acceptance requires a separately authorized Windows machine')
    if args.scope == 'application':
        selections = [[str(p.relative_to(ROOT)) for p in sorted((ROOT / 'tests').glob('test_*.py'))]]
    elif args.scope == 'windows-portable':
        selections = [['tests/webview2', 'tests/server_mode/test_attachment_surface.py']]
    elif args.scope == 'windows-native':
        # Retired synthetic renderer and personal diagnostic fixtures remain
        # private historical evidence, not active production-host acceptance.
        retired = {'test_webview2_experiment.py', 'test_browser_environment_probe.py'}
        selections = [[str(p.relative_to(ROOT))] for name in ('webview2', 'windows')
                      for p in sorted((ROOT / 'tests' / name).glob('test_*.py'))
                      if p.name not in retired]
    else:
        # Different Qt suites create QCoreApplication/QApplication lifetimes.
        # Separate processes avoid an invalid process-wide Qt fixture mixture.
        selections = [[str(p.relative_to(ROOT))] for name in LINUX_CONTRACTS
                      for p in sorted((ROOT / 'tests' / name).glob('test_*.py'))]
    results = []
    for index, selection in enumerate(selections):
        command = prefix + selection + [f'--basetemp={temporary / str(index)}']
        print('RUN', ' '.join(command), flush=True)
        results.append(subprocess.call(command, cwd=ROOT, env=environment))
    return 0 if all(result == 0 for result in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
