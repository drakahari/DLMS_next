"""Reset outcome classification must not hide mutation behind ownership errors."""
import pytest
from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app
from dlms.services import restore


@pytest.mark.parametrize("backup", ["/private/pre-reset-safe.zip", "/private/unsafe\nname.zip"])
def test_ownership_failure_after_reset_entry_reports_possible_changes(tmp_path, backup):
    source = tmp_path / "synthetic-source.txt"
    source.write_bytes(b"retained before reset")
    failure = restore.DataRootOwnershipError("private diagnostic " + str(tmp_path))
    def partial():
        source.unlink()
        raise failure
    with pytest.raises(restore.DataRootOwnershipError) as caught:
        restore.run_reset_with_backup("test", partial, require_owned_root=lambda _: None,
                                     create_backup=lambda _: (backup, {}))
    assert caught.value is failure and not source.exists()
    message, status = app._destructive_operation_error(failure, "reset")
    assert status == 500 and "No destructive action was authorized" not in message
    assert "changes may already have occurred" in message or "data may already have changed" in message
    assert str(tmp_path) not in message and "unsafe\nname.zip" not in message
    if "safe.zip" in backup:
        assert "Retained safety backup: pre-reset-safe.zip" in message
        assert "No automatic rollback is confirmed" in message


def test_ownership_preflight_refusal_remains_no_mutation(tmp_path):
    source = tmp_path / "untouched.txt"
    source.write_bytes(b"unchanged")
    failure = restore.DataRootOwnershipError("owned-root preflight refused")
    def refuse(_): raise failure
    with pytest.raises(restore.DataRootOwnershipError) as caught:
        restore.run_reset_with_backup("test", lambda: source.unlink(), require_owned_root=refuse,
                                     create_backup=lambda _: pytest.fail("Backup after failed authorization"))
    assert caught.value is failure and source.read_bytes() == b"unchanged"
    message, status = app._destructive_operation_error(failure, "reset")
    assert status == 409 and "No destructive action was authorized" in message
