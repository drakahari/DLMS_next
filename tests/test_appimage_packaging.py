"""Additive AppImage layout, launcher and native icon contracts."""
import ast
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tool(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    import build_appimage
    return build_appimage


@pytest.fixture
def appdir(tool, tmp_path):
    binary = tmp_path / "DLMS"
    binary.write_text('#!/bin/sh\nprintf "%s\\n" "$QUIZAPP_DATA_DIR" "$@"\n')
    binary.chmod(0o755)
    destination = tmp_path / "app dir"
    tool.stage_appdir(binary, destination)
    return destination, tool.sha256_file(binary)


def test_appdir_layout_artwork_and_desktop(tool, appdir):
    directory, digest = appdir
    tool.verify_appdir(directory, digest)
    with Image.open(ROOT / "static/favicon.ico") as original:
        expected = original.convert("RGBA").resize((256, 256), Image.Resampling.LANCZOS)
    with Image.open(directory / "dlms.png") as icon:
        assert icon.tobytes() == expected.tobytes()
    if shutil.which("desktop-file-validate"):
        subprocess.run(["desktop-file-validate", directory / "dlms.desktop"], check=True)


@pytest.mark.parametrize("arguments", [[], ["--no-browser", "--host", "0.0.0.0"],
                                       ["--browser", "--host=127.0.0.1", "value with spaces"]])
def test_launcher_preserves_arguments_data_root_and_exit(tool, appdir, tmp_path, arguments):
    directory, _ = appdir
    result = subprocess.run([directory / "AppRun", *arguments], cwd=tmp_path,
                            env={"QUIZAPP_DATA_DIR": str(tmp_path / "outside")},
                            capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == [str(tmp_path / "outside"), *arguments]
    (directory / "usr/bin/DLMS").write_text("#!/bin/sh\nexit 17\n")
    assert subprocess.run([directory / "AppRun"], check=False).returncode == 17


@pytest.mark.parametrize("broken", ["binary", "icon", "desktop", "support", "launcher"])
def test_invalid_layout_rejected(tool, appdir, broken):
    directory, digest = appdir
    names = {"binary": "usr/bin/DLMS", "icon": ".DirIcon", "desktop": "dlms.desktop",
             "support": "sample_quiz.txt", "launcher": "AppRun"}
    (directory / names[broken]).unlink()
    with pytest.raises((OSError, ValueError)):
        tool.verify_appdir(directory, digest)


def test_fresh_output_and_pinned_tools(tool, appdir, tmp_path):
    directory, _ = appdir
    with pytest.raises(FileExistsError):
        tool.stage_appdir(directory / "usr/bin/DLMS", directory)
    binary = directory / "usr/bin/DLMS"
    assert tool.checked_tool(binary, tool.sha256_file(binary)) == binary.resolve()
    with pytest.raises(ValueError, match="checksum mismatch"):
        tool.checked_tool(binary, "0" * 64)
    with pytest.raises(ValueError, match="64 hexadecimal"):
        tool.checked_tool(binary, "bad")


@pytest.mark.parametrize("mode,extra", [("fuse", []), ("extract", ["--appimage-extract-and-run"])])
def test_smoke_reuses_native_gate_and_propagates_failure(tool, monkeypatch, tmp_path, mode, extra):
    monkeypatch.setattr(tool, "_assert_smoke_host", Mock())
    monkeypatch.setattr(tool, "_assert_port_available", Mock())
    smoke = Mock(side_effect=RuntimeError("runtime mismatch"))
    monkeypatch.setattr(tool, "_run_smoke_command", smoke)
    with pytest.raises(RuntimeError, match="runtime mismatch"):
        tool.smoke_appimage(tmp_path / "DLMS.AppImage", "3.2.0", mode)
    command, target, work, version = smoke.call_args.args
    assert command == [str(tmp_path / "DLMS.AppImage"), *extra, "--no-browser"]
    assert target == "linux-x86_64" and version == "3.2.0"
    assert not work.exists()


@pytest.mark.parametrize("target", ["win32", "linux", "darwin"])
def test_native_spec_icon_branch_preserves_platform_contract(tool, monkeypatch, tmp_path, target):
    import PyInstaller.config
    monkeypatch.setitem(PyInstaller.config.CONF, "workpath", str(tmp_path))
    spec = ast.parse((ROOT / "DLMS.spec").read_text())
    branch = next(node for node in spec.body if isinstance(node, ast.If) and
                  ast.unparse(node.test) == "sys.platform == 'darwin'")
    exe, bundle = Mock(), Mock()
    namespace = {"sys": SimpleNamespace(platform=target), "project_root": ROOT,
                 "Path": Path, "EXE": exe, "BUNDLE": bundle,
                 "python_archive": object(), "analysis": SimpleNamespace(scripts=[], binaries=[], datas=[]),
                 "app_bundle_version": "3.2.0", "app_release_version": "3.2.0",
                 "app_bundle_build_version": "3.2.0"}
    exec(compile(ast.Module(body=[branch], type_ignores=[]), "DLMS.spec", "exec"), namespace)
    if target == "win32":
        icon = Path(exe.call_args.kwargs["icon"])
        assert icon.parent == tmp_path
        with Image.open(icon) as image:
            assert image.format == "ICO"
            assert image.ico.sizes() == {(n, n) for n in (16, 24, 32, 48, 64, 128, 256)}
        assert exe.call_args.kwargs["console"] is True
    elif target == "linux":
        assert exe.call_args.kwargs["icon"] is None
        assert exe.call_args.kwargs["console"] is True
    else:
        assert bundle.call_args.kwargs["icon"] == str(ROOT / "static/favicon.ico")
        assert bundle.call_args.kwargs["name"] == "DLMS.app"
        assert exe.call_args.kwargs["console"] is False


def test_non_linux_target_rejected(tool):
    with pytest.raises(SystemExit) as caught:
        tool.main(["--target", "windows11-x86_64"])
    assert caught.value.code == 2


def test_runtime_evidence_is_exclusive_and_records_failure(tool, monkeypatch, tmp_path):
    import json
    import verify_appimage_runtime as runtime
    report = tmp_path / "evidence.json"
    args = [str(tmp_path / "image"), "--expected-version", "3.2.0", "--report", str(report)]
    evaluate = Mock(side_effect=RuntimeError("probe failed"))
    monkeypatch.setattr(runtime, "evaluate", evaluate)
    with pytest.raises(RuntimeError, match="probe failed"):
        runtime.main(args)
    assert json.loads(report.read_text())["status"] == "FAILED"
    with pytest.raises(FileExistsError):
        runtime.main(args)
    evaluate.assert_called_once()


def test_runtime_success_does_not_claim_lan_without_opt_in(tool, monkeypatch, tmp_path):
    import json
    import verify_appimage_runtime as runtime
    evaluate = Mock(return_value={"screenshot_ocr": "PASS"})
    monkeypatch.setattr(runtime, "evaluate", evaluate)
    report = tmp_path / "evidence.json"
    assert runtime.main([str(tmp_path / "image"), "--expected-version", "3.2.0",
                         "--report", str(report)]) == 0
    assert evaluate.call_args.kwargs == {"lan": False}
    assert json.loads(report.read_text()) == {"status": "PASSED", "screenshot_ocr": "PASS"}


def test_appimage_preflight_wrong_host_never_builds(tool, monkeypatch, tmp_path):
    monkeypatch.setattr(tool, "_assert_smoke_host", Mock(side_effect=RuntimeError("wrong host")))
    build = Mock()
    monkeypatch.setattr(tool, "build_frozen", build)
    with pytest.raises(RuntimeError, match="wrong host"):
        tool.build(SimpleNamespace())
    build.assert_not_called()
