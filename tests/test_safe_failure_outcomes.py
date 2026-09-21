"""DLMS-142/143 outcome evidence and sanitized user guidance."""
import inspect
from unittest.mock import Mock, patch

import pytest
from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms
from dlms.services import restore, storage_health


@pytest.mark.parametrize("failure,outcome", [
    ("before", "not_modified"), ("rollback", "rolled_back"),
    ("incomplete", "recovery_required"), ("preserve", "restored"),
    ("checkpoint", "recovery_required"),
])
def test_restore_outcome_follows_recovery_result(tmp_path, failure, outcome):
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "restore.zip").write_bytes(b"fixture")
    safety = tmp_path / "safety.zip"
    journal = tmp_path / "journal.json"
    callbacks = {name: Mock() for name in inspect.signature(restore.complete_staged_restore).parameters
                 if name not in {"token", "db_path"}}
    callbacks["restore_staging_dir"].return_value = str(stage)
    callbacks["validate_backup"].return_value = {"manifest": {}, "uncompressed_bytes": 7}
    def backup(*args):
        safety.write_bytes(b"preserved safety")
        return str(safety), {"total_uncompressed_bytes": safety.stat().st_size}
    def operation(*args, **kwargs):
        journal.write_text("{}")
        return str(journal), {}
    callbacks["create_backup"].side_effect = backup
    callbacks["new_operation"].side_effect = operation
    callbacks["read_journal"].return_value = ({}, {})
    callbacks["recover_one"].return_value = "preserved" if failure == "preserve" else "rolled_back"
    private = 'private /account <script>secret()</script>'
    if failure == "before":
        callbacks["validate_semantics"].side_effect = ValueError(private)
    else:
        callbacks["apply_data"].side_effect = OSError(private)
    if failure in {"incomplete", "checkpoint"}:
        callbacks["recover_one"].side_effect = OSError(private)
    if failure == "checkpoint":
        callbacks["checkpoint"].side_effect = OSError(private)
    # These cases test restore phases, not the host's available disk capacity.
    # Keep the real preflight, supplying a deterministic healthy filesystem.
    with patch.object(storage_health, "available_space", return_value=(1024**4, 1024**4)), \
         patch.object(storage_health, "require_capacity", wraps=storage_health.require_capacity) as capacity:
        with pytest.raises(restore.RestoreFailure) as caught:
            restore.complete_staged_restore("token", db_path=str(tmp_path / "results.db"), **callbacks)
    assert capacity.call_count == (1 if failure == "before" else 2)
    callbacks["extract_backup"].assert_called_once()
    callbacks["validate_semantics"].assert_called_once()
    assert caught.value.outcome == outcome
    message, status = dlms._settings_restore_error(caught.value)
    assert private not in message and "<script>" not in message
    assert status == (400 if failure == "before" else 500)
    if failure == "before":
        callbacks["prepare_database"].assert_not_called()
        callbacks["create_backup"].assert_not_called()
        callbacks["recover_one"].assert_not_called()
        callbacks["apply_data"].assert_not_called()
        assert "before changing live data" in message
    elif failure == "rollback":
        assert "successfully restored the pre-restore snapshot" in message
    elif failure in {"incomplete", "checkpoint"}:
        assert safety.exists() and journal.exists()
        assert "Recovery is still required" in message
        assert "safety backup" in message and "recovery journal" in message
        assert "restart" in message and "do not delete" in message
        assert "successfully" not in message and "preserved or" not in message
        if failure == "checkpoint":
            callbacks["apply_data"].assert_not_called()
    else:
        assert "retained the restored data" in message
    if failure != "before":
        callbacks["prepare_database"].assert_called_once()
        callbacks["create_backup"].assert_called_once()
        callbacks["new_operation"].assert_called_once()
        callbacks["recover_one"].assert_called_once()
        if failure != "checkpoint":
            callbacks["apply_data"].assert_called_once()


def test_unknown_restore_failure_never_claims_recovery():
    message, _ = dlms._settings_restore_error(RuntimeError("private token"))
    assert "could not confirm" in message
    assert "private token" not in message
    assert "preserved or rolled back" not in message


def test_failure_template_still_escapes_html():
    with dlms.app.test_request_context():
        page = dlms.render_template("settings/restore-failed.html", error='<img id="injected">')
    assert '<img id="injected">' not in page
    assert "&lt;img" in page


def test_destructive_error_is_static_and_safe():
    message, status = dlms._destructive_operation_error(OSError("secret path"), "<script>secret</script>")
    assert status == 500 and "Some changes may already" in message
    assert "secret" not in message and "log" not in message


def test_history_and_pack_failures_are_actionable():
    from dlms.routes import history, content_packs
    from types import SimpleNamespace
    with dlms.app.test_request_context():
        result, status = history.clear_db_history(SimpleNamespace(clear_persistent_history=Mock(side_effect=OSError("private"))))
        assert status == 500 and "Restart DLMS" in result["error"]
        assert "private" not in result["error"]
        with patch.object(content_packs, "flash") as flash:
            content_packs.content_pack_details(SimpleNamespace(content_pack_folder_report=Mock(side_effect=OSError("private"))), "demo")
        assert "Restart DLMS" in flash.call_args.args[0]
        assert "private" not in flash.call_args.args[0]
