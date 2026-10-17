"""Test-only IFileDialogEvents sink; no process/window input or raw cross-thread COM."""
import ctypes as c
from ctypes import wintypes as w

from desktop.windows_backup_chooser import GUID


class CancelEvents:
    def __init__(self, dialog, stage):
        self.dialog, self.stage, self.refs, self.callbacks, self.errors = dialog, stage, 1, [], []
        self.fired = False
        class Interface(c.Structure):
            _fields_ = [('vtable', c.POINTER(c.c_void_p))]
        unknown = bytes(GUID.parse('00000000-0000-0000-c000-000000000046'))
        events = bytes(GUID.parse('973510db-7d7f-452b-8975-74a85828d354'))
        def query(this, iid, output):
            if c.string_at(iid, 16) not in (unknown, events):
                output[0] = None
                return -2147467262  # E_NOINTERFACE
            output[0] = c.addressof(self.interface)
            self.refs += 1
            return 0
        def add_ref(this): self.refs += 1; return self.refs
        def release(this): self.refs -= 1; return self.refs
        def cancel(*args):
            if self.fired: return 0
            self.fired = True
            try:
                self.stage('native-dialog-event-callback')
                self.dialog.call(23, (c.c_long,), c.c_long(-2147023673))
                self.stage('native-dialog-event-close-S_OK')
            except BaseException as exc:
                self.errors.append(repr(exc)); self.stage('native-dialog-event-error:' + repr(exc))
            return 0
        def default_response(this, dialog, item, response):
            response[0] = 0
            return 0
        specifications = [
            (c.c_long, (c.c_void_p, c.POINTER(c.c_void_p)), query),
            (w.ULONG, (), add_ref), (w.ULONG, (), release),
            (c.c_long, (c.c_void_p,), cancel),
            (c.c_long, (c.c_void_p, c.c_void_p), cancel),
            (c.c_long, (c.c_void_p,), cancel),
            (c.c_long, (c.c_void_p,), cancel),
            (c.c_long, (c.c_void_p, c.c_void_p, c.POINTER(c.c_int)), default_response),
            (c.c_long, (c.c_void_p,), cancel),
            (c.c_long, (c.c_void_p, c.c_void_p, c.POINTER(c.c_int)), default_response),
        ]
        for result, arguments, function in specifications:
            self.callbacks.append(c.WINFUNCTYPE(result, c.c_void_p, *arguments)(function))
        self.table = (c.c_void_p * len(self.callbacks))(*(c.cast(fn, c.c_void_p).value for fn in self.callbacks))
        self.interface = Interface(self.table)
        self.cookie = w.DWORD()

    def __enter__(self):
        self.dialog.call(7, (c.c_void_p, c.POINTER(w.DWORD)), c.byref(self.interface), c.byref(self.cookie))
        return self

    def __exit__(self, *_):
        self.dialog.call(8, (w.DWORD,), self.cookie)
