"""Native file choosers with explicit, pre-isolation Windows shell locations.

The isolated GUI USERPROFILE must remain isolated. Windows' implicit Downloads
place can expand against it. Supply literal configured places and prominent
native Downloads/Documents controls; AddPlace alone may not appear in the pane.
This chooser grants no directory access to pages;
the existing backup output adapter still validates and pins the returned path.
"""
from __future__ import annotations

import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
import uuid


class GUID(c.Structure):
    _fields_ = [('data1', w.DWORD), ('data2', w.WORD), ('data3', w.WORD),
                ('data4', c.c_ubyte * 8)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


def configured_folders():
    """Resolve paths only, before changing HOME/USERPROFILE; do not enumerate."""
    return tuple(known_folder(value) for value in (
        'fdd39ad0-238f-46af-adb4-6c85480369c7',  # Documents, including redirection
        '374de290-123f-4565-9164-39c4925e467b'))  # Downloads; preserve named slots


def known_folder(identifier):
    """Read Windows' configured path; never create or enumerate a known folder."""
    shell, ole = c.WinDLL('shell32'), c.WinDLL('ole32')
    get = shell.SHGetKnownFolderPath
    get.argtypes, get.restype = (c.POINTER(GUID), w.DWORD, w.HANDLE,
                                c.POINTER(c.c_void_p)), c.c_long
    ole.CoTaskMemFree.argtypes, ole.CoTaskMemFree.restype = (w.LPVOID,), None
    result = c.c_void_p()
    try:
        _checked(get(c.byref(GUID.parse(identifier)), 0x4000, None, c.byref(result)))  # DONT_VERIFY
        return Path(c.wstring_at(result))
    finally:
        if result:
            ole.CoTaskMemFree(result)


def _checked(result):
    if result < 0:
        raise OSError(result, f'Windows backup chooser failed (HRESULT 0x{result & 0xffffffff:08X})')
    return result


def _method(pointer, index, *arguments):
    table = c.cast(pointer, c.POINTER(c.POINTER(c.c_void_p))).contents
    return c.WINFUNCTYPE(c.c_long, c.c_void_p, *arguments)(table[index])


def _release(pointer):
    if pointer:
        table = c.cast(pointer, c.POINTER(c.POINTER(c.c_void_p))).contents
        c.WINFUNCTYPE(w.ULONG, c.c_void_p)(table[2])(pointer)


class NativeSaveDialog:
    """One STA-owned IFileSaveDialog; COM objects never cross threads."""
    def __init__(self):
        self.ole = c.WinDLL('ole32')
        self.shell = c.WinDLL('shell32')
        self.ole.CoUninitialize.argtypes, self.ole.CoUninitialize.restype = (), None
        self.ole.CoTaskMemFree.argtypes, self.ole.CoTaskMemFree.restype = (w.LPVOID,), None
        self.dialog = c.c_void_p()
        self.initialized = False
        self.places = None

    clsid = 'c0b4e2f3-ba21-4773-8dba-335ec946eb8b'
    iid = '84bccd23-5fde-4cdb-aea4-af64b83d78ab'
    opening = False

    def __enter__(self):
        initialize = self.ole.CoInitializeEx
        initialize.argtypes, initialize.restype = (w.LPVOID, w.DWORD), c.c_long
        _checked(initialize(None, 2))  # COINIT_APARTMENTTHREADED
        self.initialized = True
        try:
            create = self.ole.CoCreateInstance
            create.argtypes, create.restype = (c.POINTER(GUID), w.LPVOID, w.DWORD,
                                               c.POINTER(GUID), c.POINTER(c.c_void_p)), c.c_long
            _checked(create(c.byref(GUID.parse(self.clsid)),
                            None, 1, c.byref(GUID.parse(self.iid)),
                            c.byref(self.dialog)))
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        try:
            try:
                if self.places:
                    self.places.close()
            finally:
                _release(self.dialog)
        finally:
            self.dialog = c.c_void_p()
            if self.initialized:
                self.initialized = False
                self.ole.CoUninitialize()

    def call(self, index, types, *args):
        return _checked(_method(self.dialog, index, *types)(self.dialog, *args))

    def _item(self, path):
        create = self.shell.SHCreateItemFromParsingName
        create.argtypes, create.restype = (w.LPCWSTR, w.LPVOID, c.POINTER(GUID),
                                          c.POINTER(c.c_void_p)), c.c_long
        item = c.c_void_p()
        _checked(create(str(path), None, c.byref(GUID.parse('43826d1e-e718-42ee-bc55-a1e261c37bfe')),
                        c.byref(item)))
        return item

    def configure(self, filename, folders, *, title=None, pattern='*.zip', initial=None, notice=''):
        class Filter(c.Structure):
            _fields_ = [('name', w.LPCWSTR), ('pattern', w.LPCWSTR)]
        filters = (Filter * 1)(Filter('DLMS backups (*.zip)' if pattern == '*.zip' else 'Export file', pattern))
        self.call(4, (w.UINT, c.POINTER(Filter)), 1, filters)
        if filename:
            self.call(15, (w.LPCWSTR,), filename)
        self.call(17, (w.LPCWSTR,), title or 'Save Local DLMS backup')
        if pattern.startswith('*.') and ';' not in pattern:
            self.call(22, (w.LPCWSTR,), pattern[2:])
        # No overwrite prompt: existing destinations remain a clear refusal in
        # the publication adapter. Never test-create or add personal MRU data.
        self.call(9, (w.DWORD,), 0x40 | 0x800 | 0x10000 | 0x2000000 | 0x8
                  | (0x1000 if self.opening else 0x8000))
        for folder in dict.fromkeys(folders):
            try:
                item = self._item(folder)
            except OSError:
                continue  # Optional sidebar hint; named control remains visible.
            try:
                try:
                    self.call(21, (c.c_void_p, c.c_int), item, 1)  # FDAP_TOP: supplemental hint
                except OSError:
                    pass  # The explicit visible controls do not depend on it.
            finally:
                _release(item)
        preferred = initial or folders[0]
        for folder in dict.fromkeys((preferred, *folders)):
            try:
                self.set_folder(folder)
                if folder != preferred:
                    notice = ('Requested folder unavailable. Opened another configured Windows folder. '
                              'Use Downloads or Documents below.')
                break
            except OSError:
                continue
        else:
            raise ValueError('Configured Documents/Downloads locations are unavailable. Reconnect the folder or correct its Windows configuration, then retry.')
        self.places = FolderControls(self, folders, notice)

    def set_folder(self, folder):
        item = self._item(folder)
        try:
            self.call(12, (c.c_void_p,), item)
        finally:
            _release(item)

    def _item_path(self, item):
        name = c.c_void_p()
        try:
            _checked(_method(item, 5, c.c_uint, c.POINTER(c.c_void_p))(
                item, 0x80058000, c.byref(name)))
            return c.wstring_at(name)
        finally:
            if name:
                self.ole.CoTaskMemFree(name)

    def current_folder(self):
        item = c.c_void_p()
        try:
            self.call(13, (c.POINTER(c.c_void_p),), c.byref(item))
            return self._item_path(item)
        finally:
            _release(item)

    def show(self, owner):
        result = _method(self.dialog, 3, w.HWND)(self.dialog, owner)
        if result & 0xffffffff == 0x800704c7:  # HRESULT_FROM_WIN32(ERROR_CANCELLED)
            return ''
        _checked(result)
        item = c.c_void_p()
        try:
            self.call(20, (c.POINTER(c.c_void_p),), c.byref(item))
            return self._item_path(item)
        finally:
            _release(item)


class NativeOpenDialog(NativeSaveDialog):
    clsid = 'dc1c5a9c-e88a-4dde-a5a1-60f82a20aef7'
    iid = 'd57c7288-d4ad-4768-be02-9d969532d960'
    opening = True


class FolderControls:
    """STA-owned visible native buttons; no window messages or browser bridge.

    AddPlace alone is not discoverable in every Windows navigation-pane layout.
    These controls use literal pre-isolation paths, never shell: aliases.
    """
    DOCUMENTS, DOWNLOADS, GROUP, STATUS = 6101, 6102, 6100, 6103

    def __init__(self, dialog, folders, notice=''):
        self.dialog, self.folders = dialog, tuple(folders)
        self.custom, self.cookie = c.c_void_p(), w.DWORD()
        self.callbacks, self.refs, self.advised = [], 1, False
        self.errors = []
        _checked(_method(dialog.dialog, 0, c.POINTER(GUID), c.POINTER(c.c_void_p))(
            dialog.dialog, c.byref(GUID.parse('e6fdd21a-163f-4975-9c8c-a69f1ba37034')),
            c.byref(self.custom)))
        try:
            self._custom(26, (w.DWORD, w.LPCWSTR), self.GROUP, 'DLMS locations')
            if len(folders) > 1:
                self._custom(5, (w.DWORD, w.LPCWSTR), self.DOWNLOADS, '&Downloads')
            self._custom(5, (w.DWORD, w.LPCWSTR), self.DOCUMENTS, 'D&ocuments')
            self._custom(11, (w.DWORD, w.LPCWSTR), self.STATUS,
                         notice or 'Use these buttons for your Windows folders.')
            self._custom(27, ())
            self._custom(28, (w.DWORD,), self.GROUP)
            self._make_sink()
            dialog.call(7, (c.c_void_p, c.POINTER(w.DWORD)),
                        c.byref(self.events), c.byref(self.cookie))
            self.advised = True
        except BaseException:
            self.close()
            raise

    def _custom(self, index, types, *args):
        return _checked(_method(self.custom, index, *types)(self.custom, *args))

    def navigate(self, identifier):
        """Called only by this dialog's native control-event interface."""
        index = {self.DOCUMENTS: 0, self.DOWNLOADS: 1}.get(identifier)
        if index is None or index >= len(self.folders):
            return 0
        try:
            self.dialog.set_folder(self.folders[index])
            self._custom(12, (w.DWORD, w.LPCWSTR), self.STATUS,
                         'Windows Downloads' if index else 'Windows Documents')
        except Exception:
            # Native callbacks must not raise across the COM ABI. Keep the
            # dialog open and make the unavailable destination actionable.
            self.errors.append(identifier)
            try:
                self._custom(12, (w.DWORD, w.LPCWSTR), self.STATUS,
                             'Folder unavailable. Choose another folder or cancel.')
            except Exception:
                pass  # A retiring native dialog cannot accept status updates.
        return 0

    def _make_sink(self):
        class Interface(c.Structure):
            _fields_ = [('vtable', c.POINTER(c.c_void_p))]
        unknown = bytes(GUID.parse('00000000-0000-0000-c000-000000000046'))
        events = bytes(GUID.parse('973510db-7d7f-452b-8975-74a85828d354'))
        controls = bytes(GUID.parse('36116642-d713-4b97-9b83-7484a9d00433'))
        def query(this, iid, output):
            value = c.string_at(iid, 16)
            target = self.events if value in (unknown, events) else self.controls if value == controls else None
            if target is None:
                output[0] = None
                return -2147467262
            output[0] = c.addressof(target)
            self.refs += 1
            return 0
        def add_ref(this): self.refs += 1; return self.refs
        def release(this): self.refs -= 1; return self.refs
        def noop(*args): return 0
        def response(this, dialog, item, output): output[0] = 0; return 0
        def button(this, custom, identifier): return self.navigate(identifier)
        common = [(c.c_long, (c.c_void_p, c.POINTER(c.c_void_p)), query),
                  (w.ULONG, (), add_ref), (w.ULONG, (), release)]
        def interface(specifications):
            callbacks = [c.WINFUNCTYPE(result, c.c_void_p, *arguments)(function)
                         for result, arguments, function in specifications]
            self.callbacks.extend(callbacks)
            table = (c.c_void_p * len(callbacks))(*(c.cast(fn, c.c_void_p).value for fn in callbacks))
            self.tables.append(table)
            return Interface(table)
        self.tables = []
        self.events = interface(common + [
            (c.c_long, (c.c_void_p,), noop),
            (c.c_long, (c.c_void_p, c.c_void_p), noop),
            (c.c_long, (c.c_void_p,), noop),
            (c.c_long, (c.c_void_p,), noop),
            (c.c_long, (c.c_void_p, c.c_void_p, c.POINTER(c.c_int)), response),
            (c.c_long, (c.c_void_p,), noop),
            (c.c_long, (c.c_void_p, c.c_void_p, c.POINTER(c.c_int)), response)])
        self.controls = interface(common + [
            (c.c_long, (c.c_void_p, w.DWORD, w.DWORD), noop),
            (c.c_long, (c.c_void_p, w.DWORD), button),
            (c.c_long, (c.c_void_p, w.DWORD, w.BOOL), noop),
            (c.c_long, (c.c_void_p, w.DWORD), noop)])

    def close(self):
        try:
            if self.advised:
                self.advised = False
                self.dialog.call(8, (w.DWORD,), self.cookie)
        finally:
            _release(self.custom)
            self.custom = c.c_void_p()


def choose(owner, filename, folders, *, factory=NativeSaveDialog):
    """Return one explicit filename or cancellation; never publish any bytes."""
    if not folders:
        raise ValueError('Configured Documents/Downloads locations are unavailable; reopen Desktop after correcting Windows folder configuration')
    with factory() as dialog:
        dialog.configure(filename, folders)
        return dialog.show(int(owner.winId())), ''


def choose_open(owner, folders, *, factory=NativeOpenDialog):
    if not folders:
        raise ValueError('Configured Documents/Downloads locations are unavailable')
    with factory() as dialog:
        dialog.configure('', folders, title='Select a Local DLMS backup')
        return dialog.show(int(owner.winId())), ''


def choose_export(owner, filename, folders, initial=None, *, title='Save quiz export as', notice='', factory=NativeSaveDialog):
    if not folders:
        raise ValueError('Configured Documents/Downloads locations are unavailable')
    # Filename remains a suggestion. The output adapter separately enforces
    # safe names, destination ownership and no-replace publication.
    suffix = Path(filename).suffix
    pattern = '*' + suffix if suffix else '*.*'
    with factory() as dialog:
        dialog.configure(filename, folders, title=title, pattern=pattern,
                         initial=initial or folders[-1], notice=notice)
        return dialog.show(int(owner.winId())), ''
