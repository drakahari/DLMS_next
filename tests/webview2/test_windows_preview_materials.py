"""Windows preview receipts do not accept Linux-only or substituted material kits."""
import hashlib
import json

import pytest

from package_windows_webview2.preview_materials import verify
from package_windows_webview2.preview_bundle import exclusion


def kit(root):
    root.mkdir()
    for name in ('REDISTRIBUTION.md', 'BUILD_AND_REPLACEMENT.md', 'EXACT_INPUTS.json'):
        (root/name).write_text('synthetic material')
    (root/'SOURCE_MATERIALS.json').write_text(json.dumps({'archives': [{'file':'source.zip','sha256':'a'*64,'bytes':1}], 'unresolved':[]}))
    manifest={'format':1,'platform':'windows-x86_64-preview','sha256': {
        p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}}
    (root/'MANIFEST.json').write_text(json.dumps(manifest))
    return root


def test_exact_windows_materials_and_changed_notice(tmp_path):
    root=kit(tmp_path/'materials')
    assert verify(root)['platform']=='windows-x86_64-preview'
    (root/'REDISTRIBUTION.md').write_text('changed')
    with pytest.raises(ValueError, match='differ'):
        verify(root)


def test_linux_material_manifest_is_not_windows_clearance(tmp_path):
    root=kit(tmp_path/'materials')
    data=json.loads((root/'MANIFEST.json').read_text());data['platform']='linux-x86_64'
    (root/'MANIFEST.json').write_text(json.dumps(data))
    with pytest.raises(ValueError, match='Windows'):
        verify(root)


@pytest.mark.parametrize('path', ['PySide6/Qt6Charts.dll','PySide6/QtQuick3D.pyd',
    'PySide6/qml/QtQuick/Timeline/plugins.dll','PySide6/Qt/qml/QtGraphs/qmldir',
    '_internal/PySide6/Qt6VirtualKeyboard.dll', 'PySide6/Qt6Quick3DRuntimeRender.dll',
    'PySide6/Qt6Quick3DAssetImport.dll', 'PySide6/QtQuick3DUtils.pyd',
    'PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll',
    'PySide6/plugins/qmltooling/qmldbg_quick3dprofiler.dll'])
def test_windows_unused_family_exclusions(path):
    assert exclusion(path)


@pytest.mark.parametrize('path', ['PySide6/Qt6Widgets.dll','PySide6/Qt6WebEngineCore.dll',
    'PySide6/qml/QtQuick/Controls/qmldir','PySide6/QtSvg.pyd'])
def test_required_qt_runtime_is_retained(path):
    assert exclusion(path) is None


def test_unreviewed_native_consumer_of_excluded_family_stops_freeze(monkeypatch):
    import sys
    from types import SimpleNamespace
    from package_windows_webview2.preview_bundle import prune
    class Image:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def parse_data_directories(self,**kwargs):pass
        DIRECTORY_ENTRY_IMPORT=[SimpleNamespace(dll=b'Qt6Charts.dll')]
    monkeypatch.setitem(sys.modules,'pefile',SimpleNamespace(PE=lambda *args,**kwargs:Image(),
        DIRECTORY_ENTRY={'IMAGE_DIRECTORY_ENTRY_IMPORT':1,'IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT':13}))
    with pytest.raises(ValueError,match='Retained Windows binary requires excluded'):
        prune([('PySide6/Qt6Charts.dll','unused.dll','BINARY'),
               ('unknown-consumer.dll','retained.dll','BINARY')],[])
