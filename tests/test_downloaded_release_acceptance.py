"""Downloaded-release acceptance with real archives and offline GitHub fixtures."""
import hashlib
import importlib
import json
from pathlib import Path
import plistlib
import shutil
import stat
import struct
import subprocess
from types import SimpleNamespace
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tool(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    return importlib.import_module("accept_downloaded_release")


def make_package(path, platform):
    with zipfile.ZipFile(path, "w") as archive:
        def add(name, payload, mode=0o644):
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(info, payload)
        prefix = "" if platform == "macos-arm64" else path.stem + "/"
        for name in ("README.txt", "sample_quiz.txt"):
            add(prefix + name, name.encode())
        if platform == "macos-arm64":
            add("DLMS.app/Contents/MacOS/DLMS",
                b"\xcf\xfa\xed\xfe" + struct.pack("<I", 0x0100000C) + b"\0" * 24, 0o755)
            add("DLMS.app/Contents/Resources/icon.icns", b"icon")
            add("DLMS.app/Contents/Info.plist", plistlib.dumps({
                "CFBundleShortVersionString": "3.2.0", "CFBundleVersion": "3.2.0",
                "CFBundleExecutable": "DLMS", "CFBundleIdentifier": "io.github.drakahari.DLMS",
            }))
        else:
            binary = bytearray(256)
            binary[:2] = b"MZ"
            binary[0x3C:0x40] = struct.pack("<I", 0x80)
            binary[0x80:0x84] = b"PE\0\0"
            binary[0x84:0x86] = struct.pack("<H", 0x8664)
            add(prefix + path.stem + ".exe", binary)


@pytest.fixture(params=["windows11-x86_64", "macos-arm64"])
def scenario(tool, tmp_path, monkeypatch, request):
    asset = f"DLMS-3.2.0-{request.param}.zip"
    remote = tmp_path / "remote"
    remote.mkdir()
    make_package(remote / asset, request.param)
    digest = hashlib.sha256((remote / asset).read_bytes()).hexdigest()
    # A multi-platform release manifest must allow verifying a single asset.
    manifest = remote / "SHA256SUMS.txt"
    manifest.write_text(f"{digest}  {asset}\n{'a' * 64}  another-package.zip\n")

    def source(repository, tag, destination):
        (destination / "app.py").write_text('APP_VERSION = "3.2.0"\n')
        (destination / "release_assets").mkdir()
        for name in ("README.txt", "sample_quiz.txt"):
            (destination / "release_assets" / name).write_text(name)
        return "a" * 40

    calls = []
    def download(repo, tag, name, destination):
        calls.append((repo, tag, name))
        shutil.copyfile(remote / name, destination / name)

    monkeypatch.setattr(tool, "tagged_source", source)
    monkeypatch.setattr(tool, "download", download)
    args = SimpleNamespace(repo="drakahari/DLMS_next", tag="v3.2.0", asset=asset,
                           source_root=ROOT, output_dir=tmp_path / "acceptance", smoke=False)
    return args, remote, calls


def test_success_evidence_and_manual_status(tool, scenario):
    args, remote, calls = scenario
    record, evidence = tool.accept(args)
    assert record["automated_acceptance"] == "PASSED"
    assert record["checksum_manifest_result"] == record["package_verification_result"] == "PASS"
    assert record["manual_platform_check"] == "REQUIRED"
    assert record["native_smoke_result"] == "NOT_RUN"
    assert record["asset_sha256"] == tool.sha256_file(remote / args.asset)
    assert record["checksum_manifest_sha256"] == tool.sha256_file(remote / "SHA256SUMS.txt")
    assert json.loads(evidence.read_text()) == record
    assert calls == [(args.repo, args.tag, args.asset), (args.repo, args.tag, "SHA256SUMS.txt")]
    assert "Automated acceptance: PASSED" in tool.report(record, evidence)
    assert "Manual platform check: REQUIRED" in tool.report(record, evidence)


@pytest.mark.parametrize("failure", ["mismatch", "missing_asset", "missing_manifest",
                                    "malformed", "empty", "duplicate", "missing_entry", "package"])
def test_failures_recorded_without_acceptance(tool, scenario, failure, monkeypatch):
    args, remote, _ = scenario
    manifest = remote / "SHA256SUMS.txt"
    if failure == "mismatch":
        (remote / args.asset).write_bytes(b"changed bytes")
    elif failure == "missing_asset":
        (remote / args.asset).unlink()
    elif failure == "missing_manifest":
        manifest.unlink()
    elif failure == "malformed":
        manifest.write_text("not a checksum manifest\n")
    elif failure == "empty":
        manifest.write_text("")
    elif failure == "duplicate":
        manifest.write_text(manifest.read_text() * 2)
    elif failure == "missing_entry":
        manifest.write_text(f"{'a' * 64}  another-package.zip\n")
    else:
        (remote / args.asset).write_bytes(b"not a ZIP")
        manifest.write_text(f"{tool.sha256_file(remote / args.asset)}  {args.asset}\n")
    monkeypatch.setattr(tool, "clean_extract_and_smoke", lambda *a: pytest.fail("must not launch"))
    args.smoke = True
    record, evidence = tool.accept(args)
    assert record["automated_acceptance"] == "FAILED"
    assert record["errors"]
    assert record["manual_platform_check"] == "REQUIRED"
    assert record["native_smoke_result"] == "NOT_RUN"
    assert json.loads(evidence.read_text()) == record
    if failure == "package":
        assert record["checksum_manifest_result"] == "PASS"
        assert record["package_verification_result"] == "FAIL"


@pytest.mark.parametrize("errors", [[], ["foreign host or native smoke failed"]])
def test_native_smoke_is_composed_and_never_clears_manual_gate(tool, scenario, monkeypatch, errors):
    args, _, _ = scenario
    args.smoke = True
    calls = []
    def smoke(package, source):
        calls.append(package)
        assert tool.release_version(source) == "3.2.0"
        return errors
    monkeypatch.setattr(tool, "clean_extract_and_smoke", smoke)
    record, _ = tool.accept(args)
    assert calls == [args.output_dir / args.asset]
    assert record["native_smoke_result"] == ("FAIL" if errors else "PASS")
    assert record["automated_acceptance"] == ("FAILED" if errors else "PASSED")
    assert record["manual_platform_check"] == "REQUIRED"


def test_duplicate_output_is_preserved(tool, scenario):
    args, _, calls = scenario
    _, evidence = tool.accept(args)
    before = evidence.read_bytes()
    with pytest.raises(FileExistsError):
        tool.accept(args)
    assert evidence.read_bytes() == before
    assert len(calls) == 2


def test_cli_status_and_output(tool, scenario, capsys):
    args, _, _ = scenario
    command = ["--repo", args.repo, "--tag", args.tag, "--asset", args.asset,
               "--output-dir", str(args.output_dir)]
    assert tool.main(command) == 0
    assert "Automated acceptance: PASSED" in capsys.readouterr().out
    assert tool.main(command) == 1


@pytest.mark.parametrize("field,value", [("repo", "--evil"), ("tag", "latest"),
                                         ("asset", "../escape.zip"), ("asset", "*.zip")])
def test_argument_validation(tool, field, value):
    values = dict(repo="owner/repo", tag="v3.2.0", asset="DLMS-3.2.0-macos-arm64.zip")
    values[field] = value
    with pytest.raises(SystemExit) as error:
        tool.main([f"--{key}={value}" for key, value in values.items()])
    assert error.value.code == 2


def test_github_download_contract(tool, tmp_path, monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        (tmp_path / "SHA256SUMS.txt").write_text("download")
    monkeypatch.setattr(tool.subprocess, "run", run)
    tool.download("owner/repo", "v3.2.0", "SHA256SUMS.txt", tmp_path)
    command, options = calls[0]
    assert command == ["gh", "release", "download", "v3.2.0", "--repo", "github.com/owner/repo",
                       "--pattern", "SHA256SUMS.txt", "--dir", str(tmp_path)]
    assert options["check"] is True and options["timeout"] == 600
    assert options["env"]["GH_HOST"] == "github.com"


def test_missing_download_despite_success(tool, tmp_path, monkeypatch):
    monkeypatch.setattr(tool.subprocess, "run", lambda *a, **kw: None)
    with pytest.raises(ValueError, match="did not produce"):
        tool.download("owner/repo", "v3.2.0", "SHA256SUMS.txt", tmp_path)


def test_tagged_source_uses_immutable_commit(tool, tmp_path, monkeypatch):
    calls = []
    def git(command, **kwargs):
        calls.append(command)
        if "rev-parse" in command:
            return "a" * 40 + "\n"
        return b'APP_VERSION = "3.2.0"\n' if command[-1].endswith(":app.py") else b"support asset"
    monkeypatch.setattr(tool.subprocess, "check_output", git)
    assert tool.tagged_source(ROOT, "v3.2.0", tmp_path) == "a" * 40
    assert calls[0][-1] == "refs/tags/v3.2.0^{commit}"
    assert all(call[-1].startswith("a" * 40 + ":") for call in calls[1:])
    assert (tmp_path / "release_assets/README.txt").read_bytes() == b"support asset"


def test_source_failure_has_evidence(tool, scenario, monkeypatch):
    args, _, calls = scenario
    def fail(*a):
        raise subprocess.CalledProcessError(128, ["git", "rev-parse"], stderr=b"private details")
    monkeypatch.setattr(tool, "tagged_source", fail)
    record, evidence = tool.accept(args)
    assert record["automated_acceptance"] == "FAILED"
    assert not calls
    assert "private details" not in evidence.read_text()
