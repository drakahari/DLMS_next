"""Byte-bound Mac notices and corresponding-source companion preparation.

Public files only; no Git history, installed profiles, credentials or binaries
are exported as application source. Source archives remain inert.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
BASE='717dd01a5efa9c6cbc8f95f463e70714ec198597'
SHARED={
 'DLMS-Desktop-3.3.0-preview1-source-python.tar.zst':'40d78ccaad2cb0aadcca96f7f9cfeff06cba11e2de794ec45146954190b141f1',
 'DLMS-Desktop-3.3.0-preview1-source-qt-pyside.tar':'2d5f30392243200188b7df70563ba9d40e9847d695c979f628e38543d9d6ff73',
}
NOTICES_SHA='47f1164a762cb4336ad3f8fa69e3914f6d04547b058b0193b50c3ec929d0e03c'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def files(root):
    root=Path(root)
    for path in sorted(root.rglob('*')):
        if path.is_symlink(): raise ValueError('Material aliases refused')
        if path.is_file(): yield path
        elif not path.is_dir(): raise ValueError('Nonregular recipient material')


def _member(name):
    path=Path(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name:
        raise ValueError('Unsafe source/notice member')
    return path


def prepare(stage, inputs, cache):
    """Require native-source completion and collect exact notice/source bindings."""
    native=cache/'sources/native'
    index=json.loads((native/'NATIVE_SOURCES.json').read_text())
    if index.get('complete') is not True or index.get('unresolved')!=[]:
        raise ValueError('Mac native source material unresolved: '+repr(index.get('unresolved')))
    for producer in index['producers']:
        source=producer['source']
        if digest(native/_member(source['file']))!=source['sha256']:
            raise ValueError('Native source changed: '+producer['name'])
        if digest(native/_member(producer['formula']))!=producer['formula_sha256']:
            raise ValueError('Native producer formula changed')
        for patch in producer.get('patches',[]):
            if digest(native/_member(patch['file']))!=patch['sha256']:
                raise ValueError('Native producer patch changed')
    model=index['english_model']
    if digest(native/_member(model['file']))!=model['sha256']:
        raise ValueError('Exact English OCR model changed')
    wheel_native=cache/'sources/wheel-native'
    wheel_index=json.loads((wheel_native/'WHEEL_NATIVE_SOURCES.json').read_text())
    if wheel_index.get('complete') is not True or wheel_index.get('unresolved')!=[]:
        raise ValueError('Mac wheel-native source material unresolved')
    for source in wheel_index['sources']:
        if digest(wheel_native/_member(source['file']))!=source['sha256']:
            raise ValueError('Wheel-native corresponding source changed')
    notices=stage/'notices';notices.mkdir()
    sources=[]
    for name,sha in SHARED.items():
        source=cache/'sources/shared'/name
        if digest(source)!=sha: raise ValueError('Shared source companion changed')
        sources.append({'file':name,'bytes':source.stat().st_size,'sha256':sha,
                        'role':'Unmodified verified public Qt/Python source companion; Mac differences indexed separately'})
    source_notices=cache/'sources/shared/DLMS-Desktop-3.3.0-preview1-notices.tar.zst'
    if digest(source_notices)!=NOTICES_SHA:
        raise ValueError('Published upstream notice companion changed')
    # Only reusable upstream license texts; never Linux binary/source mappings.
    prefixes=('distribution-kit/upstream-texts/Qt-6.11.2/',
              'distribution-kit/upstream-texts/PySide-Shiboken-6.11.2/',
              'distribution-kit/upstream-texts/Chromium-source-metadata/',
              'distribution-kit/common-licenses/')
    with tarfile.open(source_notices) as archive:
        for item in archive:
            if item.isfile() and item.name.startswith(prefixes):
                relative=_member(item.name).relative_to('distribution-kit')
                target=notices/relative
                target.parent.mkdir(parents=True,exist_ok=True)
                with archive.extractfile(item) as stream: target.write_bytes(stream.read())
    wheelhouse=Path(inputs['wheelhouse']); wheels=[]
    for name,sha in inputs['wheels'].items():
        wheel=wheelhouse/name
        if digest(wheel)!=sha: raise ValueError('Pinned Mac wheel changed: '+name)
        wheels.append({'file':name,'sha256':sha})
        with zipfile.ZipFile(wheel) as archive:
            for item in archive.namelist():
                leaf=Path(item).name.lower()
                if item.endswith('/') or not (re.search(r'license|copying|notice|copyright',leaf) or '/sboms/' in item
                        or leaf in ('metadata','wheel','sbom.json','sbom.spdx.json')): continue
                relative=_member(item)
                target=notices/'wheels'/name/relative
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(archive.read(item))
    # Exact native producer texts/recipes/patches; archives are separate companions.
    for path in files(native):
        if path.name.endswith(('.part','.tar.gz','.tar.xz','.tar.bz2','.tar.zst','.tgz','.zip','.traineddata')): continue
        target=notices/'native'/path.relative_to(native)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target)
    for path in files(wheel_native):
        if path.name.endswith(('.tar.gz','.tar.xz','.tar.bz2','.tar.zst','.tgz','.zip','.part')): continue
        target=notices/'wheel-native'/path.relative_to(wheel_native)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target)
    for name in ('LICENSE','desktop_assets/ICON_PROVENANCE.md'):
        shutil.copyfile(ROOT/name,notices/Path(name).name)
    for name in ('REDISTRIBUTION.md','BUILD_AND_REPLACEMENT.md','RELEASE_PROPOSAL.md'):
        shutil.copyfile(ROOT/'docs/macos-preview'/name,notices/name)
    exact={'format':1,'platform':'macos-arm64-preview','application_base':BASE,
           'wheels':wheels,'native_producers':index,'wheel_native':wheel_index,
           'shared_source_archives':sources,
           'scope':'Technical correspondence; not a claim of reproducible vendor binaries or legal certification',
           'excluded_mappings':['Linux ELF/Ubuntu/AppImage mappings','Windows PE/conda/Microsoft mappings'],
           'signing':'ad hoc only; no Developer ID or notarization',
           'selected_files':'Consent/origin/path/descriptor/hash safeguards retained; malicious same-user native process excluded from guarantee'}
    (notices/'EXACT_INPUTS.json').write_text(json.dumps(exact,sort_keys=True,indent=2)+'\n')
    (notices/'SOURCE_MATERIALS.json').write_text(json.dumps({'format':1,'application_base':BASE,
        'shared_archives':sources,'native_index':'native/NATIVE_SOURCES.json',
        'wheel_native_index':'wheel-native/WHEEL_NATIVE_SOURCES.json','unresolved':[]},indent=2)+'\n')
    manifest={p.relative_to(notices).as_posix():digest(p) for p in files(notices)}
    (notices/'MANIFEST.json').write_text(json.dumps({'format':1,'platform':'macos-arm64-preview','sha256':manifest},indent=2)+'\n')
    return notices,index


def verify(root):
    root=Path(root)
    value=json.loads((root/'MANIFEST.json').read_text())
    actual={p.relative_to(root).as_posix():digest(p) for p in files(root) if p!=root/'MANIFEST.json'}
    if value.get('platform')!='macos-arm64-preview' or value.get('sha256')!=actual:
        raise ValueError('Mac recipient materials differ from exact manifest')
    required={'REDISTRIBUTION.md','BUILD_AND_REPLACEMENT.md','RELEASE_PROPOSAL.md',
              'LICENSE','ICON_PROVENANCE.md','EXACT_INPUTS.json','SOURCE_MATERIALS.json',
              'native/NATIVE_SOURCES.json','wheel-native/WHEEL_NATIVE_SOURCES.json'}
    if not required<=actual.keys(): raise ValueError('Required Mac recipient materials missing')
    source=json.loads((root/'SOURCE_MATERIALS.json').read_text())
    if source.get('unresolved')!=[]: raise ValueError('Mac corresponding source unresolved')
    return value


def deliver_companions(stage,cache,delivery):
    """Export source and notices only after the artifact is qualified separately."""
    verify(stage/'notices')
    delivery=Path(delivery);delivery.mkdir(mode=0o700,parents=True,exist_ok=False)
    for name in SHARED: shutil.copyfile(cache/'sources/shared'/name,delivery/name)
    with tarfile.open(delivery/'DLMS-Desktop-3.3.0-macos-preview1-source-native.tar.zst','x:zst') as archive:
        native=cache/'sources/native'
        for path in files(native):
            if path.name.endswith('.part'): raise ValueError('Incomplete native source download')
            archive.add(path,arcname='native-sources/'+path.relative_to(native).as_posix(),recursive=False)
    with tarfile.open(delivery/'DLMS-Desktop-3.3.0-macos-preview1-source-wheel-native.tar.zst','x:zst') as archive:
        wheel_native=cache/'sources/wheel-native'
        for path in files(wheel_native):
            if path.name.endswith('.part'): raise ValueError('Incomplete wheel-native source download')
            archive.add(path,arcname='wheel-native-sources/'+path.relative_to(wheel_native).as_posix(),recursive=False)
    with tarfile.open(delivery/'DLMS-Desktop-3.3.0-macos-preview1-notices.tar.zst','x:zst') as archive:
        for path in files(stage/'notices'):
            archive.add(path,arcname='notices/'+path.relative_to(stage/'notices').as_posix(),recursive=False)
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    untracked=subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
    selected=sorted(set(p for p in tracked+untracked if p))
    source_manifest={}
    with tarfile.open(delivery/'DLMS-Desktop-3.3.0-macos-preview1-source-application.tar.zst','x:zst') as archive:
        for name in selected:
            relative=_member(name)
            if relative.parts[0] in ('.git','.gate1','.venv','dist','build','profiles','backups'):
                raise ValueError('Private/build path in source export')
            path=ROOT/relative
            if path.is_symlink() or not path.is_file(): raise ValueError('Nonregular source input')
            source_manifest[name]=digest(path)
            archive.add(path,arcname='DLMS-source/'+name,recursive=False)
    (delivery/'APPLICATION_SOURCE_MANIFEST.json').write_text(json.dumps(source_manifest,sort_keys=True,indent=2)+'\n')
    return delivery
