"""Recreate only this candidate's environment offline, preserving the old one.

Documents FileProvider can mark dependency plugins UF_HIDDEN, which Qt excludes
from discovery. Keep the actual environment and its launcher pointer in the
task's private cache, without a project virtualenv symlink. Never clear flags,
remove quarantine, download packages, or change global Python installations.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def safe_directory(path):
    if path.is_symlink() or (path.exists() and (not path.is_dir()
            or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o022)):
        raise ValueError('Unsafe task directory: ' + str(path))


def main():
    if sys.platform != 'darwin' or platform.machine() != 'arm64' or sys.version_info[:3] != (3, 14, 7):
        raise SystemExit('Use native arm64 Python 3.14.7 on this Mac.')
    from desktop.macos_paths import real_home
    evidence = ROOT / '.gate1/macos'
    wheelhouse = evidence / 'wheelhouse'
    for path in (ROOT / '.gate1', evidence, wheelhouse):
        safe_directory(path)
    download = json.loads((evidence / 'wheelhouse.json').read_text())
    if hashlib.sha256((ROOT / 'package_macos/requirements-lock.txt').read_bytes()).hexdigest() != download['lock_sha256']:
        raise ValueError('Download request lock changed; do not resolve new dependencies silently.')
    if set(download['wheels']) != {p.name for p in wheelhouse.iterdir()}:
        raise ValueError('Wheelhouse contents differ from the download inventory.')
    for name, expected in download['wheels'].items():
        path = wheelhouse / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Downloaded wheel changed: ' + name)
    cache = real_home() / '.cache/dlms-desktop-macos-candidate'
    environments = cache / 'environments'
    for path in (cache.parent, cache, environments):
        safe_directory(path)
        path.mkdir(mode=0o700, exist_ok=True)
    pointer = cache / 'ENVIRONMENT.json'
    if os.path.lexists(pointer):
        raise ValueError('A task environment pointer already exists; inspect it before another setup.')
    link = ROOT / '.venv'
    if link.is_symlink():
        raise ValueError('Project .venv is already a symlink; inspect it before creating another environment.')
    safe_directory(link)
    if not (link / 'pyvenv.cfg').is_file():
        raise ValueError('Expected task-created project environment is missing; nothing moved.')
    destination = Path(tempfile.mkdtemp(prefix='py314-arm64-', dir=environments))
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('PYTHON', 'QT_', 'QTWEBENGINE_', 'DYLD_'))}
    base = Path('/opt/homebrew/bin/python3.14')
    log = evidence / (destination.name + '-environment.log')
    with log.open('x') as output:
        commands = [
            [str(base), '-m', 'venv', str(destination)],
            [str(destination / 'bin/python'), '-m', 'pip', '--isolated', '--disable-pip-version-check',
             'install', '--no-index', '--no-cache-dir', '--find-links', str(wheelhouse),
             '-r', str(ROOT / 'package_macos/requirements-resolved.txt')],
            [str(destination / 'bin/python'), '-m', 'pip', 'check'],
        ]
        for command in commands:
            subprocess.run(command, env=environment, stdout=output, stderr=subprocess.STDOUT, check=True)
        # Test discovery before changing the established project link. Failure
        # leaves both the original environment and new failure evidence intact.
        smoke = '''from PySide6.QtCore import QDir, QLibraryInfo
from PySide6.QtWidgets import QApplication
from pathlib import Path
p=QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)+'/platforms'
assert 'libqoffscreen.dylib' in QDir(p).entryList(), 'Qt cannot discover its platform plugins'
app=QApplication(['dlms-environment-check'])
assert app.platformName()=='offscreen'
print('Qt offscreen discovery and initialization passed:',p)
'''
        subprocess.run([str(destination / 'bin/python'), '-c', smoke], env=dict(environment, QT_QPA_PLATFORM='offscreen'),
                       stdout=output, stderr=subprocess.STDOUT, check=True)
    preserved = evidence / 'preserved-environments'
    safe_directory(preserved)
    preserved.mkdir(mode=0o700, exist_ok=True)
    old = preserved / ('documents-' + destination.name)
    if old.exists():
        raise FileExistsError('Preserve the earlier environment archive.')
    link.rename(old)
    record = {'environment': str(destination), 'project_link': None,
              'repository': str(ROOT),
              'download_inventory_sha256': hashlib.sha256((evidence / 'wheelhouse.json').read_bytes()).hexdigest(),
              'preserved_environment': str(old), 'log': str(log),
              'offline': True, 'global_installs': False, 'security_changes': False}
    with pointer.open('x') as output:
        json.dump(record, output, indent=2)
        output.write('\n')
    with (evidence / (destination.name + '-environment.json')).open('x') as output:
        json.dump(record, output, indent=2)
        output.write('\n')
    print(json.dumps(record, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
