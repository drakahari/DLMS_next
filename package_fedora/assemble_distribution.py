"""Assemble supplied technical notices; never declare legal clearance.

Source/version correspondence comes from the audit, not from this copy utility.
No symlinks, special files, overwritten outputs, or operational reports included.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil


def leaves(root):
    if root.is_symlink() or not root.is_dir():raise ValueError('Materials need a plain directory')
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):raise ValueError('Materials cannot contain symlinks/special files')
        if path.is_file():yield path


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(1024*1024):h.update(block)
    return h.hexdigest()


def verify_materials(root):
    data=json.loads((root/'MANIFEST.json').read_text())
    historical = data.get('format') == 1 and data.get('status') == 'Private technical materials; public redistribution not cleared'
    preview = data.get('format') == 2 and data.get('status') == 'Linux preview redistribution materials; not legal certification'
    if not (historical or preview):raise ValueError('Unsupported materials manifest')
    rows={p.relative_to(root).as_posix():digest(p) for p in leaves(root) if p.name!='MANIFEST.json' or p.parent!=root}
    if rows!=data['sha256']:raise ValueError('Distribution texts differ from manifest')
    if preview:
        required = {'REDISTRIBUTION.md', 'BUILD_AND_REPLACEMENT.md', 'SOURCE_MATERIALS.json'}
        if not required.issubset(rows):raise ValueError('Preview source/build instructions are missing')
        sources=json.loads((root/'SOURCE_MATERIALS.json').read_text())
        if not sources.get('archives') or sources.get('unresolved') != []:
            raise ValueError('Preview corresponding-source materials are unresolved')
    return data


def assemble(output,inputs,*,preview=False):
    output=output.absolute()
    if '..' in output.parts:raise ValueError('Parent traversal in output')
    if output.exists() or output.is_symlink():raise FileExistsError('Materials output exists; preserve it')
    for part in (output,*output.parents):
        if part.is_symlink():raise ValueError('Output has a symlink parent')
    groups=set()
    for name,source in inputs:
        if not name or name in ('.','..') or '/' in name or '\\' in name:raise ValueError('Unsafe materials group')
        if name in groups or name=='MANIFEST.json':raise ValueError('Duplicate or reserved materials group')
        groups.add(name)
        source=source.absolute()
        if '..' in source.parts:raise ValueError('Parent traversal in source')
        for part in (source,*source.parents):
            if part.is_symlink():raise ValueError('Source has a symlink parent')
        if source.is_dir() and (output.is_relative_to(source) or source.is_relative_to(output)):raise ValueError('Source and output trees must be separate')
        if source.is_dir():
            list(leaves(source))
        else:
            if source.is_symlink() or not source.is_file():raise ValueError('Materials need regular input files')
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    for name,source in inputs:
        if source.is_dir():shutil.copytree(source,output/name)
        else:
            shutil.copyfile(source,output/name)
    manifest={'format':1,'status':'Private technical materials; public redistribution not cleared',
              'sha256':{p.relative_to(output).as_posix():digest(p) for p in leaves(output)}}
    if preview:
        manifest.update(format=2,status='Linux preview redistribution materials; not legal certification')
    (output/'MANIFEST.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    verify_materials(output)
    return manifest


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path)
    p.add_argument('--linux-preview',action='store_true',help='Require completed source index and recipient build/replacement instructions; not legal certification')
    p.add_argument('--input',action='append',required=True,help='group=regular-file-or-directory')
    a=p.parse_args();assemble(a.output,[(v.split('=',1)[0],Path(v.split('=',1)[1])) for v in a.input],preview=a.linux_preview)

if __name__=='__main__':main()
