"""Generate checksum input for separate publisher signing. Never creates keys."""
from pathlib import Path
import argparse
import hashlib
import re


def checksum_manifest(files: list[Path]) -> bytes:
    names=set();lines=[]
    for path in sorted(files,key=lambda p:p.name):
        if path.is_symlink() or not path.is_file():raise ValueError('Release inputs must be regular files')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*',path.name) or path.name in names:raise ValueError('Unsafe or duplicate release filename')
        names.add(path.name);digest=hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
        lines.append(digest.hexdigest()+'  '+path.name+'\n')
    if not lines:raise ValueError('No release files')
    return ''.join(lines).encode('ascii')


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('files',nargs='+',type=Path);a=p.parse_args()
    raw=checksum_manifest(a.files)
    with a.output.open('xb') as stream:stream.write(raw)

if __name__=='__main__':main()
