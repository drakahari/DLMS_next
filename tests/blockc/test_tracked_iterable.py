"""The WSGI outer gate must be released even without response iteration."""

from desktop.backend import TrackedIterable


def test_close_before_iteration_releases_exactly_once():
    calls = []

    class Source:
        def __iter__(self):
            calls.append("iterated")
            yield b"body"

        def close(self):
            calls.append("source_closed")

    wrapped = TrackedIterable(Source(), lambda: calls.append("gate_released"))
    wrapped.close()
    wrapped.close()
    assert calls == ["source_closed", "gate_released"]


def test_iteration_closes_and_releases_exactly_once():
    calls = []
    wrapped = TrackedIterable([b"body"], lambda: calls.append("gate_released"),
                              before_iteration=lambda: calls.append("entered"))
    assert list(wrapped) == [b"body"]
    wrapped.close()
    assert calls == ["entered", "gate_released"]
