"""Opt-in, streaming Firefox gate diagnostics, including before job cancellation."""

import collections
import json
import time

import pytest

from tests.browser._bidi import FirefoxBidi


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item, nextitem):
    original = FirefoxBidi.command
    commands = collections.defaultdict(lambda: [0, 0.0, 0.0])

    def measured(client, method, params, *args, **kwargs):
        started = time.monotonic()
        try:
            return original(client, method, params, *args, **kwargs)
        finally:
            elapsed = time.monotonic() - started
            row = commands[method]
            row[0] += 1
            row[1] += elapsed
            row[2] = max(row[2], elapsed)

    FirefoxBidi.command = measured
    try:
        return (yield)
    finally:
        FirefoxBidi.command = original
        print("\nFIREFOX_COMMAND_TIMING " + json.dumps({
            "test": item.nodeid,
            "columns": ["count", "total_seconds", "max_seconds"],
            "commands": dict(commands),
        }), flush=True)


def pytest_runtest_logreport(report):
    print("\nFIREFOX_PHASE_TIMING " + json.dumps({
        "test": report.nodeid, "phase": report.when,
        "outcome": report.outcome, "seconds": report.duration,
    }), flush=True)
    if report.failed:
        # Quiet pytest otherwise withholds every traceback until the full suite
        # exits, losing the actual failures when Actions cancels the job.
        print(str(report.longrepr), flush=True)
