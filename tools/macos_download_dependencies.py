"""Download this candidate's wheels only; never install or run downloaded code."""
from pathlib import Path
import hashlib
import json
import platform
import subprocess
import sys
import os


def main():
    if sys.platform != 'darwin' or platform.machine() != 'arm64' or sys.version_info[:3] != (3, 14, 7):
        raise SystemExit('Use native arm64 Python 3.14.7 on this Mac.')
    root = Path(__file__).resolve().parents[1]
    lock = root / 'package_macos/requirements-lock.txt'
    target = root / '.gate1/macos/wheelhouse'
    for part in (root / '.gate1', root / '.gate1/macos', target):
        if part.is_symlink() or (part.exists() and not part.is_dir()):
            raise SystemExit('Download path contains a symlink or non-directory.')
        if part.exists() and (part.stat().st_uid != os.getuid() or part.stat().st_mode & 0o022):
            raise SystemExit('Download path is writable by another user.')
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    if target.is_symlink() or any(target.iterdir()):
        raise SystemExit('Wheelhouse is populated or unsafe; preserve it and ask for inspection.')
    subprocess.run([sys.executable, '-m', 'pip', '--isolated', '--disable-pip-version-check',
                    'download', '--no-cache-dir', '--index-url', 'https://pypi.org/simple',
                    '--only-binary=:all:', '--retries', '0', '--timeout', '30',
                    '--dest', str(target), '-r', str(lock)], check=True)
    wheels = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(target.iterdir()) if p.suffix == '.whl'}
    if not wheels or len(wheels) != len(list(target.iterdir())):
        raise SystemExit('Unexpected download contents; do not install.')
    with (target.parent / 'wheelhouse.json').open('x') as inventory:
        inventory.write(json.dumps({
        'lock_sha256': hashlib.sha256(lock.read_bytes()).hexdigest(),
        'python': platform.python_version(), 'architecture': platform.machine(),
        'index': 'https://pypi.org/simple', 'wheels': wheels}, indent=2) + '\n')
    print('Downloaded wheels and SHA-256 inventory to', target)


if __name__ == '__main__':
    main()
