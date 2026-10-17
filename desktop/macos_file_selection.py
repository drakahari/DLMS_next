"""Explicit Darwin file selection with page-owned, immutable private snapshots.

The chooser grants access to selected bytes, not to an ordinary directory.
These are ephemeral browser File inputs, not durable application acknowledgments.
Backend workflow validators and publication/recovery contracts remain authoritative.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import ctypes
import fcntl
import sys
import hashlib
import os
from pathlib import Path
import secrets
import stat
import tempfile
import threading
import time
import unicodedata
import zipfile

MIB = 1024 * 1024
LIMITS = {'.txt': 16*MIB, '.csv': 16*MIB, '.pdf': 64*MIB, '.zip': 256*MIB,
          **{suffix: 32*MIB for suffix in ('.png', '.jpg', '.jpeg', '.webp', '.gif')}}
PAGE_LIMIT = 384*MIB
PROCESS_LIMIT = 768*MIB
MAX_FILES = 25
MAX_RETAINED_FILES = 256
CHUNK = MIB
_lock = threading.Lock()
_retained = 0

# BSD user immutable flags block writes, truncation, links and namespace
# replacement while Qt holds a page-owned File. They are not Linux memfd seals:
# another deliberately hostile process running as this uid can clear UF_IMMUTABLE.
# No protection against that same-user authority is claimed by this adapter.
def _flags(fd, value):
    if sys.platform != 'darwin':
        raise RuntimeError('The Darwin selected-file adapter requires macOS.')
    library = ctypes.CDLL(None, use_errno=True)
    function = library.fchflags
    function.argtypes = (ctypes.c_int, ctypes.c_uint)
    function.restype = ctypes.c_int
    if function(fd, value) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))

def _reserve(size):
    global _retained
    with _lock:
        if _retained + size > PROCESS_LIMIT:
            raise ValueError('Too much selected file data is still open. Close and reopen the window before selecting more files.')
        _retained += size


def _release(size):
    global _retained
    with _lock:
        _retained -= size


def _under(path, root):
    # Darwin commonly uses case-insensitive APFS and canonical decomposed
    # Unicode. Deny equivalent private spellings even on a case-sensitive disk.
    normalize = lambda value: unicodedata.normalize('NFD', str(value)).casefold().rstrip('/')
    path, root = normalize(path), normalize(root)
    return path == root or path.startswith(root + '/')


def open_source(path: Path, forbidden=(), permitted_private=()):
    """Pin directories; reject links/specials and private-folder aliases."""
    if (path.anchor != '/' or '..' in path.parts or path.suffix.lower() not in LIMITS
            or any(ord(char) < 32 or ord(char) == 127 for char in path.name)):
        raise ValueError('Choose a local TXT, CSV, PDF, ZIP, PNG, JPEG, GIF or WebP file supported by this form.')
    def private(selected):
        return any(_under(selected, root) for root in forbidden) and not any(
            _under(selected, root) for root in permitted_private)
    message = 'Desktop private data and browser/recovery files cannot be selected. Export a supported file to an ordinary folder first.'
    if private(path): raise ValueError(message)
    def identities(roots):
        result = set()
        for root in roots:
            try: info = os.stat(root)
            except FileNotFoundError: continue
            result.add((info.st_dev, info.st_ino))
        return result
    blocked_ids, allowed_ids = identities(forbidden), identities(permitted_private)
    directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    blocked = False
    try:
        for part in path.parent.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
            os.close(directory)
            directory = child
            info = os.fstat(directory)
            identifier = (info.st_dev, info.st_ino)
            if identifier in blocked_ids: blocked = True
            if identifier in allowed_ids: blocked = False
        if blocked: raise ValueError(message)
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
    finally:
        os.close(directory)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
                or not info.st_mode & 0o444 or info.st_size <= 0 or info.st_size > LIMITS[path.suffix.lower()]):
            raise ValueError('Choose a readable, nonempty regular file owned by you, within this form’s file-size limit. Symbolic/hard links and special files are not supported.')
        canonical = Path(os.fsdecode(fcntl.fcntl(fd, fcntl.F_GETPATH, b'\0' * 1024).split(b'\0', 1)[0]))
        if private(canonical): raise ValueError(message)
        return fd, info
    except BaseException:
        os.close(fd)
        raise


def _identity(info):
    return tuple(getattr(info, key) for key in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns'))


def _hash(fd, limit, valid):
    os.lseek(fd, 0, os.SEEK_SET)
    result = hashlib.sha256()
    total = 0
    while block := os.read(fd, CHUNK):
        total += len(block)
        if total > limit or not valid():
            raise ValueError('The selected file changed or selection was canceled while checking its private copy.')
        result.update(block)
    return result.hexdigest()


def _validate(fd, suffix):
    """Bounded preliminary type checks on the exact sealed bytes handed to Qt.

    Route-specific format/asset/archive, encrypted-PDF and pixel limits still
    run in the unchanged backend, and can refuse a preliminary-valid input.
    """
    with os.fdopen(os.dup(fd), 'rb') as stream:
        stream.seek(0)
        if suffix == '.pdf':
            if b'%PDF-' not in stream.read(1024):
                raise ValueError('The selected file does not contain a PDF header. Choose the original PDF.')
        elif suffix == '.zip':
            try:
                with zipfile.ZipFile(stream) as archive:
                    if not archive.infolist():
                        raise ValueError('The selected ZIP is empty.')
            except zipfile.BadZipFile as exc:
                raise ValueError('The selected ZIP is damaged or incomplete. Choose a complete export.') from exc
        elif suffix in {'.png','.jpg','.jpeg','.webp','.gif'}:
            from PIL import Image
            try:
                with Image.open(stream) as image:
                    if image.format not in {'PNG','JPEG','WEBP','GIF'}:
                        raise ValueError('Choose a PNG, JPEG, GIF or WebP raster image.')
                    image.verify()
            except (OSError, SyntaxError) as exc:
                raise ValueError('The selected image cannot be decoded. Choose an intact PNG, JPEG, GIF or WebP.') from exc


class Snapshots:
    """Own native immutable inodes until the exact WebEngine page retires.

    No source pathname is exposed to Chromium. The file and its containing
    job directory are immutable before publication, and held read-only
    descriptors identify every inode that cleanup is permitted to mutate.
    """
    def __init__(self, root: Path):
        root = root.resolve(strict=True)
        info = root.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077 or not stat.S_ISDIR(info.st_mode):
            raise ValueError('Selected-file storage must be a private Desktop-owned directory.')
        self.directory = Path(tempfile.mkdtemp(prefix='selected-files-', dir=root))
        self.root_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        self.items = []
        self.bytes = 0
        self.closed = False
        self._operation_lock = threading.RLock()

    def _check_root(self):
        found = self.directory.lstat()
        held = os.fstat(self.root_fd)
        if not stat.S_ISDIR(found.st_mode) or (found.st_dev, found.st_ino) != (held.st_dev, held.st_ino):
            raise ValueError("Selected-file storage changed; no files were submitted.")

    @staticmethod
    def _retire(item):
        fd, path, size, digest, job_fd, identity = item
        try:
            found = os.stat(path.parent.name, dir_fd=identity[0], follow_symlinks=False)
            held = os.fstat(job_fd)
            if (found.st_dev, found.st_ino) != (held.st_dev, held.st_ino):
                raise ValueError('Selected-file job changed; retained for inspection.')
            selected = os.stat(path.name, dir_fd=job_fd, follow_symlinks=False)
            held_file = os.fstat(fd)
            if (selected.st_dev, selected.st_ino) != (held_file.st_dev, held_file.st_ino):
                raise ValueError('Selected-file name changed; retained for inspection.')
            _flags(job_fd, 0)
            _flags(fd, 0)
            os.unlink(path.name, dir_fd=job_fd)
            os.rmdir(path.parent.name, dir_fd=identity[0])
        finally:
            os.close(fd); os.close(job_fd); _release(size)

    def stage(self, choices, **kwargs):
        with self._operation_lock:
            return self._stage(choices, **kwargs)

    def _stage(self, choices, *, forbidden=(), permitted_private=(), expected=None,
               captured=None, valid=lambda: True, checkpoint=lambda phase, path: None):
        if self.closed or not 0 < len(choices) <= MAX_FILES:
            raise ValueError('Select between one and 25 supported files.')
        if len(self.items) + len(choices) > MAX_RETAINED_FILES:
            raise ValueError('Too many selected files remain open in this page. Close and reopen the window before selecting more.')
        self._check_root()
        pending = []
        try:
            for index, selected in enumerate(choices):
                if not valid():
                    raise ValueError('File selection canceled or its page changed. No selected files were submitted.')
                path = Path(selected)
                if captured is None:
                    source, initial = open_source(path, forbidden, permitted_private)
                else:
                    source, initial = os.dup(captured[index][0]), captured[index][1]
                    os.lseek(source, 0, os.SEEK_SET)
                target = None
                job_fd = None
                reserved = False
                name = secrets.token_hex(16)
                job = self.directory / name
                output = job / path.name
                try:
                    if expected is not None and _identity(initial) != expected[index]:
                        raise ValueError('The selected file changed or was replaced after selection. Choose it again.')
                    if self.bytes + sum(item[2] for item in pending) + initial.st_size > PAGE_LIMIT:
                        raise ValueError('Selected file data exceeds the 384 MiB page limit. Close and reopen the window before choosing more files.')
                    _reserve(initial.st_size); reserved = True
                    os.mkdir(name, 0o700, dir_fd=self.root_fd)
                    job_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self.root_fd)
                    target = os.open(path.name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=job_fd)
                    checkpoint('opened', path)
                    total = 0
                    digest = hashlib.sha256()
                    while block := os.read(source, CHUNK):
                        if not valid():
                            raise ValueError('File selection canceled. No selected files were submitted.')
                        total += len(block)
                        if total > initial.st_size:
                            raise ValueError('The selected file changed while being copied. Select it again.')
                        digest.update(block)
                        view = memoryview(block)
                        while view:
                            count = os.write(target, view)
                            if not count: raise OSError('Selected-file copy made no progress.')
                            view = view[count:]
                        checkpoint('copying', path)
                    checkpoint('copied', path)
                    second = _hash(source, initial.st_size, valid)
                    current, now = open_source(path, forbidden, permitted_private)
                    os.close(current)
                    if (total != initial.st_size or _identity(initial) != _identity(os.fstat(source))
                            or _identity(initial) != _identity(now) or digest.hexdigest() != second):
                        raise ValueError('The selected file changed or was replaced while being copied. Select the intended file again.')
                    os.fsync(target)
                    os.fchmod(target, 0o400)
                    _validate(target, path.suffix.lower())
                    _flags(target, stat.UF_IMMUTABLE)
                    _flags(job_fd, stat.UF_IMMUTABLE)
                    checkpoint('sealed', output)
                    held = os.fstat(target)
                    named = os.stat(path.name, dir_fd=job_fd, follow_symlinks=False)
                    if (not held.st_flags & stat.UF_IMMUTABLE or not os.fstat(job_fd).st_flags & stat.UF_IMMUTABLE
                            or (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino)
                            or _hash(target, initial.st_size, valid) != digest.hexdigest()):
                        raise ValueError('The staged selected-file snapshot changed before publication.')
                    # No writable descriptor is retained after sealing.
                    readonly = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=job_fd)
                    if _identity(os.fstat(readonly)) != _identity(held):
                        os.close(readonly)
                        raise ValueError('The staged selected-file identity changed.')
                    os.close(target); target = readonly
                    pending.append((target, output, initial.st_size, digest.hexdigest(), job_fd, (self.root_fd,)))
                    target = job_fd = None
                    reserved = False
                finally:
                    os.close(source)
                    try:
                        if target is not None:
                            item = (target, output, initial.st_size, '', job_fd, (self.root_fd,))
                            try: self._retire(item)
                            except (OSError, ValueError) as exc:
                                print('DLMS selected-file cleanup retained private path evidence: ' + str(exc), file=sys.stderr)
                            finally: reserved = False; target = job_fd = None
                        elif job_fd is not None:
                            os.close(job_fd); job_fd = None
                    finally:
                        if reserved:
                            _release(initial.st_size)
                            try: os.rmdir(name, dir_fd=self.root_fd)
                            except FileNotFoundError: pass
            if not valid():
                raise ValueError('The page changed during file selection. Choose files again on the intended page.')
            self._check_root()
            self.items.extend(pending)
            self.bytes += sum(item[2] for item in pending)
            return [str(item[1]) for item in pending]
        except BaseException:
            for item in pending:
                try: self._retire(item)
                except (OSError, ValueError) as exc:
                    print('DLMS selected-file cleanup retained private path evidence: ' + str(exc), file=sys.stderr)
            raise

    def discard(self, paths):
        with self._operation_lock:
            return self._discard(paths)

    def _discard(self, paths):
        failures = []
        for item in list(self.items):
            if str(item[1]) not in paths: continue
            self.items.remove(item); self.bytes -= item[2]
            try: self._retire(item)
            except (OSError, ValueError) as exc: failures.append(str(exc))
        return failures

    def close(self, *_):
        with self._operation_lock:
            self._close()

    def _close(self):
        if self.closed: return
        self.closed = True
        failures = self.discard([str(item[1]) for item in self.items])
        try:
            self._check_root()
            self.directory.rmdir()
        except (OSError, ValueError) as exc: failures.append(str(exc))
        finally: os.close(self.root_fd)
        if failures:
            print('DLMS selected-file cleanup retained private path evidence: ' + '; '.join(failures), file=sys.stderr)


# ApplicationWorld is isolated from page script. No web-callable native
# function is installed, and subframes cannot mint a top-level chooser lease.
SELECTION_SCRIPT = r"""(()=>{
 if(self!==top)return;
 let active=null;
 const inputFor=e=>{
   let x=e.target instanceof Element?e.target:null;
   if(x?.tagName==='LABEL')x=x.control;
   else if(x?.closest('label'))x=x.closest('label').control;
   return x?.tagName==='INPUT'&&x.type==='file'&&!x.disabled?x:null;
 };
 document.addEventListener('click',e=>{
   const x=inputFor(e);
   active=e.isTrusted&&!e.defaultPrevented&&x?{el:x,href:location.href,at:performance.now()}:null;
 },true);
 document.addEventListener('keydown',e=>{
   const x=inputFor(e);
   active=e.isTrusted&&!e.repeat&&!e.defaultPrevented&&['Enter',' '].includes(e.key)&&x?
     {el:x,href:location.href,at:performance.now()}:null;
 },true);
 document.addEventListener('visibilitychange',()=>{active=null;});
 Object.defineProperty(globalThis,'__dlmsFileTake',{value:()=>{
   const a=active;active=null;
   return !!(a&&a.el.isConnected&&!a.el.disabled&&a.el.type==='file'&&
     a.href===location.href&&performance.now()-a.at<5000);
 },writable:false});
})()"""


def install_selection_guard(page):
    from PySide6.QtWebEngineCore import QWebEngineScript
    script = QWebEngineScript()
    script.setName('dlms-private-file-activation')
    script.setWorldId(QWebEngineScript.ScriptWorldId.ApplicationWorld)
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setRunsOnSubFrames(False)
    script.setSourceCode(SELECTION_SCRIPT)
    page.scripts().insert(script)
    page._macos_selection_guard = True
    page._macos_file_used_epoch = 0


def _take_activation(page, valid):
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWebEngineCore import QWebEngineScript
    handoff = getattr(page, 'ai_handoff', None)
    if (not getattr(page, '_macos_selection_guard', False) or handoff is None
            or not handoff.epoch or handoff.epoch == page._macos_file_used_epoch
            or time.monotonic() - handoff.started > 5):
        return False
    epoch = handoff.epoch
    page._macos_file_used_epoch = epoch
    result = []
    loop = QEventLoop()
    timeout = QTimer(); timeout.setSingleShot(True); timeout.timeout.connect(loop.quit)
    def received(value):
        result.append(value is True); loop.quit()
    timeout.start(1000)
    page.runJavaScript('globalThis.__dlmsFileTake?.() === true',
                       QWebEngineScript.ScriptWorldId.ApplicationWorld, received)
    if not result: loop.exec()
    timeout.stop()
    return bool(result and result[0] and valid() and handoff.epoch == epoch)


def choose_files(page, mode, *, server=False):
    """Native Qt picker; exact consent and immutable copies belong to one page."""
    from PySide6.QtCore import QEventLoop, QTimer, Qt
    from PySide6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog
    from PySide6.QtWebEngineCore import QWebEnginePage
    from shiboken6 import isValid
    from .isolation import AREA
    owner = page.owner
    if mode not in (QWebEnginePage.FileSelectionMode.FileSelectOpen,
                    QWebEnginePage.FileSelectionMode.FileSelectOpenMultiple):
        return []
    view = owner.view
    generation = (owner._browser_generation, owner._settings_generation,
                  getattr(owner, '_server_navigation_serial', 0), page.document_generation)
    url = bytes(page.url().toEncoded())
    identity = (owner.manifest or {}).copy()
    canceled = threading.Event()
    captured = []

    def valid():
        # Called only on the GUI thread; worker receives cancellation Event.
        if (not isValid(page) or not isValid(view) or owner._closing or owner._close_after_dialog or owner.view is not view
                or view.page() is not page or owner._mode_switch_busy
                or page.isLoading()
                or any(getattr(owner, key, False) for key in ('_settings_action_busy', '_backup_creating', '_close_active'))
                or owner.mode != ('server' if server else 'local')
                or generation != (owner._browser_generation,owner._settings_generation,
                                  getattr(owner, '_server_navigation_serial', 0), page.document_generation)
                or bytes(page.url().toEncoded()) != url or (owner.manifest or {}) != identity):
            return False
        if server:
            from .server_browser import exact_server_origin
            return not owner.server_unreachable and exact_server_origin(page.url(), page.origin)
        from .shell import allowed_internal
        return (owner.backend is not None and owner.backend.poll() is None
                and allowed_internal(page.url(), owner.port) and not owner.maintenance_transition
                and not owner.import_in_progress and not owner._settings_transition_refused)

    if not valid() or getattr(owner, '_file_selection_active', False): return []
    if owner.file_selection_for_test is None and not _take_activation(page, valid):
        owner.statusBar().showMessage('File selection refused: use this page’s file button directly.')
        return []
    owner._file_selection_active = True
    focus = owner.focusWidget()
    try:
        selected = owner.file_selection_for_test
        if selected is not None:
            owner.file_selection_for_test = None
            choices = [str(p) for p in selected] if isinstance(selected, (list,tuple)) else [str(selected)]
        else:
            from .exports import initial
            previous, warning = initial(owner, 'upload')
            start = str(previous)
            if warning: owner.statusBar().showMessage(warning)
            filters = 'Supported files (*.txt *.csv *.pdf *.zip *.png *.jpg *.jpeg *.webp *.gif);;All files (*)'
            title = 'Choose files for ' + (f'Server {page.origin}' if server else f'Local profile {owner.profile_name}')
            if mode == QWebEnginePage.FileSelectionMode.FileSelectOpenMultiple:
                choices, _ = QFileDialog.getOpenFileNames(owner, title, start, filters)
            else:
                choice, _ = QFileDialog.getOpenFileName(owner, title, start, filters)
                choices = [choice] if choice else []
        if not choices:
            owner.statusBar().showMessage('File selection canceled. No new files were selected or submitted.')
            return []
        if not valid(): return []
        from .isolation import PROJECT
        from .macos_paths import real_home
        home = real_home()
        forbidden = (AREA, home/'Library', *(home/name for name in ('.ssh', '.aws', '.codex', '.agents', '.gnupg', '.config')), PROJECT/'.git')
        permitted_private = () if server else (owner.paths['tmp'], owner.paths['downloads'])
        if len(choices) > MAX_FILES: raise ValueError('Select at most 25 files.')
        expected = []
        for choice in choices:
            descriptor, info = open_source(Path(choice), forbidden, permitted_private)
            captured.append((descriptor, info))
            expected.append(_identity(info))
        if server:
            prompt = QMessageBox(owner)
            prompt.setWindowTitle('Allow selected files for this Server?')
            prompt.setTextFormat(Qt.TextFormat.PlainText)
            prompt.setText(f'{page.origin}\n\n' + '\n'.join(Path(p).name for p in choices) +
                '\n\nThese selected copies become readable by this Server session, including its page content. It may upload them immediately. Local data and recovery files remain private. Continue only if you trust this exact destination.')
            prompt.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
            prompt.setDefaultButton(QMessageBox.StandardButton.Cancel)
            answer = prompt.exec()
            if not valid(): return []
            if answer != QMessageBox.StandardButton.Yes:
                owner.statusBar().showMessage('Server file access canceled. No new files were selected or submitted.')
                return []
        root = owner.server_paths['root'] if server else owner.paths['tmp']
        if not hasattr(page, '_selected_snapshots'):
            page._selected_snapshots = Snapshots(root)
            page.destroyed.connect(page._selected_snapshots.close)
        progress = QProgressDialog('Preparing private selected-file copies…', 'Cancel selection', 0, 0, owner)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(150)
        progress.canceled.connect(canceled.set)
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='dlms-file-selection')
        future = pool.submit(page._selected_snapshots.stage, choices, forbidden=forbidden, permitted_private=permitted_private, expected=expected, captured=captured, valid=lambda: not canceled.is_set())
        loop = QEventLoop()
        timer = QTimer(); timer.setInterval(30)
        def poll():
            if not valid(): canceled.set()
            if future.done(): loop.quit()
        timer.timeout.connect(poll); timer.start()
        show_timer = QTimer(progress); show_timer.setSingleShot(True)
        show_timer.timeout.connect(lambda: progress.show() if not future.done() else None)
        show_timer.start(150)
        try:
            loop.exec()
            result = future.result()
            if not valid() or canceled.is_set():
                page._selected_snapshots.discard(result)
                if valid(): owner.statusBar().showMessage('File selection canceled. No new files were selected or submitted.')
                return []
            try:
                from .exports import remember
                remember(owner, Path(choices[0]).parent, 'upload')
            except (OSError,ValueError):
                pass  # A selected snapshot remains valid if preference storage fails.
            owner.statusBar().showMessage('Selected private copies are ready for this form. Submit/review to save; choosing files alone does not save application data.')
            return result
        finally:
            show_timer.stop(); timer.stop()
            # QProgressDialog.close() emits canceled even for our own teardown.
            # Detach first so a validation/write failure stays a failure.
            progress.canceled.disconnect(canceled.set)
            progress.close(); progress.deleteLater(); pool.shutdown(wait=True)
    except Exception as exc:
        if not valid(): return []
        if canceled.is_set():
            owner.statusBar().showMessage('File selection canceled. No new files were selected or submitted.')
            return []
        message = f'File selection refused: {exc}. No selected files were submitted.'
        owner.statusBar().showMessage(message)
        prompt = QMessageBox(owner)
        prompt.setWindowTitle('Files not selected'); prompt.setTextFormat(Qt.TextFormat.PlainText)
        prompt.setIcon(QMessageBox.Icon.Warning); prompt.setText(message)
        prompt.exec()
        return []
    finally:
        for descriptor, _ in captured: os.close(descriptor)
        owner._file_selection_active = False
        if valid():
            if focus is not None:
                focus.setFocus(Qt.FocusReason.OtherFocusReason)
            else:
                view.setFocus(Qt.FocusReason.OtherFocusReason)
