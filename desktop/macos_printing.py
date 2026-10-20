"""One standard AppKit/PDFKit print operation, including native PDF choices.

The immutable selected-card snapshot is the only document AppKit receives.
AppKit owns printer/PDF settings, destination selection and overwrite consent.
No destination bridge, separate PDF action, shell command or Qt private API.
"""
from __future__ import annotations
import ctypes as C
import sys
import threading

P = C.c_void_p
_COMPLETIONS = {}
_DELEGATE_CLASS = None
_DELEGATE_CALLBACKS = []


class Size(C.Structure):
    _fields_ = [('width', C.c_double), ('height', C.c_double)]


class NativePrint:
    def __init__(self):
        if sys.platform != 'darwin':
            raise RuntimeError('AppKit printing requires macOS')
        self.appkit = C.CDLL('/System/Library/Frameworks/AppKit.framework/AppKit')
        C.CDLL('/System/Library/Frameworks/PDFKit.framework/PDFKit')
        self.objc = C.CDLL('/usr/lib/libobjc.A.dylib')
        self.objc.objc_getClass.argtypes = [C.c_char_p]
        self.objc.objc_getClass.restype = P
        self.objc.sel_registerName.argtypes = [C.c_char_p]
        self.objc.sel_registerName.restype = P
        self.pm = C.CDLL('/System/Library/Frameworks/ApplicationServices.framework/Frameworks/PrintCore.framework/PrintCore')
        for name, args in {
            'PMSetDuplex': [P, C.c_uint32],
        }.items():
            function = getattr(self.pm, name)
            function.argtypes = args
            function.restype = C.c_int32

    def cls(self, name):
        result = self.objc.objc_getClass(name.encode())
        if not result:
            raise RuntimeError('Required native printing class unavailable')
        return result

    def send(self, receiver, selector, result=P, types=(), args=()):
        if not receiver:
            raise RuntimeError('Native printing object unavailable')
        return C.CFUNCTYPE(result, P, P, *types)(('objc_msgSend', self.objc))(
            receiver, self.objc.sel_registerName(selector.encode()), *args)

    def string(self, text):
        return self.send(self.cls('NSString'), 'stringWithUTF8String:', types=(C.c_char_p,), args=(text.encode(),))

    def number(self, value):
        return self.send(self.cls('NSNumber'), 'numberWithDouble:', types=(C.c_double,), args=(value,))

    def key(self, key):
        return P.in_dll(self.appkit, key).value

    def sheet(self, target, window):
        """Keep Qt's event loop alive while AppKit owns its native sheet.

        Nested AppKit runModal can immediately abort in Qt's Cocoa dispatcher;
        use public completion delegates instead of Qt's private interrupt API.
        """
        from PySide6.QtCore import QEventLoop
        global _DELEGATE_CLASS
        if _DELEGATE_CLASS is None:
            runtime = self.objc
            runtime.objc_allocateClassPair.argtypes = [P, C.c_char_p, C.c_size_t]
            runtime.objc_allocateClassPair.restype = P
            runtime.objc_registerClassPair.argtypes = [P]
            runtime.class_addMethod.argtypes = [P, P, P, C.c_char_p]
            runtime.class_addMethod.restype = C.c_bool
            delegate_class = runtime.objc_allocateClassPair(self.cls('NSObject'), b'DLMSAveryPrintCompletion', 0)
            if not delegate_class:
                raise RuntimeError('Native print completion class unavailable')
            for name, result_type, encoding in (
                ('operation:finished:context:', C.c_bool, b'v@:@B^v'),
            ):
                def completed(_self, _cmd, _sender, value, context):
                    state = _COMPLETIONS.get(context)
                    if state is not None and state['sender'] == _sender:
                        # Never propagate Python exceptions across the ObjC ABI.
                        try:
                            state['callback'](value)
                        except BaseException:
                            state['error'] = True
                            state['loop'].quit()
                implementation = C.CFUNCTYPE(None, P, P, P, result_type, P)(completed)
                selector = runtime.sel_registerName(name.encode())
                if not runtime.class_addMethod(delegate_class, selector, C.cast(implementation, P), encoding):
                    raise RuntimeError('Native print completion method unavailable')
                _DELEGATE_CALLBACKS.append(implementation)
            runtime.objc_registerClassPair(delegate_class)
            _DELEGATE_CLASS = delegate_class
        native_window = self.send(P(int(window.winId())), 'window')
        if not native_window:
            raise RuntimeError('The owned native print window is unavailable')
        loop = QEventLoop()
        outcome = []
        def completed(value):
            if not outcome:
                outcome.append(value)
                loop.quit()
        token = id(outcome)
        delegate = self.send(self.send(_DELEGATE_CLASS, 'alloc'), 'init')
        state = {'sender':target, 'callback':completed, 'loop':loop, 'error':False}
        _COMPLETIONS[token] = state
        try:
            selector = self.objc.sel_registerName(b'operation:finished:context:')
            self.send(target, 'runOperationModalForWindow:delegate:didRunSelector:contextInfo:',
                      None, (P, P, P, P), (native_window, delegate, selector, P(token)))
            while not outcome and not state['error']:
                loop.exec()
            if state['error']:
                raise RuntimeError('Native printing completion failed')
            return outcome[0]
        finally:
            _COMPLETIONS.pop(token, None)
            self.send(delegate, 'release', None)


def print_avery(content: bytes, duplex: str, current, window):
    """Show the standard print/PDF sheet for an already-authorized snapshot.

    The caller freezes its page/mode and holds browser_dialog until completion.
    Opening the operation does not accept its dialog or submit a print job.
    OS destination/overwrite confirmation is intentionally the output authority.
    """
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Native printing requires the GUI thread')
    if duplex not in ('short', 'long') or not isinstance(content, bytes) or not content.startswith(b'%PDF-'):
        raise ValueError('Invalid Avery print snapshot or flip intent')
    if not current():
        return {'kind': 'refused', 'message': 'The page or mode changed. Printing did not start.'}
    api = NativePrint()
    pool = api.send(api.cls('NSAutoreleasePool'), 'new')
    retained = []
    try:
        info = api.send(api.send(api.cls('NSPrintInfo'), 'sharedPrintInfo'), 'copy')
        retained.append(info)
        api.send(info, 'setPaperSize:', None, (Size,), (Size(612, 792),))
        api.send(info, 'setOrientation:', None, (C.c_long,), (0,))
        for side in ('Left', 'Right', 'Top', 'Bottom'):
            api.send(info, 'set' + side + 'Margin:', None, (C.c_double,), (0,))
        dictionary = api.send(info, 'dictionary')
        for key,value in (('NSPrintScalingFactor',1),('NSPrintPagesAcross',1),('NSPrintPagesDown',1),
                          ('NSPrintCopies',1),('NSPrintAllPages',1),('NSPrintFirstPage',1),('NSPrintLastPage',0x7fffffff)):
            api.send(dictionary, 'setObject:forKey:', None, (P, P), (api.number(value), api.key(key)))
        settings = api.send(info, 'PMPrintSettings')
        if api.pm.PMSetDuplex(settings, 3 if duplex == 'short' else 2) != 0:
            raise RuntimeError('Native duplex default could not be established')
        api.send(info, 'updateFromPMPrintSettings', None)
        # NSData copies these bytes; subsequent changes to the private evidence
        # file or the web DOM cannot change the document in the native dialog.
        buffer = C.create_string_buffer(content)
        data = api.send(api.cls('NSData'), 'dataWithBytes:length:', P,
                        (P, C.c_ulong), (C.cast(buffer,P),len(content)))
        document = api.send(api.send(api.cls('PDFDocument'), 'alloc'), 'initWithData:', P, (P,), (data,))
        if not document:
            raise RuntimeError('The Avery print snapshot could not be read')
        retained.append(document)
        if not api.send(document, 'pageCount', C.c_ulong):
            raise RuntimeError('The Avery print snapshot is empty')
        operation = api.send(document, 'printOperationForPrintInfo:scalingMode:autoRotate:',
                             P, (P, C.c_long, C.c_bool), (info, 0, False))
        if not operation:
            raise RuntimeError('The system could not prepare the print operation')
        retained.append(api.send(operation, 'retain'))
        api.send(operation, 'setJobTitle:', None, (P,), (api.string('DLMS Avery cards'),))
        api.send(operation, 'setShowsPrintPanel:', None, (C.c_bool,), (True,))
        api.send(operation, 'setShowsProgressPanel:', None, (C.c_bool,), (True,))
        if not current():
            return {'kind': 'refused', 'message': 'The page or mode changed. Printing did not start.'}
        success = api.sheet(operation, window)
        # False can mean cancel or failure, even after a spool attempt. The UI
        # action and observed output/queue determine the narrower test result.
        return {'kind': 'completed' if success else 'not_completed',
                'message': ('Print/PDF operation completed. Physical paper output is not confirmed.' if success
                            else 'Print/PDF operation canceled or failed. No completion is confirmed; check the system dialog or printer queue.')}
    finally:
        for item in reversed(retained):
            api.send(item, 'release', None)
        api.send(pool, 'drain', None)
