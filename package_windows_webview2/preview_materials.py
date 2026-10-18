"""Require a complete, byte-bound Windows recipient-material kit before freezing."""
import hashlib
import json
import re
from pathlib import Path


def verify(root):
    root = Path(root)
    if root.is_symlink() or getattr(root.lstat(), 'st_file_attributes', 0) & 0x400:
        raise ValueError('Material aliases are refused')
    data = json.loads((root / 'MANIFEST.json').read_text(encoding='utf-8'))
    if data.get('format') != 1 or data.get('platform') != 'windows-x86_64-preview':
        raise ValueError('Expected Windows preview materials')
    required = {'REDISTRIBUTION.md', 'BUILD_AND_REPLACEMENT.md', 'SOURCE_MATERIALS.json', 'EXACT_INPUTS.json'}
    actual = {}
    for path in root.rglob('*'):
        if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('Material aliases are refused')
        if path.is_file() and path != root / 'MANIFEST.json':
            actual[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != data['sha256'] or not required <= actual.keys():
        raise ValueError('Windows materials differ from their complete manifest')
    index = json.loads((root / 'SOURCE_MATERIALS.json').read_text())
    if index.get('unresolved') != [] or not index.get('archives'):
        raise ValueError('Windows corresponding-source materials are unresolved')
    names=set()
    for row in index['archives']:
        name=row.get('file')
        if (not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',name)
                or name in names or not re.fullmatch(r'[0-9a-f]{64}',row.get('sha256',''))
                or type(row.get('bytes')) is not int or row['bytes']<=0):
            raise ValueError('Invalid source companion binding')
        names.add(name)
    return data
