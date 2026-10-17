"""Explicit Linux browser file selection with page-owned immutable snapshots.

The chooser grants access to selected bytes, not to an ordinary directory.
These are ephemeral browser File inputs, not durable application acknowledgments.
Backend workflow validators and publication/recovery contracts remain authoritative.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import os
from pathlib import Path
import secrets
import stat
import tempfile
import threading
import zipfile

MIB = 1024 * 1024
LIMITS = {'.txt': 16*MIB, '.csv': 16*MIB, '.pdf': 64*MIB, '.zip': 256*MIB,
          **{suffix: 32*MIB for suffix in ('.png', '.jpg', '.jpeg', '.webp', '.gif')}}
PAGE_LIMIT = 384*MIB
PROCESS_LIMIT = 768*MIB
MAX_FILES = 25
MAX_RETAINED_FILES = 256
CHUNK = MIB
_SEALS = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
_lock = threading.Lock()
_retained = 0


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


def open_source(path: Path, forbidden=(), permitted_private=()):
    """Pin every directory; never follow an input symlink or block on a FIFO."""
    if (path.anchor != '/' or '..' in path.parts or path.suffix.lower() not in LIMITS
            or any(ord(char) < 32 or ord(char) == 127 for char in path.name)):
        raise ValueError('Choose a local TXT, CSV, PDF, ZIP, PNG, JPEG, GIF or WebP file supported by this form.')
    if (any(path == root or path.is_relative_to(root) for root in forbidden)
            and not any(path.is_relative_to(root) for root in permitted_private)):
        raise ValueError('Desktop private data and browser/recovery files cannot be selected. Export a supported file to an ordinary folder first.')
    directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parent.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
    finally:
        os.close(directory)
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
            or not info.st_mode & 0o444 or info.st_size <= 0 or info.st_size > LIMITS[path.suffix.lower()]):
        os.close(fd)
        raise ValueError('Choose a readable, nonempty regular file owned by you, within this form’s file-size limit. Symbolic/hard links and special files are not supported.')
    return fd, info


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
    with open(f'/proc/self/fd/{fd}', 'rb') as stream:
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
    """One page owns all its File objects until actual WebEngine destruction."""
    def __init__(self, root: Path):
        # Parent is an already validated Desktop-owned temp/root directory.
        self.directory = Path(tempfile.mkdtemp(prefix='selected-files-', dir=root))
        self.items = []
        self.bytes = 0
        self.closed = False

    def stage(self, choices, *, forbidden=(), permitted_private=(), expected=None, valid=lambda: True, checkpoint=lambda phase, path: None):
        if self.closed or not 0 < len(choices) <= MAX_FILES:
            raise ValueError('Select between one and 25 supported files.')
        if len(self.items) + len(choices) > MAX_RETAINED_FILES:
            raise ValueError('Too many selected files remain open in this page. Close and reopen the window before selecting more.')
        pending = []
        try:
            for index, selected in enumerate(choices):
                if not valid():
                    raise ValueError('File selection canceled or its page changed. No selected files were submitted.')
                path = Path(selected)
                source, initial = open_source(path, forbidden, permitted_private)
                if expected is not None and _identity(initial) != expected[index]:
                    os.close(source)
                    raise ValueError('The selected file changed or was replaced after selection. Choose it again.')
                target = None
                reserved = False
                job = self.directory / secrets.token_hex(16)
                try:
                    if self.bytes + sum(item[2] for item in pending) + initial.st_size > PAGE_LIMIT:
                        raise ValueError('Selected file data exceeds the 384 MiB page limit. Close and reopen the window before choosing more files.')
                    _reserve(initial.st_size); reserved = True
                    target = os.memfd_create('dlms-selected-file', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
                    os.fchmod(target, 0o400)
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
                            view = view[count:]
                        checkpoint('copying', path)
                    checkpoint('copied', path)
                    second = _hash(source, initial.st_size, valid)
                    current, now = open_source(path, forbidden, permitted_private)
                    os.close(current)
                    if (total != initial.st_size or _identity(initial) != _identity(os.fstat(source))
                            or _identity(initial) != _identity(now) or digest.hexdigest() != second):
                        raise ValueError('The selected file changed or was replaced while being copied. Select the intended file again.')
                    fcntl.fcntl(target, fcntl.F_ADD_SEALS, _SEALS)
                    _validate(target, path.suffix.lower())
                    job.mkdir(mode=0o700)
                    link = job / path.name
                    # The only permitted link is ours, pointing at a held sealed
                    # descriptor; user-supplied links are always rejected above.
                    link.symlink_to(f'/proc/{os.getpid()}/fd/{target}')
                    pending.append((target, link, initial.st_size, digest.hexdigest()))
                    target = None
                    reserved = False
                finally:
                    os.close(source)
                    if target is not None: os.close(target)
                    if reserved: _release(initial.st_size)
                    if job.exists() and not any(job.iterdir()): job.rmdir()
            if not valid():
                raise ValueError('The page changed during file selection. Choose files again on the intended page.')
            self.items.extend(pending)
            self.bytes += sum(item[2] for item in pending)
            return [str(item[1]) for item in pending]
        except BaseException:
            for fd, link, size, _ in pending:
                try:
                    link.unlink(missing_ok=True)
                    if not any(link.parent.iterdir()): link.parent.rmdir()
                except OSError as exc:
                    import sys
                    print('DLMS selected-file cleanup retained private path evidence: ' + str(exc), file=sys.stderr)
                finally:
                    os.close(fd); _release(size)
            raise

    def discard(self, paths):
        """Retire only a batch never handed to the renderer; keep prior Files."""
        failures = []
        for item in list(self.items):
            fd, link, size, _ = item
            if str(link) not in paths: continue
            self.items.remove(item); self.bytes -= size
            try:
                link.unlink(missing_ok=True)
                if not any(link.parent.iterdir()): link.parent.rmdir()
            except OSError as exc:
                failures.append(str(exc))
            finally:
                os.close(fd); _release(size)
        return failures

    def close(self, *_):
        if self.closed: return
        self.closed = True
        failures = self.discard([str(item[1]) for item in self.items])
        try:
            if not any(self.directory.iterdir()): self.directory.rmdir()
        except OSError as exc:
            failures.append(str(exc))
        if failures:
            import sys
            print('DLMS selected-file cleanup retained private path evidence: ' + '; '.join(failures), file=sys.stderr)


def choose_files(page, mode, *, server=False):
    """Qt-only capability, never a web-callable bridge or directory grant."""
    from PySide6.QtCore import QEventLoop, QTimer, Qt
    from PySide6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog
    from PySide6.QtWebEngineCore import QWebEnginePage
    from .isolation import AREA
    owner = page.owner
    if mode not in (QWebEnginePage.FileSelectionMode.FileSelectOpen,
                    QWebEnginePage.FileSelectionMode.FileSelectOpenMultiple):
        return []
    view = owner.view
    generation = (owner._browser_generation, owner._settings_generation,
                  getattr(owner, '_server_navigation_serial', 0))
    url = bytes(page.url().toEncoded())
    identity = (owner.manifest or {}).copy()
    canceled = threading.Event()

    def valid():
        # Called only on the GUI thread; worker receives cancellation Event.
        if (owner._closing or owner._close_after_dialog or owner.view is not view
                or view.page() is not page or owner._mode_switch_busy
                or owner.mode != ('server' if server else 'local')
                or generation != (owner._browser_generation,owner._settings_generation,
                                  getattr(owner, '_server_navigation_serial', 0))
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
        forbidden = (AREA/'profiles', AREA/'shell', AREA/'server-profiles')
        permitted_private = () if server else (owner.paths['tmp'], owner.paths['downloads'])
        if len(choices) > MAX_FILES: raise ValueError('Select at most 25 files.')
        expected = []
        for choice in choices:
            descriptor, info = open_source(Path(choice), forbidden, permitted_private)
            os.close(descriptor)
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
        future = pool.submit(page._selected_snapshots.stage, choices, forbidden=forbidden, permitted_private=permitted_private, expected=expected, valid=lambda: not canceled.is_set())
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
        owner._file_selection_active = False
        if valid():
            if focus is not None:
                focus.setFocus(Qt.FocusReason.OtherFocusReason)
            else:
                view.setFocus(Qt.FocusReason.OtherFocusReason)
