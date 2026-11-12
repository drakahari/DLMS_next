"""Exercise the real pytest partition, exit status and completion contract."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def run_shard(directory, index, count, body):
    path = directory / "test_synthetic.py"
    path.write_text(body)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "-p", "tests.browser._shard", "--firefox-shard-count", str(count),
         "--firefox-shard-index", str(index), str(path)],
        env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1"),
        cwd=directory, capture_output=True, text=True, timeout=20,
    )
    records = {}
    for line in result.stdout.splitlines():
        for key in ("MANIFEST", "RESULT"):
            prefix = "FIREFOX_SHARD_" + key + " "
            if line.startswith(prefix):
                records[key] = json.loads(line[len(prefix):])
    return result, records


def test_two_shards_execute_the_entire_collection_once_with_fresh_processes(tmp_path):
    body = "import pytest\n@pytest.mark.parametrize('n', range(7))\ndef test_case(n): assert n >= 0\n"
    baseline, whole = run_shard(tmp_path, 0, 1, body)
    assert baseline.returncode == 0, baseline.stdout + baseline.stderr
    selected = []
    for index in range(2):
        result, records = run_shard(tmp_path, index, 2, body)
        assert result.returncode == 0, result.stdout + result.stderr
        assert records["MANIFEST"]["collection_sha256"] == whole["MANIFEST"]["collection_sha256"]
        assert records["RESULT"]["complete"]
        assert records["RESULT"]["passed"] == records["MANIFEST"]["selected"]
        selected.extend(records["RESULT"]["passed"])
    assert len(selected) == len(set(selected)) == 7
    assert set(selected) == set(whole["RESULT"]["passed"])


@pytest.mark.parametrize("index,count", [(-1, 2), (2, 2), (0, 0), (1, 4)])
def test_invalid_or_empty_shards_fail_before_running_a_test(tmp_path, index, count):
    result, _ = run_shard(tmp_path, index, count, "def test_no_run(): raise AssertionError('BODY RAN')\n")
    assert result.returncode == pytest.ExitCode.USAGE_ERROR
    assert "BODY RAN" not in result.stdout


@pytest.mark.parametrize("body", [
    "def test_failure(): assert False\n",
    "import pytest\ndef test_skip(): pytest.skip('not acceptance')\n",
])
def test_failure_or_skipped_coverage_cannot_report_success(tmp_path, body):
    result, records = run_shard(tmp_path, 0, 1, body)
    assert result.returncode == pytest.ExitCode.TESTS_FAILED
    assert records["RESULT"]["complete"] is False
