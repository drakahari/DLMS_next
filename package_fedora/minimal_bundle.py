"""Narrow opt-in exclusions for unused GPL Qt families and optional Readline.

Packaging only. Keep Qt Quick/QML native dependencies of WebEngine, Wayland
client integration and all OCR/PDF dependencies. Refuse unexpected consumers.
"""
from pathlib import Path, PurePosixPath
import json
import re
import subprocess
import posixpath

FAMILIES=('Charts','DataVisualization','Graphs','Quick3D','QuickTimeline','VirtualKeyboard','WaylandCompositor')
OPTIONAL_PLUGINS={
    'PySide6/Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so',
    'PySide6/Qt/plugins/qmltooling/libqmldbg_quick3dprofiler.so',
}
QML={'Charts':('QtCharts',),'DataVisualization':('QtDataVisualization',),
     'Graphs':('QtGraphs','QtGraphs3D'),'Quick3D':('QtQuick3D',),
     'QuickTimeline':('QtQuick/Timeline',),'VirtualKeyboard':('QtQuick/VirtualKeyboard',),
     'WaylandCompositor':('QtWayland/Compositor',)}


def exclusion(path):
    p=PurePosixPath(path);parts=p.parts
    if path.startswith('_internal/'):path=path[len('_internal/'):];p=PurePosixPath(path)
    if path.startswith('PySide6/Qt/qml/'):
        rest=path[len('PySide6/Qt/qml/'):]
        for family,roots in QML.items():
            if any(rest==root or rest.startswith(root+'/') for root in roots):return family+' unused QML resource/plugin'
    if path.startswith('PySide6/Qt/lib/'):
        for family in FAMILIES:
            if p.name.startswith('libQt6'+family) and '.so' in p.name:return family+' unused native family'
    if p.name.startswith('readline.cpython-') and '.so' in p.name:return 'optional CPython Readline extension'
    if p.name.startswith('libreadline.so'):return 'optional Readline native library'
    return None


def needed(source):
    source=Path(source)
    if not source.is_file():return []
    with source.open('rb') as stream:
        if stream.read(4)!=b'\x7fELF':return []
    run=subprocess.run(['readelf','-d',str(source)],capture_output=True,text=True,check=True)
    return re.findall(r'\(NEEDED\).*?\[([^\]]+)\]',run.stdout)


def prune(binaries,datas,read_needed=needed):
    reasons={str(row[0]):exclusion(str(row[0])) for row in [*binaries,*datas] if exclusion(str(row[0]))}
    edges={str(row[0]):read_needed(row[1]) for row in binaries if row[2]!='SYMLINK'}
    while True:
        aliases={}
        # PyInstaller can put binary convenience aliases in the data TOC.
        for row in [*binaries,*datas]:
            if row[2]!='SYMLINK' or str(row[0]) in reasons:continue
            target=posixpath.normpath(str(PurePosixPath(row[0]).parent/PurePosixPath(row[1])))
            if target.startswith(('../','/')):raise ValueError('Escaping binary alias')
            if target in reasons:aliases[str(row[0])]='alias of explicitly excluded '+target
        reasons.update(aliases)
        removed_names={PurePosixPath(path).name for path in reasons}
        discovered={}
        for row in binaries:
            path=str(row[0])
            if path in reasons:continue
            dependency=next((name for name in edges.get(path,[]) if name in removed_names),None)
            if dependency:
                # Family QML is already removed above. Only these reviewed
                # optional plugins may follow it; unknown QML also fails closed.
                if path not in OPTIONAL_PLUGINS:
                    raise ValueError(f'Unexpected retained dependency: {path} needs removed {dependency}')
                discovered[path]='unused Qt plugin depends on '+dependency
        if not discovered and not aliases:break
        reasons.update(discovered)
    kept_binaries=[r for r in binaries if str(r[0]) not in reasons]
    kept_datas=[r for r in datas if str(r[0]) not in reasons]
    if any(exclusion(str(r[0])) for r in [*kept_binaries,*kept_datas]):raise AssertionError('Flagged component remains')
    return kept_binaries,kept_datas,[{'path':path,'reason':reason} for path,reason in sorted(reasons.items())]


def verify_payload(root):
    root=Path(root).resolve()
    for path in root.rglob('*'):
        relative=path.relative_to(root).as_posix()
        if path.is_symlink():
            target=path.resolve(strict=True)
            if not target.is_relative_to(root):raise ValueError('Escaping packaged alias')
        if exclusion(relative) or ('.so' in path.name and
                any(path.name.startswith('libQt6'+family) for family in FAMILIES)):
            raise ValueError('Excluded component remains: '+relative)
