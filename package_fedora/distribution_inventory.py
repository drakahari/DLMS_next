"""Audit an extracted private payload without running it or resolving network sources.

Every payload leaf and PYZ module receives explicit ownership evidence or an
unresolved classification. This is an inventory, not license clearance.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import re
import zipfile
import subprocess
from collections import defaultdict


def digest(path: Path) -> str:
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def payload_leaves(root: Path) -> list[dict]:
    root=root.resolve();leaves=[]
    for path in sorted(root.rglob('*')):
        rel=path.relative_to(root).as_posix()
        if path.is_symlink():
            if not path.resolve(strict=True).is_relative_to(root):raise ValueError(f'Escaping payload link: {rel}')
            leaves.append({'path':rel,'kind':'symlink','target':os.readlink(path)})
        elif path.is_file():leaves.append({'path':rel,'kind':'file','bytes':path.stat().st_size,'sha256':digest(path)})
        elif not path.is_dir():raise ValueError(f'Special payload leaf: {rel}')
    return leaves


def toc_records(value):
    if isinstance(value,(list,tuple)):
        if len(value)==3 and all(isinstance(x,str) for x in value) and value[2] in {'PYMODULE','BINARY','EXTENSION','DATA','SYMLINK'}:
            yield value
        else:
            for item in value:yield from toc_records(item)


def qt_part(path: str) -> str | None:
    match=re.search(r'(?:lib)?Qt6([A-Za-z0-9]+)\.so',path)
    if match:return match.group(1)
    match=re.search(r'/Qt([A-Za-z0-9]+)\.abi3\.so',path)
    if match:return match.group(1)
    if '/Qt/resources/' in path or '/qtwebengine_locales/' in path or path.endswith('/QtWebEngineProcess'):return 'WebEngine-resources'
    if '/Qt/plugins/' in path:return 'plugin:'+path.split('/Qt/plugins/',1)[1]
    if '/Qt/qml/' in path:return 'qml:'+path.split('/Qt/qml/',1)[1].split('/')[0]
    return None


def rpm_info(source: Path) -> dict | None:
    result=subprocess.run(['rpm','-qf','--qf','%{NAME}|%{VERSION}|%{RELEASE}|%{ARCH}|%{SOURCERPM}|%{URL}|%{LICENSE}\n',str(source)],capture_output=True,text=True)
    if result.returncode:return None
    fields=result.stdout.strip().splitlines()[0].split('|')
    if len(fields)!=7:return None
    name,version,release,arch,srpm,url,license_=fields
    return {'name':name,'version':version,'release':release,'arch':arch,'source_rpm':srpm,'upstream_url':url,'package_license_expression':license_,'license_limit':'RPM expression covers package, not necessarily each shipped file'}


def project_component(source: Path, rel: str, project: Path):
    """Distinguish application/owner MIT grants from third-party components.

    Root relocation must not turn every repository file into captured MIT code.
    This is provenance classification, not a license clearance decision.
    """
    resolved = source.resolve()
    if not resolved.is_relative_to(project):
        return None
    name = resolved.relative_to(project).as_posix()
    if name in {'tools/run_consolidation_checks.py', 'tools/prepare_public_snapshot.py'} or name.startswith('tools/macos_') or name.split('/')[0] in {'desktop', 'desktop_assets', 'package_fedora',
            'package_linux', 'package_appimage', 'package_windows',
            'package_windows_webview2', 'package_macos', 'windows_webview2'}:
        return 'application:desktop', {'kind': 'Desktop additions', 'name': 'DLMS Desktop',
            'version': None, 'origin': 'Exact frozen build-info.json and source hashes',
            'license_expression': 'MIT', 'license_scope': 'Owner-authored portions; retain third-party terms',
            'origin_license': 'docs/desktop-license.md; Copyright (c) 2026 Mike Buchanan'}
    if rel.startswith('_internal/static/help_assets/'):
        return 'asset:help-images', {'kind': 'captured illustrations', 'name': 'Help screenshots/illustrations',
            'version': 'captured e0510eb', 'origin': 'one-time source acquisition; per-image authorship not separately established',
            'license_expression': 'MIT (source-wide statement)', 'unresolved': 'Third-party depicted/content rights require asset review'}
    if name in {'app.py', 'init.sql', 'LICENSE'} or name.split('/')[0] in {'dlms', 'static', 'templates', 'tools'}:
        version = None
        for node in ast.parse((project / 'app.py').read_text(encoding='utf-8')).body:
            if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'APP_VERSION' for t in node.targets)
                    and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
                version = node.value.value
        return 'application:canonical', {'kind': 'application source/assets', 'name': 'canonical DLMS application',
            'version': version, 'origin': 'Root application tree; exact source and frozen module hashes',
            'license_expression': 'MIT'}
    return None


def audit(payload: Path,analysis: Path,pyz: Path,project: Path) -> dict:
    from PyInstaller.loader.pyimod01_archive import ZlibArchiveReader
    payload=payload.resolve();project=project.resolve();leaves=payload_leaves(payload)
    toc=list(toc_records(ast.literal_eval(analysis.read_text())))
    sources={};pure={}
    for name,source,kind in toc:
        if kind=='PYMODULE':pure[name]=Path(source)
        elif kind!='SYMLINK':sources['_internal/'+name]=Path(source)
    owners={};dists={}
    for dist in metadata.distributions():
        name=dist.metadata.get('Name');version=dist.version
        if not name:continue
        key='python:'+name.lower().replace('_','-')
        if key in dists:continue
        dists[key]={'id':key,'kind':'Python distribution','name':name,'version':version,'origin':'https://pypi.org/project/'+name+'/'+version+'/', 'license_expression':dist.metadata.get('License-Expression'),'project_urls':dist.metadata.get_all('Project-URL') or [],'files':[],'modules':[]}
        for f in dist.files or ():owners[Path(dist.locate_file(f)).resolve()]=key
    # Embedded vendored distributions have their own versions/licenses;
    # their parent's metadata is not a substitute for these identities.
    for parent in list(dists.values()):
        dist=metadata.distribution(parent['name'])
        vendor=Path(dist.locate_file(parent['name'].lower().replace('-','_')))/'_vendor'
        if not vendor.is_dir():continue
        for inner in metadata.distributions(path=[str(vendor)]):
            name=inner.metadata.get('Name');key='vendored:'+parent['name'].lower()+':'+name.lower().replace('_','-')
            dists[key]={'id':key,'kind':'vendored Python distribution','name':name,'version':inner.version,'parent_distribution':parent['name'],'origin':'https://pypi.org/project/'+name+'/'+inner.version+'/', 'license_expression':inner.metadata.get('License-Expression'),'files':[],'modules':[]}
            for f in inner.files or ():owners[Path(inner.locate_file(f)).resolve()]=key
    components={};rpm_cache={};unresolved=[]
    copied_ocr={'_internal/ocr/tesseract/bin/tesseract':Path('/usr/bin/tesseract'),
                '_internal/ocr/tesseract/bin/ld.so':Path('/usr/lib64/ld-linux-x86-64.so.2'),
                '_internal/ocr/tesseract/tessdata/eng.traineddata':Path('/usr/share/tesseract/tessdata/eng.traineddata')}
    def classify(source: Path | None,rel: str):
        if rel.startswith('_internal/static/vendor/'):
            return 'asset:sortablejs',{'kind':'third-party JavaScript','name':'SortableJS','version':'1.15.0','origin':'captured static/vendor; MIT text shipped','license_expression':'MIT'}
        if rel.startswith('_internal/desktop_assets/') and ('icon' in rel or rel.endswith('dlms_omarchy.png')):
            return 'asset:owner-icon',{'kind':'artwork','name':'original geometric DLMS badge','version':'1','origin':'desktop_assets/ICON_PROVENANCE.md; original grid lettering, no imported artwork/font','license_expression':'MIT'}
        if rel in copied_ocr and copied_ocr[rel].is_file() and digest(payload/rel)==digest(copied_ocr[rel]):
            info=rpm_info(copied_ocr[rel])
            if info:return 'rpm:'+info['name']+'@'+info['version']+'-'+info['release'],dict(kind='Fedora OCR input',**info)
        known={'_internal/PySide6/Qt/libexec/qt.conf':'generated PyInstaller Qt configuration',
               '_internal/desktop_assets/build-info.json':'generated build identity',
               '_internal/notices/available-build-texts/INVENTORY.json':'generated available-text inventory'}
        if rel in known:
            return 'generated:packaging',{'kind':'generated packaging data','name':'build-generated metadata','version':'RC1','origin':known[rel],'license_expression':None}
        if rel=='_internal/notices/available-build-texts/native/CPython/LICENSE':
            return 'notice:cpython',{'kind':'license text','name':'CPython','version':'3.14.7','origin':'verified official CPython source LICENSE','license_expression':'Python-2.0.1'}
        if rel=='_internal/notices/available-build-texts/native/zstd/LICENSE':
            return 'notice:zstd',{'kind':'license text','name':'zstd','version':'1.5.7','origin':'verified native RPM notice input','license_expression':'BSD-3-Clause OR GPL-2.0-only'}
        qpart=qt_part(rel)
        if qpart:
            key='qt:'+qpart
            return key,{'kind':'Qt component/plugin/resource','name':qpart,'version':'6.11.2','chromium_version':'140.0.7339.225' if 'WebEngine' in qpart else None,'origin':'PySide6 6.11.2 wheel RECORD and exact build TOC','license_expression':None,'unresolved':'Module/native third-party license/source selection; see obligations ledger'}
        # Notice paths carry their distribution attribution even though copied
        # from a collected notice directory rather than directly from RECORD.
        prefix='_internal/notices/available-build-texts/wheels/'
        if rel.startswith(prefix):
            name=rel[len(prefix):].split('/')[0];key='python:'+name.lower().replace('_','-')
            if key in dists:return key,dists[key]
        if source:
            resolved=source.resolve()
            if resolved in owners:return owners[resolved],dists[owners[resolved]]
            component = project_component(resolved, rel, project)
            if component:
                return component
            if not resolved.is_relative_to(project):
                if resolved not in rpm_cache:rpm_cache[resolved]=rpm_info(resolved)
                info=rpm_cache[resolved]
                if info:
                    key='rpm:'+info['name']+'@'+info['version']+'-'+info['release']
                    return key,dict(kind='Fedora native/runtime input',**info)
            if 'ocr-bundle' in str(source):
                return 'ocr:bundle',{'kind':'OCR executable/data','name':'Tesseract/tessdata bundle','version':None,'origin':'verified existing bundle hashes; exact individual origins require mapping','license_expression':None,'unresolved':'Bundle executable/loader/language data source correspondence'}
        if rel=='DLMS-Desktop' or rel.endswith('/base_library.zip') or rel=='Install-DLMS-Desktop':
            return 'container:runtime',{'kind':'frozen container/launcher','name':'CPython/PyInstaller and application container','version':'Python 3.14.7 / PyInstaller 6.22.2','origin':'verified embedded executable/PYZ and base_library inputs','license_expression':None}
        return 'unresolved:payload',{'kind':'unresolved input','name':'unclassified payload input','version':None,'origin':'exact file hash recorded','unresolved':'No trustworthy source ownership mapping found'}
    def attach(key,info,field,record):
        if key not in components:components[key]={**info,'id':key,'files':[],'modules':[]}
        components[key][field].append(record)
    for leaf in leaves:
        rel=leaf['path'];source=sources.get(rel)
        if leaf['kind']=='symlink':
            target=(payload/rel).resolve();source=sources.get(target.relative_to(payload).as_posix(),source)
        key,info=classify(source,rel)
        if source and source.resolve() in owners:leaf['wheel_owner']=owners[source.resolve()]
        if source and source.is_file() and leaf['kind']=='file':
            leaf['input_sha256']=digest(source)
            leaf['input_matches_payload']=leaf['input_sha256']==leaf['sha256']
        attach(key,info,'files',leaf)
        if key.startswith('unresolved:'):unresolved.append(rel)
    archive=ZlibArchiveReader(str(pyz))
    for name in sorted(archive.toc):
        raw=archive.extract(name,raw=True);source=pure.get(name)
        key,info=classify(source,'PYZ:'+name)
        if raw is None:
            parent=name
            while '.' in parent:
                parent=parent.rsplit('.',1)[0];candidate=pure.get(parent)
                if candidate and candidate.resolve() in owners:
                    key=owners[candidate.resolve()];info=dists[key];break
        record={'name':name,'embedded_sha256':hashlib.sha256(raw).hexdigest() if raw is not None else None,'source_sha256':digest(source) if source and source.is_file() else None,'container':'DLMS-Desktop:PYZ','source_kind':'exact analysis input' if source else 'namespace/no source input'}
        attach(key,info,'modules',record)
    for c in components.values():
        if c['id'].startswith(('python:','vendored:')):
            c['runtime_code_bundled']=bool(c['modules'] or any('/notices/' not in f['path'] for f in c['files']) or any(f.get('wheel_owner')==c['id'] for other in components.values() for f in other['files']))
            c['notice_only']=not c['runtime_code_bundled']
    build_only=[dict(v,files=[],modules=[],bundled=False) for k,v in dists.items() if k not in components or components[k].get('notice_only')]
    with zipfile.ZipFile(payload/'_internal/base_library.zip') as library:
        base_modules=[{'name':name,'sha256':hashlib.sha256(library.read(name)).hexdigest(),'component':'CPython 3.14.7 bundled base modules'} for name in library.namelist()]
    return {'base_library_modules':base_modules,'format':1,'audited_release':'fedora-rc1-20261013','payload_file_count':len(leaves),'embedded_module_count':len(archive.toc),'pyz_sha256':digest(pyz),'normal_executable_sha256':digest(payload/'DLMS-Desktop'),'coverage':'Every payload leaf and PYZ module listed; unresolved ownership is not a compliance pass','components':sorted(components.values(),key=lambda c:c['id']),'build_only_distributions':build_only,'unresolved_file_ownership':unresolved,'standalone_font_files':[x['path'] for x in leaves if x['path'].lower().endswith(('.ttf','.otf','.woff','.woff2'))]}


def main():
    p=argparse.ArgumentParser();p.add_argument('--payload',type=Path,required=True);p.add_argument('--analysis',type=Path,required=True);p.add_argument('--pyz',type=Path,required=True);p.add_argument('--project',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('Preserve the existing inventory')
    result=audit(a.payload,a.analysis,a.pyz,a.project)
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'components':len(result['components']),'files':result['payload_file_count'],'modules':result['embedded_module_count'],'unresolved_file_ownership':len(result['unresolved_file_ownership'])}))

if __name__=='__main__':main()
