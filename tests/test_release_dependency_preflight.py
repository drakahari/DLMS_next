"""Release dependency validation never invokes a native build."""
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def checker(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    return importlib.import_module("check_release_dependencies")


@pytest.fixture
def complete(checker, monkeypatch):
    pins = checker.locked_requirements(ROOT / "requirements-build.txt")
    versions = mock.Mock(side_effect=lambda name: pins[name])
    imports = mock.Mock()
    run = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(checker.metadata, "version", versions)
    monkeypatch.setattr(checker.importlib, "import_module", imports)
    monkeypatch.setattr(checker.subprocess, "run", run)
    return pins, versions, imports, run


def test_complete_environment(checker, complete, capsys):
    pins, versions, imports, run = complete
    checker.check_dependencies()
    assert {call.args[0] for call in versions.call_args_list} == set(pins)
    required = {call.args[0] for call in imports.call_args_list}
    assert {"PyInstaller", "PyInstaller.utils.hooks", "pypdfium2", "pypdfium2_raw", "PIL.Image", "flask_wtf", "yaml"} <= required
    assert not any(name.startswith("dlms.") for name in required)
    assert run.call_args.args[0] == [checker.sys.executable, "-m", "pip", "check"]
    assert "Release dependencies OK" in capsys.readouterr().out


@pytest.mark.parametrize("problem", ["metadata", "import", "raw-import", "version", "pyinstaller", "pip"])
def test_incomplete_environment_fails_actionably(checker, complete, problem):
    pins, versions, imports, run = complete
    if problem == "metadata":
        def version(name):
            if name == "pypdfium2":
                raise checker.metadata.PackageNotFoundError(name)
            return pins[name]
        versions.side_effect = version
        expected = "pypdfium2: missing distribution metadata"
    elif problem in {"import", "raw-import"}:
        module = "pypdfium2_raw" if problem == "raw-import" else "pypdfium2"
        def load(name):
            if name == module:
                raise ModuleNotFoundError(name)
        imports.side_effect = load
        expected = f"{module}: import failed"
    elif problem in {"version", "pyinstaller"}:
        package = "pypdfium2" if problem == "version" else "pyinstaller"
        versions.side_effect = lambda name: "0.0" if name == package else pins[name]
        expected = f"{package}: installed 0.0, locked version {pins[package]} required"
    else:
        run.return_value = SimpleNamespace(returncode=1, stdout="broken transitive dependency", stderr="")
        expected = "pip check failed: broken transitive dependency"
    with pytest.raises(RuntimeError) as error:
        checker.check_dependencies()
    message = str(error.value)
    assert expected in message
    assert checker.sys.executable in message
    assert str(checker.build_python(ROOT)) in message
    assert "pip install -r requirements-build.txt" in message
    if problem != "pip":
        run.assert_not_called()


@pytest.mark.parametrize("platform,suffix", [("linux", "bin/python"), ("darwin", "bin/python"), ("win32", "Scripts/python.exe")])
def test_build_environment_path(checker, tmp_path, platform, suffix):
    assert checker.build_python(tmp_path, platform) == tmp_path / ".venv-build" / suffix


def test_manifest_is_authority_and_unknown_syntax_fails(checker, tmp_path):
    runtime = tmp_path / "runtime.txt"
    runtime.write_text("pypdfium2==99.1\n")
    build = tmp_path / "build.txt"
    build.write_text("-r runtime.txt\nPyInstaller==99.2\n")
    assert checker.locked_requirements(build) == {"pypdfium2": "99.1", "pyinstaller": "99.2"}
    build.write_text("PyInstaller>=99.2\n")
    with pytest.raises(ValueError, match="Unsupported"):
        checker.locked_requirements(build)


def test_specs_are_authority(checker):
    imports, metadata = checker.spec_dependencies(ROOT)
    assert {"pypdfium2", "pypdfium2_raw"} <= imports
    assert "pypdfium2" in metadata
