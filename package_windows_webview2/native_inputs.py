"""Bind preview root DLLs to existing reviewed Windows producer archives.

Avoid PyInstaller discovering Qt's dynamic OpenSSL on PATH or the host UCRT.
Read exact members; never execute producer scripts.
"""
import hashlib
import json
from pathlib import Path
import tarfile
import zipfile

MEMBERS = {
    'openssl': ('Library/bin/libcrypto-3-x64.dll', 'Library/bin/libssl-3-x64.dll'),
    'ucrt': ('Library/bin/ucrtbase.dll',),
}


def materialize(cache, destination, lock):
    from compression.zstd import ZstdFile  # verified Windows CPython3.14 build
    pins = json.loads(Path(lock).read_text())['packages']
    destination = Path(destination)
    destination.mkdir(exist_ok=False)
    records = []
    for package, members in MEMBERS.items():
        matches = [item for item in pins if item['name'] == package]
        if len(matches) != 1:
            raise ValueError('Ambiguous pinned native package: ' + package)
        pin = matches[0]
        archive = Path(cache) / pin['url'].rsplit('/', 1)[-1]
        with archive.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != pin['sha256']:
            raise ValueError('Pinned native archive digest differs: ' + package)
        found = set()
        with zipfile.ZipFile(archive) as container:
            payloads = [name for name in container.namelist()
                        if name.startswith('pkg-') and name.endswith('.tar.zst')]
            if len(payloads) != 1:
                raise ValueError('Ambiguous native package payload: ' + package)
            with container.open(payloads[0]) as compressed, ZstdFile(compressed) as raw:
                with tarfile.open(fileobj=raw, mode='r|') as payload:
                    for item in payload:
                        if item.name not in members:
                            continue
                        if (item.name in found or not item.isfile()
                                or not 0 < item.size <= 32 * 1024 * 1024):
                            raise ValueError('Invalid native package member: ' + item.name)
                        found.add(item.name)
                        with payload.extractfile(item) as stream:
                            data = stream.read(item.size + 1)
                        if len(data) != item.size:
                            raise ValueError('Truncated native package member')
                        target = destination / Path(item.name).name
                        with target.open('xb') as stream:
                            stream.write(data)
                        records.append({'file': target.name, 'sha256': hashlib.sha256(data).hexdigest(),
                                        'package': archive.name, 'archive_sha256': digest, 'member': item.name})
        if found != set(members):
            raise ValueError('Missing pinned native package members: ' + package)
    return records


def verify_collected(rows, root, records):
    """Refuse a fallback to an ambient same-name DLL after freezer analysis."""
    root = Path(root)
    for record in records:
        matches = [row for row in rows if row[0].replace('\\', '/') == record['file']]
        if len(matches) != 1 or Path(matches[0][1]).resolve() != (root / record['file']).resolve():
            raise ValueError('Unpinned root DLL selected: ' + record['file'])
        if hashlib.sha256(Path(matches[0][1]).read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Pinned root DLL bytes changed: ' + record['file'])
