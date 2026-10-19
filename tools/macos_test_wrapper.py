"""Task-only wrapper staging and fail-closed opening; no installed changes.

Never strips quarantine. Originals are inventoried read-only. Only fresh output
may have confirmed FinderInfo/ResourceFork removed, before signing. A Documents
copy must pass the same gate; otherwise use the untouched private staged wrapper.
The native wrapper also verifies itself and its pinned payload before opening.
Same-user malicious replacement during verification is outside this test tool's
guarantee; this is not a production trust/signing mechanism.
"""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROHIBITED = ('com.apple.FinderInfo', 'com.apple.ResourceFork')

# CPython's macOS build does not expose os.*xattr. Use Darwin's no-follow API.
def _xattr(name, path, attribute=None, value=None):
    libc = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
    f = getattr(libc, name); f.restype = ctypes.c_ssize_t
    p = os.fsencode(path); a = attribute.encode() if attribute is not None else None
    if name == 'removexattr':
        result = f(p, a, ctypes.c_int(1))
    elif name == 'setxattr':
        result = f(p, a, value, ctypes.c_size_t(len(value)), ctypes.c_uint32(0), ctypes.c_int(1))
    else:
        args = [p] + ([a] if a is not None else [])
        tail = ([ctypes.c_uint32(0)] if a is not None else []) + [ctypes.c_int(1)]
        size = f(*args, None, ctypes.c_size_t(0), *tail)
        if size < 0: raise OSError(ctypes.get_errno(), name, str(path))
        buffer = ctypes.create_string_buffer(size)
        result = f(*args, buffer, ctypes.c_size_t(size), *tail)
        if result >= 0: return buffer.raw[:result]
    if result < 0: raise OSError(ctypes.get_errno(), name, str(path))


def set_attribute(path, name, value): return _xattr('setxattr', path, name, value)
def get_attribute(path, name): return _xattr('getxattr', path, name)
def remove_attribute(path, name): return _xattr('removexattr', path, name)


def run(args):
    return subprocess.run([str(x) for x in args], check=True)


def inventory(root):
    root = Path(root)
    result = {}
    for p in [root, *sorted(root.rglob('*'))]:
        s = p.lstat(); entry = {'mode': stat.S_IMODE(s.st_mode)}
        if p.is_symlink(): entry['symlink'] = os.readlink(p)
        elif p.is_file():
            with p.open('rb') as f: entry['sha256'] = hashlib.file_digest(f, 'sha256').hexdigest()
        elif p.is_dir(): entry['directory'] = True
        else: raise ValueError('Special file refused: ' + str(p))
        result[str(p.relative_to(root)) if p != root else ''] = entry
    return result


def metadata(root):
    root = Path(root)
    return {str(p.relative_to(root)) if p != root else '':
            {name: get_attribute(p, name).hex()
             for name in _xattr('listxattr', p).decode().split('\0') if name}
            for p in [root, *sorted(root.rglob('*'))]}


def ordinary(path, directory=True):
    path = Path(path)
    if not path.is_absolute(): raise ValueError('Absolute paths required')
    for p in [path, *path.parents]:
        if p.is_symlink(): raise ValueError('Path alias refused: ' + str(p))
    if not (path.is_dir() if directory else path.is_file()): raise ValueError('Wrong path type')
    return path


def verify(path):
    ordinary(path)
    run(['/usr/bin/codesign', '--verify', '--deep', '--strict', path])


def stage(app, data_root, profile, destination):
    app = ordinary(app); data_root = ordinary(data_root)
    destination = Path(destination)
    if not re.fullmatch(r'[a-z][a-z0-9]{0,31}', profile): raise ValueError('Unsafe profile')
    ordinary(destination.parent)
    if destination.exists() or destination.is_symlink(): raise FileExistsError(destination)
    # Executable staging must stay outside Documents/Downloads metadata providers.
    cache = Path.home()/'.cache'
    if not destination.is_relative_to(cache): raise ValueError('Use fresh private cache staging')
    s = data_root.stat()
    if s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) & 0o077: raise ValueError('Private owned root required')
    marker = ordinary(data_root/'.dlms-macos-preview.json', False)
    if json.loads(marker.read_text()) != {'kind':'dlms-desktop-macos-preview','version':1}: raise ValueError('Root marker differs')
    verify(app)
    before = inventory(app); attrs = metadata(app)
    destination.mkdir(mode=0o700)
    wrapper = destination/'Open DLMS Repair Candidate.app'
    resources = wrapper/'Contents/Resources'; resources.mkdir(parents=True)
    macos = wrapper/'Contents/MacOS'; macos.mkdir()
    with (app/'Contents/Info.plist').open('rb') as f: bundle_id = plistlib.load(f)['CFBundleIdentifier']
    config = dict(app=str(app), data_root=str(data_root), profile=profile,
                  bundle_identifier=bundle_id, payload_inventory=before)
    (resources/'Task.json').write_text(json.dumps(config, sort_keys=True)+'\n')
    # Bundled icon; never mutable Finder custom-icon metadata.
    shutil.copyfile(ROOT/'desktop_assets/icons/macos/DLMSDesktop.icns', resources/'DLMSDesktop.icns')
    info = dict(CFBundleExecutable='VerifiedLauncher', CFBundleIdentifier='io.github.drakahari.DLMSDesktop.TaskVerifiedLauncher',
                CFBundleName='Open DLMS Repair Candidate', CFBundlePackageType='APPL',
                CFBundleVersion='1', CFBundleIconFile='DLMSDesktop.icns', NSHighResolutionCapable=True)
    (wrapper/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    run(['/usr/bin/clang', '-arch', 'arm64', '-fobjc-arc', '-framework', 'AppKit',
         '-Wno-deprecated-declarations', ROOT/'tools/macos_verified_test_launcher.m',
         '-o', macos/'VerifiedLauncher'])
    pre = metadata(wrapper); removed = []
    for rel, values in pre.items():
        for attr in PROHIBITED:
            if attr in values:
                remove_attribute(wrapper/rel, attr)
                removed.append(dict(path=rel, attribute=attr, bytes_hex=values[attr]))
    post = metadata(wrapper)
    for rel, values in pre.items():
        assert {k:v for k,v in values.items() if k not in PROHIBITED} == post[rel]
    run(['/usr/bin/codesign', '--sign', '-', '--timestamp=none', wrapper])
    verify(wrapper)
    run([macos/'VerifiedLauncher', '--verify-only'])
    assert inventory(app) == before and metadata(app) == attrs, 'Payload changed'
    record = dict(wrapper=str(wrapper), app=str(app), data_root=str(data_root), profile=profile,
                  wrapper_inventory=inventory(wrapper), payload_inventory=before,
                  payload_metadata=attrs, wrapper_metadata=metadata(wrapper), removed=removed,
                  before_sign_metadata=pre)
    (destination/'VERIFIED_WRAPPER.json').write_text(json.dumps(record, indent=2)+'\n')
    return record


def checked_open(record, wrapper=None, *, opener=run, verifier=verify):
    wrapper = Path(wrapper or record['wrapper']); app = Path(record['app'])
    if inventory(wrapper) != record['wrapper_inventory']: raise ValueError('Wrapper inventory changed')
    if inventory(app) != record['payload_inventory']: raise ValueError('Payload inventory changed')
    config = json.loads((wrapper/'Contents/Resources/Task.json').read_text())
    if any(config[k] != record[k] for k in ('app','data_root','profile','payload_inventory')):
        raise ValueError('Wrapper does not pin the expected payload/root/profile')
    verifier(wrapper); verifier(app)
    # Both checked results and identities are required before the sole opener.
    return opener(['/usr/bin/open', str(wrapper)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('stage')
    for name in ('app', 'data-root', 'destination'): p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--profile', required=True)
    p = sub.add_parser('open'); p.add_argument('--record', type=Path, required=True)
    p.add_argument('--wrapper', type=Path)
    args = parser.parse_args()
    if sys.platform != 'darwin': raise SystemExit('Native macOS only')
    if args.command == 'stage':
        record = stage(args.app, args.data_root, args.profile, args.destination)
        print(json.dumps({'wrapper':record['wrapper'],'removed':record['removed']}, indent=2))
    else: checked_open(json.loads(args.record.read_text()), args.wrapper)


if __name__ == '__main__': main()
