"""Deterministic CI partitioning with explicit coverage and completion receipts."""

import hashlib
import json

import pytest


_STATE = pytest.StashKey[dict]()


def pytest_addoption(parser):
    parser.addoption("--firefox-shard-count", type=int, default=1)
    parser.addoption("--firefox-shard-index", type=int, default=0)


def pytest_collection_modifyitems(config, items):
    count = config.getoption("--firefox-shard-count")
    index = config.getoption("--firefox-shard-index")
    if count < 1 or not 0 <= index < count:
        raise pytest.UsageError("Firefox shard index must be within a positive shard count")
    all_ids = [item.nodeid for item in items]
    if len(set(all_ids)) != len(all_ids):
        raise pytest.UsageError("Firefox shard collection contains duplicate test IDs")
    selected = items[index::count]
    if not selected:
        raise pytest.UsageError("Firefox shard must select at least one test")
    manifest = {
        "index": index, "count": count, "collected": len(items),
        "collection_sha256": hashlib.sha256("\n".join(all_ids).encode()).hexdigest(),
        "selected": [item.nodeid for item in selected],
    }
    config.stash[_STATE] = {"manifest": manifest, "passed": []}
    deselected = [item for position, item in enumerate(items) if position % count != index]
    items[:] = selected
    config.hook.pytest_deselected(items=deselected)
    print("\nFIREFOX_SHARD_MANIFEST " + json.dumps(manifest), flush=True)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    if report.when == "call" and report.passed:
        item.config.stash[_STATE]["passed"].append(item.nodeid)
    return report


def pytest_sessionfinish(session, exitstatus):
    if _STATE not in session.config.stash:
        return
    state = session.config.stash[_STATE]
    complete = state["passed"] == state["manifest"]["selected"]
    if exitstatus == 0 and not complete:
        # An all-skipped or partially skipped browser shard is not acceptance.
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
    print("\nFIREFOX_SHARD_RESULT " + json.dumps({
        "index": state["manifest"]["index"], "complete": complete,
        "passed": state["passed"],
    }), flush=True)
