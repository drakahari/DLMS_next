"""Bounded synthetic Darwin publication visibility probe; never change flags.

Creates new files under a fresh visible Documents/Downloads child, optionally
with a new /private/tmp control. Samples inode flags/ctime for <=15 seconds.
No existing output is replaced, removed, or changed; all evidence is retained.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import pwd
import stat
import sys
import tempfile
import time

PAYLOAD = b'DLMS synthetic publication visibility probe\n' * 1024
RENAME_EXCL = 0x00000004  # Native SDK sys/stdio.h: refuse existing destination.


def identity(path):
    info = path.lstat()
    return {'path': str(path), 'inode': info.st_ino, 'dev': info.st_dev,
            'bytes': info.st_size, 'flags': info.st_flags, 'flags_hex': hex(info.st_flags),
            'hidden': bool(info.st_flags & stat.UF_HIDDEN), 'links': info.st_nlink,
            'ctime_ns': info.st_ctime_ns, 'mtime_ns': info.st_mtime_ns}


def create(path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        view = memoryview(PAYLOAD)
        while view:
            written = os.write(fd, view)
            if not written: raise OSError('Write made no progress')
            view = view[written:]
        os.fsync(fd)
    finally: os.close(fd)


def setup(root):
    cases = []
    library = ctypes.CDLL(None, use_errno=True)
    rename = library.renamex_np
    rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    for name, method, dot in (
        ('dot-hardlink', 'link', True), ('plain-hardlink', 'link', False),
        ('direct-exclusive', 'direct', False),
        ('dot-exclusive-rename', 'rename', True), ('plain-exclusive-rename', 'rename', False),
    ):
        final = root/(name+' visible output.txt')
        source = root/(('.' if dot else '')+name+' staging.part')
        entry = {'name': name, 'method': method, 'source_dot_prefix': dot, 'final': str(final)}
        if method == 'direct': create(final)
        else:
            create(source)
            entry['source_before'] = identity(source)
            if method == 'link':
                os.link(source, final, follow_symlinks=False)
                source.unlink()  # Exact task-created staging inode/name only.
            elif rename(os.fsencode(source), os.fsencode(final), RENAME_EXCL):
                code = ctypes.get_errno(); raise OSError(code, os.strerror(code))
        entry['published'] = identity(final)
        cases.append(entry)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try: os.fsync(directory)
    finally: os.close(directory)
    return cases


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=12, choices=range(8, 16))
    parser.add_argument('--control-temp', action='store_true')
    args = parser.parse_args(argv)
    if sys.platform != 'darwin': parser.error('Darwin-only probe')
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    if (not args.parent.is_absolute() or '..' in args.parent.parts
            or any(p.is_symlink() for p in (args.parent, *args.parent.parents))
            or not args.parent.is_dir()
            or not any(args.parent.is_relative_to(home/name) for name in ('Documents', 'Downloads'))):
        parser.error('Use an existing ordinary Documents/Downloads fixture folder without symlinks')
    roots = [Path(tempfile.mkdtemp(prefix='DLMS publication visibility ', dir=args.parent))]
    if args.control_temp: roots.append(Path(tempfile.mkdtemp(prefix='dlms-publication-control-', dir='/private/tmp')))
    report = {'synthetic_only': True, 'seconds': args.seconds, 'flag_or_xattr_changes': False,
              'existing_data_changes': False, 'payload_sha256': hashlib.sha256(PAYLOAD).hexdigest(),
              'roots': [{'path': str(root), 'directory_before': identity(root), 'cases': setup(root)} for root in roots],
              'samples': []}
    print(json.dumps({'created_roots': [str(root) for root in roots]}), flush=True)
    started = time.monotonic()
    for sample in range(args.seconds+1):
        sample_record = {'elapsed': round(time.monotonic()-started, 3), 'files': []}
        for root_record in report['roots']:
            for case in root_record['cases']:
                value = identity(Path(case['final']))
                value['case'] = case['name']
                sample_record['files'].append(value)
        report['samples'].append(sample_record)
        print(json.dumps(sample_record), flush=True)
        if sample < args.seconds: time.sleep(1)
    for root_record in report['roots']:
        root_record['directory_after'] = identity(Path(root_record['path']))
        for case in root_record['cases']:
            output = Path(case['final'])
            case['final_state'] = identity(output)
            case['bytes_equal'] = output.read_bytes() == PAYLOAD
    output = roots[0]/'publication-visibility-evidence.json'
    with output.open('x') as stream: json.dump(report, stream, indent=2)
    print(json.dumps({'report': str(output), 'retained_all_evidence': True}), flush=True)
    return 0


if __name__ == '__main__': raise SystemExit(main())
