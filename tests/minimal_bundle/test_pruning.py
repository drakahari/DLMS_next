from pathlib import Path
import pytest
from package_fedora.minimal_bundle import exclusion,prune,FAMILIES,QML


@pytest.mark.parametrize('family',FAMILIES)
def test_exact_family_paths(family):
    assert exclusion(f'PySide6/Qt/lib/libQt6{family}.so.6')
    for root in QML[family]:assert exclusion(f'PySide6/Qt/qml/{root}/qmldir')


@pytest.mark.parametrize('path',['PySide6/Qt/lib/libQt6WaylandClient.so.6','PySide6/Qt/lib/libQt6Quick.so.6','PySide6/Qt/lib/libQt6Qml.so.6','PySide6/Qt/lib/libQt6WebEngineCore.so.6','PySide6/Qt/plugins/platforms/libqwayland-generic.so','ocr/tesseract/bin/tesseract','libjbig.so.2.1','libtiff.so.6','pillow.libs/libtiff-hash.so.6'])
def test_required_or_unassessed_not_pruned(path):assert exclusion(path) is None


def test_optional_plugin_closure_and_unexpected_consumer_refusal():
    library=('PySide6/Qt/lib/libQt6VirtualKeyboard.so.6','library','BINARY')
    plugin=('PySide6/Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so','plugin','BINARY')
    protected=('PySide6/Qt/lib/libQt6WebEngineCore.so.6','required','BINARY')
    read=lambda src:['libQt6VirtualKeyboard.so.6'] if src=='plugin' else []
    kept,_,removed=prune([library,plugin,protected],[],read)
    assert kept==[protected] and len(removed)==2
    with pytest.raises(ValueError,match='Unexpected retained dependency'):
        prune([library,protected],[],lambda src:['libQt6VirtualKeyboard.so.6'] if src=='required' else [])


def test_similar_data_names_and_readline_scope():
    assert exclusion('static/Quick3D-notes.html') is None
    assert exclusion('python3.14/lib-dynload/readline.cpython-314-x86_64-linux-gnu.so')
    assert exclusion('libreadline.so.8')
    assert exclusion('PySide6/Qt/qml/QtQuick/TimelineExtras/qmldir') is None


def test_unknown_platform_plugin_not_silently_removed():
    library=('PySide6/Qt/lib/libQt6VirtualKeyboard.so.6','library','BINARY')
    platform=('PySide6/Qt/plugins/platforms/libqwayland-generic.so','platform','BINARY')
    with pytest.raises(ValueError,match='Unexpected retained dependency'):
        prune([library,platform],[],lambda src:['libQt6VirtualKeyboard.so.6'] if src=='platform' else [])


def test_unknown_retained_qml_consumer_not_silently_removed():
    library=('PySide6/Qt/lib/libQt6Graphs.so.6','library','BINARY')
    plugin=('PySide6/Qt/qml/QtQuick/Controls/libcontrolsplugin.so','qml','BINARY')
    with pytest.raises(ValueError,match='Unexpected retained dependency'):
        prune([library,plugin],[],lambda src:['libQt6Graphs.so.6'] if src=='qml' else [])


def test_exact_contained_alias_of_removed_library_only():
    library=('PySide6/Qt/lib/libQt6Charts.so.6','library','BINARY')
    alias=('libQt6Charts.so.6','PySide6/Qt/lib/libQt6Charts.so.6','SYMLINK')
    wayland=('libQt6WaylandClient.so.6','PySide6/Qt/lib/libQt6WaylandClient.so.6','SYMLINK')
    kept,_,removed=prune([library,alias,wayland],[],lambda src:[])
    assert kept==[wayland] and len(removed)==2
    with pytest.raises(ValueError,match='Escaping'):
        prune([('evil','../../outside','SYMLINK')],[],lambda src:[])


def test_payload_refuses_dangling_alias_and_retains_valid_link(tmp_path):
    from package_fedora.minimal_bundle import verify_payload
    (tmp_path/'keep').write_bytes(b'safe');(tmp_path/'alias').symlink_to('keep');verify_payload(tmp_path)
    (tmp_path/'dangling').symlink_to('absent')
    with pytest.raises(FileNotFoundError):verify_payload(tmp_path)


def test_alias_in_data_toc_is_removed_too():
    library=('PySide6/Qt/lib/libQt6Charts.so.6','library','BINARY')
    alias=('libQt6Charts.so.6','PySide6/Qt/lib/libQt6Charts.so.6','SYMLINK')
    b,d,removed=prune([library],[alias],lambda src:[])
    assert b==[] and d==[] and len(removed)==2
