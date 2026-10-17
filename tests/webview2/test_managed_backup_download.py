"""Managed Local backup transfer uses its selected operation, not Qt-page state."""
from enum import Enum
from pathlib import Path
from types import SimpleNamespace as NS

from PySide6.QtCore import QUrl
import pytest

from desktop.operation_feedback import OperationFeedback
from desktop.shell import DesktopWindow


class Signal:
    def __init__(self): self.callbacks = []
    def connect(self, callback): self.callbacks.append(callback)
    def emit(self, *args):
        for callback in self.callbacks: callback(*args)


class Request:
    class DownloadState(Enum):
        DownloadRequested = 0
        DownloadCompleted = 1
        DownloadCancelled = 2
        DownloadInterrupted = 3

    def __init__(self, page, token="selected-operation"):
        self.owner_page = page
        self.address = QUrl("http://127.0.0.1:42424/settings/backup/create?desktop_output=" + token)
        self.current = self.DownloadState.DownloadRequested
        self.isFinishedChanged, self.stateChanged = Signal(), Signal()
        self.accepted = self.cancelled = False
    def page(self): return self.owner_page
    def url(self): return self.address
    def downloadFileName(self): return "selected backup 日本語.zip"
    def setDownloadDirectory(self, value): self.directory = value
    def setDownloadFileName(self, value): self.filename = value
    def accept(self): self.accepted = True
    def cancel(self): self.cancelled = True
    def state(self): return self.current
    def interruptReasonString(self): return "Synthetic interrupted backup"
    def terminal(self, state):
        self.current = state
        self.stateChanged.emit(state)
        self.isFinishedChanged.emit()


@pytest.fixture
def backup(tmp_path):
    staging = tmp_path / "private downloads"; staging.mkdir(mode=0o700)
    # Native WebView2 LocalPage has no Qt document_generation attribute.
    page = NS()
    feedback, messages, submitted, timers = OperationFeedback(), [], [], []
    ticket = feedback.begin("backup")
    selection = {"operation": "selected-operation", "path": str(tmp_path / "chosen backup.zip"),
                 "synthetic-selection-marker": "same exact native selection"}
    future = object()
    def submit(function, *args):
        submitted.append((function, args)); return future
    def update(ticket, message, severity="info"):
        if feedback.update(ticket, message, severity): messages.append((message, severity))
    owner = NS(mode="local", port=42424, _closing=False, _retiring_browser=None,
               _browser_generation=1, manifest={"uuid": "synthetic", "epoch": 1},
               view=NS(page=lambda: page, url=lambda: QUrl("http://127.0.0.1:42424/")),
               paths={"downloads": staging, "root": tmp_path}, backup_output_selection=selection,
               backup_output_operation=selection["operation"], _backup_creating=True,
               _backup_feedback_ticket=ticket, backup_output_future=None,
               backup_selection_executor=NS(submit=submit),
               backup_output_timer=NS(start=lambda: timers.append(True)), download_results=[],
               _begin_feedback=feedback.begin, _feedback=update,
               _settings_ready=lambda *args: False, statusBar=lambda: NS(showMessage=messages.append))
    return NS(owner=owner, page=page, selection=dict(selection), future=future,
              submitted=submitted, timers=timers, feedback=feedback, messages=messages)


def test_bound_native_backup_accepts_page_without_qt_generation_and_publishes_exact_selection(backup, monkeypatch):
    def refuse_qt_export(*args, **kwargs):
        raise AssertionError("Managed backup must never enter the ordinary Qt export lifecycle")
    for name in ("context", "current", "begin"):
        monkeypatch.setattr("desktop.exports." + name, refuse_qt_export)
    request = Request(backup.page)
    DesktopWindow._download(backup.owner, request)
    assert request.accepted and not request.cancelled
    assert backup.owner.backup_output_selection is None
    request.terminal(Request.DownloadState.DownloadCompleted)
    from desktop.backup_output import publish
    assert len(backup.submitted) == 1
    function, (destination, selected) = backup.submitted[0]
    assert function is publish and selected == backup.selection
    assert destination == Path(request.directory) / request.filename
    assert destination.is_relative_to(backup.owner.paths["downloads"])
    assert selected is not backup.selection
    assert backup.owner.backup_output_future is backup.future
    assert backup.timers == [True]
    request.terminal(Request.DownloadState.DownloadCompleted)
    assert len(backup.submitted) == 1


@pytest.mark.parametrize("terminal,state", [
    (Request.DownloadState.DownloadCancelled, "cancelled"),
    (Request.DownloadState.DownloadInterrupted, "interrupted"),
])
@pytest.mark.parametrize("newer_feedback", [False, True])
def test_bound_backup_failure_is_terminal_without_overwriting_newer_feedback(backup, terminal, state, newer_feedback):
    request = Request(backup.page)
    DesktopWindow._download(backup.owner, request)
    if newer_feedback:
        current = backup.feedback.begin("newer-action")
        backup.feedback.update(current, "Newer outcome must remain visible", "success")
    request.terminal(terminal)
    assert backup.owner.download_results[0]["state"] == state
    assert backup.owner._backup_creating is False
    assert not backup.submitted
    message = backup.feedback.message
    request.terminal(Request.DownloadState.DownloadCompleted)
    assert backup.owner.download_results[0]["state"] == state and not backup.submitted
    assert backup.feedback.message == message
    if newer_feedback: assert message == "Newer outcome must remain visible"
    else: assert "no selected file was published" in message


def test_changed_backup_operation_cannot_publish_or_consume_new_selection(backup):
    request = Request(backup.page)
    DesktopWindow._download(backup.owner, request)
    newer = dict(backup.selection, operation="newer-operation")
    backup.owner.backup_output_operation = newer["operation"]
    backup.owner.backup_output_selection = newer
    request.terminal(Request.DownloadState.DownloadCompleted)
    assert backup.owner.download_results[0]["state"] == "unconfirmed_old_operation"
    assert not backup.submitted and backup.owner.backup_output_selection is newer


def test_completed_backup_without_active_publication_stays_private(backup, monkeypatch):
    def refuse_qt_export(*args, **kwargs):
        raise AssertionError("Managed backup must not fall through to ordinary export publication")
    for name in ("context", "current", "begin"):
        monkeypatch.setattr("desktop.exports." + name, refuse_qt_export)
    request = Request(backup.page)
    DesktopWindow._download(backup.owner, request)
    backup.owner._backup_creating = False
    request.terminal(Request.DownloadState.DownloadCompleted)
    assert backup.owner.download_results[0]["state"] == "completed_private"
    assert not backup.submitted


@pytest.mark.parametrize("invalid", ["wrong-token", "missing-selection", "foreign-page", "foreign-origin", "server"])
def test_unbound_or_foreign_backup_request_is_refused_without_claiming_selection(backup, invalid):
    request = Request(backup.page)
    if invalid == "wrong-token": request.address.setQuery("desktop_output=unselected-operation")
    elif invalid == "missing-selection": backup.owner.backup_output_selection = None
    elif invalid == "foreign-page": request.owner_page = NS()
    elif invalid == "foreign-origin": request.address.setHost("foreign.invalid")
    elif invalid == "server": backup.owner.mode = "server"
    before = backup.owner.backup_output_selection
    DesktopWindow._download(backup.owner, request)
    assert request.cancelled and not request.accepted
    assert backup.owner.backup_output_selection is before
    assert not backup.owner.download_results and not backup.submitted


def test_webview2_unbound_unqueried_backup_never_becomes_an_ordinary_export(backup):
    from desktop.webview2_shell import DesktopWindow as WebView2Window
    request = Request(backup.page)
    request.address.setQuery("")
    backup.owner.backup_output_selection = None
    backup.owner._backup_creating = False
    WebView2Window._download(backup.owner, request)
    assert request.cancelled and not request.accepted
    assert not backup.owner.download_results and not backup.submitted


@pytest.mark.parametrize("navigated", [False, True])
def test_ordinary_qt_export_still_captures_and_checks_document_generation(backup, monkeypatch, navigated):
    backup.page.document_generation = 0
    backup.owner._browser_generation = 1
    backup.owner.manifest = {"uuid": "synthetic", "epoch": 1}
    backup.owner.paths["root"] = backup.owner.paths["downloads"].parent
    request = Request(backup.page)
    request.address = QUrl("http://127.0.0.1:42424/export/quiz/1.txt")
    invoked = []
    def begin(owner, record, *, captured):
        assert owner is backup.owner and captured[0] is backup.page and captured[5] == 0
        record["native_export"] = True
        invoked.append(True)
    monkeypatch.setattr("desktop.exports.begin", begin)
    DesktopWindow._download(backup.owner, request)
    assert request.accepted
    if navigated: backup.page.document_generation += 1
    request.terminal(Request.DownloadState.DownloadCompleted)
    if navigated:
        assert backup.owner.download_results[0]["state"] == "completed_private" and not invoked
    else:
        assert backup.owner.download_results[0]["native_export"] is True and invoked == [True]
    assert not backup.submitted
