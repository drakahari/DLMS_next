"""Single-process portal read/modify/write serialization regressions."""
import json
import threading
from unittest import mock

import pytest
from tests._isolation import ensure_test_data_isolation

ensure_test_data_isolation()
import app as dlms


@pytest.mark.parametrize("path_name,loader", [
    ("PORTAL_CONFIG", "load_portal_config"),
    ("LAW_REGISTRY", "load_law_registry"),
])
def test_default_creation_joins_configuration_lock(tmp_path, path_name, loader):
    path = tmp_path / "config.json"
    started = threading.Event()
    completed = threading.Event()
    errors = []
    def read():
        started.set()
        try:
            getattr(dlms, loader)()
        except BaseException as exc:
            errors.append(exc)
        finally:
            completed.set()
    with mock.patch.object(dlms, path_name, str(path)):
        worker = threading.Thread(target=read)
        with dlms.registry_lock:
            worker.start()
            assert started.wait(2)
            blocked = not completed.wait(0.15)
            absent = not path.exists()
        worker.join(3)
        assert not worker.is_alive() and not errors
        assert blocked and absent
        assert isinstance(json.loads(path.read_text()), dict)


@pytest.mark.parametrize("second_path,form,expected", [
    ("/settings/parsing/save", {"enable_regex_replace": "on"}, "parsing"),
    ("/add_quiz_folder", {"folder": "New Course"}, "folder"),
])
def test_settings_snapshot_cannot_overwrite_concurrent_changes(tmp_path, second_path, form, expected):
    portal = tmp_path / "portal.json"
    registry = tmp_path / "quizzes.json"
    portal.write_text(json.dumps({"theme": "dark", "quiz_folders": ["Uncategorized"],
                                 "unknown": {"preserve": True}}))
    registry.write_text("[]")
    first_read = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    second_read = threading.Event()
    errors = []
    original_load = dlms.load_portal_config

    def load():
        data = original_load()
        if threading.current_thread().name == "first-config":
            first_read.set()
            if not release_first.wait(3):
                raise TimeoutError("test did not release settings read")
        else:
            second_read.set()
        return data

    def post(path, data):
        try:
            if threading.current_thread().name == "second-config":
                second_entered.set()
            client = dlms.app.test_client()
            response = client.post(path, data=data)
            assert response.status_code in (200, 302)
            response.close()
        except BaseException as exc:
            errors.append(exc)

    with mock.patch.object(dlms, "PORTAL_CONFIG", str(portal)), \
            mock.patch.object(dlms, "QUIZ_REGISTRY", str(registry)), \
            mock.patch.dict(dlms.app.config, {"WTF_CSRF_ENABLED": False}), \
            mock.patch.object(dlms, "load_portal_config", side_effect=load):
        first = threading.Thread(target=post, args=("/api/theme", {"theme": "light"}), name="first-config")
        second = threading.Thread(target=post, args=(second_path, form), name="second-config")
        first.start()
        try:
            assert first_read.wait(2)
            second.start()
            assert second_entered.wait(2)
            assert not second_read.wait(0.15), "another writer read a stale snapshot concurrently"
        finally:
            release_first.set()
            first.join(3)
            if second.ident is not None:
                second.join(3)
        assert not first.is_alive() and not second.is_alive()
        assert not errors
    saved = json.loads(portal.read_text())
    assert saved["theme"] == "light"
    assert saved["unknown"] == {"preserve": True}
    if expected == "folder":
        assert "New Course" in saved["quiz_folders"]
    else:
        assert saved["enable_regex_replace"] is True


@pytest.mark.parametrize("operation,service", [
    (lambda: dlms._run_reset_with_backup("test", lambda: None), "run_reset_with_backup"),
    (lambda: dlms._complete_staged_restore("test"), "complete_staged_restore"),
])
def test_replacement_uses_same_lock_and_releases_after_failure(operation, service):
    order = []
    class Lock:
        def __init__(self, name):
            self.name = name
        def __enter__(self):
            order.append(self.name)
        def __exit__(self, *args):
            assert order.pop() == self.name
    def fail(*args, **kwargs):
        assert order == ["restore", "registry"]
        raise OSError("simulated failure")
    with mock.patch.object(dlms, "RESTORE_OPERATION_LOCK", Lock("restore")), \
            mock.patch.object(dlms, "registry_lock", Lock("registry")), \
            mock.patch.object(dlms._restore_service, service, side_effect=fail):
        with pytest.raises(OSError, match="simulated failure"):
            operation()
    assert order == []


def test_settings_failure_does_not_publish_or_hold_lock(tmp_path):
    portal = tmp_path / "portal.json"
    original = '{"theme":"dark","unknown":42}'
    portal.write_text(original)
    with mock.patch.object(dlms, "PORTAL_CONFIG", str(portal)), \
            mock.patch.dict(dlms.app.config, {"WTF_CSRF_ENABLED": False}), \
            mock.patch.object(dlms, "_write_settings_portal_config", side_effect=OSError("disk fault")):
        response = dlms.app.test_client().post("/api/theme", data={"theme": "light"})
        assert response.status_code == 500
        response.close()
    assert portal.read_text() == original
    acquired = []
    def acquire():
        if dlms.registry_lock.acquire(timeout=1):
            acquired.append(True)
            dlms.registry_lock.release()
    worker = threading.Thread(target=acquire)
    worker.start()
    worker.join(2)
    assert not worker.is_alive() and acquired == [True]


def test_law_registry_cancellation_cannot_undo_concurrent_case_delete(tmp_path):
    registry = tmp_path / "law.json"
    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "case-one.json").write_text('{"title":"Example"}')
    registry.write_text(json.dumps({"cases": [{"id": "case-one", "file": "case-one.json"}],
                                    "folders": ["Torts"], "pending_case_workflow": {"name": "Example"}}))
    read = threading.Event()
    release = threading.Event()
    entered = threading.Event()
    second_read = threading.Event()
    errors = []
    original_load = dlms.load_law_registry
    def load():
        value = original_load()
        if threading.current_thread().name == "cancel":
            read.set()
            if not release.wait(3):
                raise TimeoutError("test did not release Law read")
        else:
            second_read.set()
        return value
    def post(path):
        try:
            if threading.current_thread().name == "delete":
                entered.set()
            response = dlms.app.test_client().post(path)
            assert response.status_code == 302
            response.close()
        except BaseException as exc:
            errors.append(exc)
    with mock.patch.object(dlms, "LAW_REGISTRY", str(registry)), \
            mock.patch.object(dlms, "LAW_CASES_FOLDER", str(cases)), \
            mock.patch.object(dlms, "load_law_registry", side_effect=load), \
            mock.patch.dict(dlms.app.config, {"WTF_CSRF_ENABLED": False}):
        first = threading.Thread(target=post, args=("/law/workflow/cancel",), name="cancel")
        second = threading.Thread(target=post, args=("/law/cases/case-one/delete",), name="delete")
        first.start()
        try:
            assert read.wait(2)
            second.start()
            assert entered.wait(2)
            assert not second_read.wait(0.15)
        finally:
            release.set()
            first.join(3)
            if second.ident is not None:
                second.join(3)
        assert not first.is_alive() and not second.is_alive()
        assert not errors
    saved = json.loads(registry.read_text())
    assert saved["cases"] == []
    assert "pending_case_workflow" not in saved
    assert not (cases / "case-one.json").exists()
