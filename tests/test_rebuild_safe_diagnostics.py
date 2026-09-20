"""Actionable maintenance diagnostics without leaking exception data."""
from contextlib import nullcontext
from unittest.mock import Mock

import pytest

from dlms.services.quiz_mutations import rebuild_registered_quiz_artifacts


@pytest.mark.parametrize('error,expected', [
    (PermissionError('/private/account'), 'write permissions'),
    (OSError('/private/account'), 'disk space'),
    (ValueError('sensitive content'), 'missing or invalid'),
    (RuntimeError('SQL and private content'), 'report this quiz ID'),
])
def test_safe_rebuild_reason_and_cleanup(error, expected):
    conn = Mock()
    conn.execute.return_value.fetchone.return_value = (1,)
    result = rebuild_registered_quiz_artifacts(
        registry_lock=nullcontext(), load_registry=lambda: [{'id': 17}], get_db=lambda: conn,
        stage_artifacts=Mock(side_effect=error), promote_artifacts=Mock(), print_message=Mock())
    assert result['failed'] == [17]
    detail = result['failure_details'][0]
    assert detail['quiz_id'] == 17 and expected in detail['message']
    assert str(error) not in detail['message']
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()
