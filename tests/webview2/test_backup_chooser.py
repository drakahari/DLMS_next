"""Windows backup destination configuration and unchanged publication guards."""
import ctypes as c
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

if os.name != 'nt':
    pytest.skip('Windows native chooser', allow_module_level=True)

from desktop import windows_backup_chooser as chooser


@pytest.mark.parametrize('result', ['', 'C:/Ordinary Downloads 日本語/backup.zip'])
def test_explicit_places_owner_cancel_selection_and_cleanup(result):
    observed = []
    folders = (Path('C:/Redirected OneDrive/Documents'), Path('C:/Ordinary Downloads 日本語'))
    class Dialog:
        def __enter__(self): observed.append('enter'); return self
        def __exit__(self, *args): observed.append('exit')
        def configure(self, filename, places): observed.append((filename, places))
        def show(self, owner): observed.append(owner); return result
    assert chooser.choose(SimpleNamespace(winId=lambda: 123), 'backup.zip', folders, factory=Dialog) == (result, '')
    assert observed == ['enter', ('backup.zip', folders), 123, 'exit']


def test_missing_prescope_locations_fails_without_late_resolution():
    with pytest.raises(ValueError, match='Configured Documents/Downloads'):
        chooser.choose(SimpleNamespace(winId=lambda: 123), 'backup.zip', ())


@pytest.mark.parametrize('result', [-2147023673, -2147467259])
def test_cancel_hresult_is_distinct_from_native_failure(monkeypatch, result):
    dialog = object.__new__(chooser.NativeSaveDialog)
    dialog.dialog = c.c_void_p()
    monkeypatch.setattr(chooser, '_method', lambda *args: lambda *args: result)
    if result == -2147023673:
        assert dialog.show(123) == ''
    else:
        with pytest.raises(OSError, match='HRESULT 0x80004005'):
            dialog.show(123)


def test_configuration_failure_remains_error_and_releases():
    retired = []
    class Dialog:
        def __enter__(self): return self
        def __exit__(self, *args): retired.append(True)
        def configure(self, *args): raise OSError('synthetic native configuration error')
    with pytest.raises(OSError, match='configuration error'):
        chooser.choose(SimpleNamespace(winId=lambda: 123), 'backup.zip', (Path('C:/Synthetic'),), factory=Dialog)
    assert retired == [True]


def test_capture_preserves_redirected_paths_and_order(monkeypatch):
    paths = {'fdd39ad0-238f-46af-adb4-6c85480369c7': 'C:/Redirected Documents 日本語',
             '374de290-123f-4565-9164-39c4925e467b': 'D:/Ordinary Downloads'}
    monkeypatch.setattr(chooser, 'known_folder', lambda location: Path(paths[location]))
    assert chooser.configured_folders() == tuple(map(Path, paths.values()))


def test_capture_retains_downloads_named_slot_when_redirected_to_documents(monkeypatch):
    monkeypatch.setattr(chooser, 'known_folder', lambda location: Path('C:/Shared Folder'))
    assert chooser.configured_folders() == (Path('C:/Shared Folder'), Path('C:/Shared Folder'))


def test_native_control_navigation_is_literal_and_failure_cannot_cross_com():
    recorded = []
    controls = object.__new__(chooser.FolderControls)
    controls.folders = (Path('C:/Redirected Documents'), Path('D:/Real Downloads 日本語'))
    controls.dialog = SimpleNamespace(set_folder=lambda path: recorded.append(path))
    controls._custom = lambda *args: None
    controls.errors = []
    assert controls.navigate(controls.DOWNLOADS) == 0
    assert recorded == [controls.folders[1]]
    def fail(*args): raise OSError('unavailable')
    controls.dialog.set_folder = fail
    controls._custom = fail
    assert controls.navigate(controls.DOWNLOADS) == 0
    assert controls.errors == [controls.DOWNLOADS]


@pytest.mark.parametrize('initial', [None, Path('E:/Previous export folder')])
def test_export_starts_in_real_downloads_or_explicit_remembered_folder(initial):
    calls = []
    class Dialog:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def configure(self, *args, **kw): calls.append((args, kw))
        def show(self, owner): assert owner == 123; return ''
    folders = (Path('C:/Docs'), Path('D:/Downloads'))
    assert chooser.choose_export(SimpleNamespace(winId=lambda:123), 'quiz.txt', folders,
        initial, title='Save Server https://synthetic.invalid export', factory=Dialog) == ('', '')
    assert calls == [(('quiz.txt', folders), {'title':'Save Server https://synthetic.invalid export',
        'pattern':'*.txt', 'initial':initial or folders[1], 'notice':''})]


def test_restore_uses_native_open_dialog_with_explicit_places(tmp_path):
    docs, downloads = tmp_path/'Documents', tmp_path/'Downloads 日本語'
    docs.mkdir(); downloads.mkdir()
    with chooser.NativeOpenDialog() as dialog:
        dialog.configure('', (docs, downloads), title='Select a Local DLMS backup')
        options = c.c_ulong()
        dialog.call(10, (c.POINTER(c.c_ulong),), c.byref(options))
        assert options.value & 0x1000
        assert not options.value & 0x8000  # Read-only backups remain readable.
        assert Path(dialog.current_folder()) == docs
        assert dialog.places.navigate(dialog.places.DOWNLOADS) == 0
        assert Path(dialog.current_folder()) == downloads


@pytest.mark.parametrize('missing', ['documents', 'downloads', 'remembered'])
def test_unavailable_known_or_remembered_folder_uses_other_explicit_place(tmp_path,missing):
    docs,downloads=tmp_path/'Documents',tmp_path/'Downloads'
    if missing!='documents':docs.mkdir()
    if missing!='downloads':downloads.mkdir()
    initial=tmp_path/'Removed previous export' if missing=='remembered' else None
    with chooser.NativeSaveDialog() as dialog:
        dialog.configure('backup.zip',(docs,downloads),initial=initial)
        assert Path(dialog.current_folder()) == (downloads if missing=='documents' else docs)
        # Missing known locations remain discoverable but give visible error
        # feedback rather than expanding a shell alias into managed storage.
        if missing in ('documents','downloads'):
            identifier=dialog.places.DOCUMENTS if missing=='documents' else dialog.places.DOWNLOADS
            assert dialog.places.navigate(identifier)==0
            assert dialog.places.errors==[identifier]


def test_no_available_explicit_places_fails_without_managed_fallback(tmp_path):
    with chooser.NativeSaveDialog() as dialog:
        with pytest.raises(ValueError,match='Configured Documents/Downloads locations are unavailable'):
            dialog.configure('backup.zip',(tmp_path/'Missing Documents',tmp_path/'Missing Downloads'))


def test_base_qt_backup_chooser_keeps_original_static_behavior(monkeypatch):
    from desktop import shell
    calls = []
    owner = SimpleNamespace(_documents_folder=lambda: Path('C:/Configured Documents'))
    monkeypatch.setattr(shell.time, 'strftime', lambda pattern: 'DLMS-backup-fixed.zip')
    monkeypatch.setattr(shell.QFileDialog, 'getSaveFileName', lambda *args, **kwargs: calls.append((args, kwargs)) or ('', ''))
    assert shell.DesktopWindow._choose_backup_destination(owner) == ('', '')
    assert calls == [((owner, 'Save Local DLMS backup', str(Path('C:/Configured Documents/DLMS-backup-fixed.zip')),
                      'DLMS backups (*.zip)'), {'options': shell.QFileDialog.Option.DontConfirmOverwrite})]


def test_native_com_configuration_on_synthetic_folders_without_show(tmp_path):
    documents, downloads = tmp_path / 'Redirected Documents 日本語', tmp_path / 'Ordinary Downloads'
    documents.mkdir(); downloads.mkdir()
    before = Path.cwd()
    with chooser.NativeSaveDialog() as dialog:
        dialog.configure('synthetic backup.zip', (documents, downloads))
        options = c.c_ulong()
        dialog.call(10, (c.POINTER(c.c_ulong),), c.byref(options))
        assert options.value & (0x40 | 0x800 | 0x10000 | 0x2000000 | 0x8) == (0x40 | 0x800 | 0x10000 | 0x2000000 | 0x8)
        assert not options.value & (0x2 | 0x100 | 0x1000 | 0x200)  # no overwrite, NOVALIDATE, FILEMUSTEXIST, multi
    assert Path.cwd() == before
    assert not list(documents.iterdir()) and not list(downloads.iterdir())


def test_ordinary_downloads_publication_and_existing_file_refusal(tmp_path):
    from desktop.backup_output import select, publish
    downloads = tmp_path / 'Ordinary Downloads 日本語'; downloads.mkdir(mode=0o700)
    source = tmp_path / 'private.zip'; source.write_bytes(b'synthetic confirmed backup bytes')
    target = downloads / 'chosen backup.zip'
    result = publish(source, select(target))
    assert target.read_bytes() == source.read_bytes()
    assert result['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError, match='no file was replaced'):
        select(target)
    assert target.read_bytes() == source.read_bytes()


def test_forbidden_scoped_downloads_stays_refused(tmp_path):
    from desktop.backup_output import select
    managed = tmp_path / 'managed'; managed.mkdir(mode=0o700)
    scoped = managed / 'home' / 'Downloads'; scoped.mkdir(parents=True, mode=0o700)
    with pytest.raises(ValueError, match='outside managed storage'):
        select(scoped / 'backup.zip', forbidden=(managed,))


@pytest.mark.parametrize('outcome', ['cancel', 'error', 'existing', 'stale'])
def test_backup_transaction_cancellation_failure_stale_and_focus(tmp_path, outcome):
    from desktop.shell import DesktopWindow
    target = tmp_path / 'already exists.zip'; target.write_bytes(b'unchanged')
    feedback, focus, submitted = [], [], []
    button = SimpleNamespace(setFocus=lambda reason: focus.append(reason))
    state = {'ready': True}
    def choose():
        if outcome == 'error': raise OSError('synthetic chooser failure')
        if outcome == 'stale': state['ready'] = False
        return (str(target) if outcome == 'existing' else '', '')
    owner = SimpleNamespace(_backup_creating=False, _settings_generation=7,
        _active_outputs=lambda: False, _settings_ready=lambda kind: state['ready'],
        _begin_feedback=lambda kind: 1, _feedback=lambda *args: feedback.append(args),
        open_backup_folder=SimpleNamespace(hide=lambda: None),
        _choose_backup_destination=choose, settings_buttons={'create_backup': button},
        view=SimpleNamespace(page=lambda: SimpleNamespace(runJavaScript=lambda *args: submitted.append(args))))
    DesktopWindow._create_settings_backup(owner)
    assert not owner._backup_creating and not submitted
    assert target.read_bytes() == b'unchanged'
    assert bool(focus) == (outcome != 'stale')
    if outcome == 'cancel': assert 'canceled; no backup requested' in feedback[-1][1]
    elif outcome in ('error', 'existing'): assert 'refused:' in feedback[-1][1] and feedback[-1][2] == 'error'
    else: assert not feedback
