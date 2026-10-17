from desktop.server_console import KNOWN_MESSAGES, ServerPolicyDiagnostics
from desktop.policy import _UNRECOGNIZED_BUILD
import pytest

@pytest.mark.parametrize('message', list(KNOWN_MESSAGES))
def test_exact_verified_warning_first_visible_then_deduplicated(message):
    diagnostics=ServerPolicyDiagnostics(_UNRECOGNIZED_BUILD)
    assert not diagnostics.repeated(message, warning=True)
    assert diagnostics.repeated(message, warning=True)
    assert diagnostics.repeated(message, warning=True)
    assert diagnostics.counts=={message:3}

@pytest.mark.parametrize('message', ['other warning', "Unrecognized feature: 'usb'", 'DLMS performance sentinel warning'])
def test_other_messages_preserved(message):
    d=ServerPolicyDiagnostics(_UNRECOGNIZED_BUILD)
    for _ in range(3):assert not d.repeated(message,warning=True)
    assert d.counts=={}

@pytest.mark.parametrize('message', list(KNOWN_MESSAGES))
def test_all_errors_and_unverified_engines_preserved(message):
    for versions,warning in [(_UNRECOGNIZED_BUILD,False),(('6.12.0','6.12.0','141'),True)]:
        d=ServerPolicyDiagnostics(versions)
        for _ in range(3):assert not d.repeated(message,warning=warning)
        assert d.counts=={}
