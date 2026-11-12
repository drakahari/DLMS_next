"""Security-fixed runtime pins must also reach both Fedora producers."""
from pathlib import Path

import yaml

from tools.check_release_dependencies import IMPORT_NAMES, locked_requirements

ROOT = Path(__file__).resolve().parents[1]


def test_security_fixed_runtime_is_identical_in_build_test_and_desktop():
    runtime = locked_requirements(ROOT / "requirements-lock.txt")
    expected = {"pillow": "13.0.0", "pypdf": "6.21.4", "cryptography": "50.0.2",
                "cffi": "2.1.1", "pycparser": "3.12"}
    for path in ("requirements-lock.txt", "requirements-build.txt", "requirements-test.txt",
                 "package_fedora/requirements-build-lock.txt", "desktop/requirements-lock.txt"):
        pins = locked_requirements(ROOT / path)
        assert all(pins[name] == version for name, version in expected.items())
        assert all(pins[name] == version for name, version in runtime.items())
    assert IMPORT_NAMES["cryptography"] == "cryptography.hazmat.primitives.ciphers"


def test_each_dependency_set_is_audited_even_after_another_set_fails():
    workflow = yaml.safe_load((ROOT / ".github/workflows/dependency-audit.yml").read_text())
    steps = workflow["jobs"]["python-dependencies"]["steps"]
    audits = [step for step in steps if "python -m pip_audit" in step.get("run", "")]
    assert len(audits) == 4
    for requirement in ("requirements-lock.txt", "requirements-build.txt", "requirements-test.txt",
                        "package_fedora/requirements-build-lock.txt"):
        matching = [step for step in audits if "--requirement " + requirement in step["run"]]
        assert len(matching) == 1
        assert matching[0]["if"] == "${{ !cancelled() }}"
        assert "continue-on-error" not in matching[0]
        assert "--ignore-vuln" not in matching[0]["run"]
