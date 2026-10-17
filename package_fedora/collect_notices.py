"""Collect available exact-build texts; presence is not redistribution clearance."""
import argparse
import hashlib
import importlib.metadata as md
import json
from pathlib import Path
import shutil


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    a.output.mkdir(mode=0o700,parents=True,exist_ok=False);records=[];seen=set()
    for dist in sorted(md.distributions(),key=lambda d:d.metadata.get('Name','')):
        name=dist.metadata.get('Name','unknown');found=[]
        key=(name.lower(),dist.version,str(Path(dist.locate_file('')).resolve()))
        if key in seen:continue
        seen.add(key)
        for item in dist.files or ():
            path=Path(item)
            if (not any(word in path.name.lower() for word in ('license','notice','copying'))
                    and not any(part.lower() in ('licenses','license') for part in path.parts)) or path.suffix in ('.py','.pyc'):continue
            source=Path(dist.locate_file(item))
            if not source.is_file() or source.is_symlink() or source.stat().st_size>4*1024*1024:continue
            # Exact distribution manifest supplies the source; never scan HOME.
            target=a.output/'wheels'/name/path
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,target)
            found.append({'path':target.relative_to(a.output).as_posix(),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
        records.append({'distribution':name,'version':dist.version,'license_expression':dist.metadata.get('License-Expression'),
                        'available_notice_files':found,'completeness':'not established'})
    known={'zstd':'/usr/share/licenses/zstd/LICENSE'}
    host=[]
    for name,path in known.items():
        source=Path(path)
        if source.is_file():
            target=a.output/'native'/name/'LICENSE';target.parent.mkdir(parents=True);shutil.copyfile(source,target)
            host.append({'component':name,'source':path,'path':target.relative_to(a.output).as_posix(),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
        else:host.append({'component':name,'source':path,'missing':True})
    python_license=Path(__file__).resolve().parent/'notices/CPython-3.14.7-LICENSE'
    expected='b0e25a78cffb43f4d92de8b61ccfa1f1f98ecbc22330b54b5251e7b6ba010231'
    if hashlib.sha256(python_license.read_bytes()).hexdigest()!=expected:raise ValueError('Verified CPython license input changed')
    target=a.output/'native/CPython/LICENSE';target.parent.mkdir(parents=True);shutil.copyfile(python_license,target)
    host.append({'component':'CPython','version':'3.14.7','source':'https://raw.githubusercontent.com/python/cpython/v3.14.7/LICENSE','path':target.relative_to(a.output).as_posix(),'sha256':expected,'retrieved':'2026-10-13'})
    result={'status':'Technical private-candidate inventory, not legal clearance','wheel_texts':records,'host_runtime_texts':host,
            'unresolved':['Exact Qt/WebEngine/Chromium third-party completeness and module license suitability',
                          'LGPL source/relinking and installation-information obligations',
                          'All OCR/PDFium/native transitive notice and source obligations',
                          'Captured theme/icon/other assets attribution review',
                          'Qualified legal review before public distribution']}
    (a.output/'INVENTORY.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'distributions':len(records),'available_texts':sum(len(x['available_notice_files']) for x in records),'host_texts':host},indent=2))

if __name__=='__main__':main()
