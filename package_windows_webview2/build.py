"""Freeze one normal Windows payload with honest uncommitted provenance."""
from pathlib import Path
import argparse
import ast
import hashlib
import importlib.metadata as metadata
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".gate1/windows-native"
SDK_SHA256 = "56f7f4b8bf9aee4b8efefbbdd4f67d5f74ebd1b100ed0806da71bf76af481aa9"


def source_backend_version(path=ROOT / "app.py"):
    """Read the captured backend's literal identity without importing it."""
    assignments = [node for node in ast.parse(path.read_text(encoding="utf-8")).body
                   if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "APP_VERSION" for target in node.targets)]
    if (len(assignments) != 1 or not isinstance(assignments[0].value, ast.Constant)
            or not isinstance(assignments[0].value.value, str)
            or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+[A-Za-z0-9.+-]{0,32}", assignments[0].value.value) is None):
        raise ValueError("Captured backend version must be one bounded literal APP_VERSION")
    return assignments[0].value.value

def verify_environment(lock=ROOT / "package_windows/requirements-build-lock.txt"):
    """Refuse drift from the reviewed Windows pins; never mutate the environment."""
    from packaging.requirements import Requirement
    verified = {}
    for line in lock.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r "):
            verified.update(verify_environment((lock.parent / line[3:]).resolve()))
            continue
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        actual = metadata.version(requirement.name)
        if actual not in requirement.specifier:
            raise ValueError(f"Dependency drift: {requirement.name} {actual}; require {requirement.specifier}")
        verified[requirement.name] = actual
    return verified

def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def verify_host(host):
    """Only the independently built, inventoried candidate host is packaged."""
    manifest = host.parent / "SHA256.json"
    # PyInstaller recursively copies the data directory. Check the directory
    # itself and every entry, rather than silently omitting unknown subtrees.
    if os.name == "nt":
        from desktop.windows_files import assert_path
        assert_path(host)
        assert_path(manifest, leaf=True)
    root_info = host.lstat()
    if not stat.S_ISDIR(root_info.st_mode) or getattr(root_info, "st_file_attributes", 0) & 0x400:
        raise ValueError("Candidate host must be a plain directory")
    entries = list(host.iterdir())
    files = []
    for path in entries:
        value = path.lstat()
        if path.name == "extension":
            if not stat.S_ISDIR(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
                raise ValueError("Candidate extension must be a plain directory")
            files.extend(path.iterdir())
            continue
        files.append(path)
    for path in files:
        value = path.lstat()
        if (not stat.S_ISREG(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400
                or value.st_nlink != 1):
            raise ValueError("Unknown or missing candidate host files: non-regular entry")
    inventory = json.loads(manifest.read_text(encoding="utf-8-sig"))
    expected = {Path(x["Path"]).relative_to(host).as_posix(): x["Hash"].lower() for x in inventory}
    required = {"DLMS-WebView2-Host.exe", "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll", "WebView2Loader.dll", "LICENSE.txt", "extension/manifest.json", "extension/rules.json"}
    expected_root = {"DLMS-WebView2-Host.exe", "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll", "WebView2Loader.dll", "LICENSE.txt", "extension"}
    if (len(inventory) != len(required) or set(expected) != required
            or {p.relative_to(host).as_posix() for p in files} != required
            or {p.name for p in entries} != expected_root):
        raise ValueError("Unknown or missing candidate host files")
    for name, digest in expected.items():
        if sha(host / name) != digest:
            raise ValueError("Candidate host bytes changed")
    return expected


def verify_sdk_inputs(host, archive, *, expected=SDK_SHA256):
    if sha(archive) != expected:
        raise ValueError("Pinned WebView2 SDK archive changed")
    members = ("lib/net462/Microsoft.Web.WebView2.Core.dll",
               "lib/net462/Microsoft.Web.WebView2.WinForms.dll",
               "runtimes/win-x64/native/WebView2Loader.dll", "LICENSE.txt")
    with zipfile.ZipFile(archive) as bundle:
        for member in members:
            with bundle.open(member) as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if sha(host / Path(member).name) != digest:
                raise ValueError("Host SDK payload differs from pinned archive")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--release", required=True)
    parser.add_argument("--host-build", required=True, help="explicit final inventoried host build; no stale default")
    parser.add_argument("--instrumented", action="store_true", help="separate native-controls test payload; never install")
    parser.add_argument("--preview-materials", type=Path, help="verified Windows-specific recipient notices/source kit")
    parser.add_argument("--native-packages", type=Path, help="existing hash-pinned OCR producer archive cache; required for preview")
    args=parser.parse_args()
    if not args.release.replace("-", "").isalnum():
        raise ValueError("Invalid release identity")
    if sys.platform != "win32" or sys.version_info[:3] != (3,14,7):
        raise RuntimeError("Use the verified native CPython 3.14.7 build environment")
    verified = verify_environment()
    if args.preview_materials:
        from .preview_materials import verify
        verify(args.preview_materials)
        if args.native_packages is None:
            raise ValueError('Preview requires explicit pinned Windows native producer archives')
    if not args.host_build.startswith("webview2-host-candidate-") or not args.host_build.removeprefix("webview2-host-candidate-").isdigit():
        raise ValueError("Use an explicitly inventoried task-local host build")
    host = WORK / args.host_build / "payload"
    if (host.parent / 'AI-RACE-PROBE').exists():
        raise ValueError('Instrumented timing host cannot be frozen as an application candidate')
    verify_host(host)
    verify_sdk_inputs(host, WORK / "webview2-inputs-01/webview2.nupkg")
    run = WORK / args.release
    run.mkdir(exist_ok=False)
    if args.preview_materials:
        from .native_inputs import materialize
        pinned_native = materialize(args.native_packages, run/'pinned-native', ROOT/'package_windows/ocr-lock.json')
        (run/'pinned-native-inputs.json').write_text(json.dumps(pinned_native, indent=2)+'\n')
    (run / "build-mode.json").write_text(json.dumps({"instrumented": args.instrumented}) + "\n")
    (run / "verified-pins.json").write_text(json.dumps(verified, indent=2) + "\n")
    shutil.copy2(host.parent / "SHA256.json", run / "host-inputs.json")
    (run / "webview2-sdk-input.json").write_text(json.dumps({
        "package": "Microsoft.Web.WebView2", "version": "1.0.4258.31",
        "archive_sha256": sha(WORK / "webview2-inputs-01/webview2.nupkg"),
        "host_build": args.host_build,
        "host_build_script_sha256": sha(ROOT / "windows_webview2/build.ps1"),
    }, indent=2) + "\n")
    files=[]
    for folder in ("desktop", "desktop_assets", "dlms", "templates", "static", "tools", "package_windows", "package_windows_webview2", "windows_webview2", "tests"):
        for path in sorted((ROOT/folder).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                files.append({"path":path.relative_to(ROOT).as_posix(),"sha256":sha(path)})
    for name in ("app.py", "init.sql", "LICENSE", "requirements-lock.txt", "requirements-build.txt"):
        path = ROOT / name
        files.append({"path": name, "sha256": sha(path)})
    files.sort(key=lambda record: record["path"])
    snapshot=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    (run/"source-snapshot.json").write_text(json.dumps({"base_commit":commit,"uncommitted":True,
        "snapshot_sha256":snapshot,"files":files},indent=2)+"\n")
    identity={"application_version":"0.1.0", "release":args.release,
              "backend_version":source_backend_version(),
              "source_commit":commit+" + uncommitted "+snapshot,
              "target":"Windows 11 x86-64 WebView2 candidate",
              "browser_runtime":"Installed Microsoft WebView2 Evergreen; detected at launch, separately serviced",
              "support":("INSTRUMENTED TEST ONLY. Never install or count as normal physical acceptance."
                         if args.instrumented else "Private unsigned candidate. Physical acceptance and public distribution unqualified.")}
    if args.preview_materials and not args.instrumented:
        identity.update(application_version=source_backend_version(), target="Windows 11 x86-64 Desktop preview",
                        support="Unsigned public preview candidate. Review validation and limitations before use; not a stable release.")
    (run/"build-info.json").write_text(json.dumps(identity,indent=2)+"\n")
    notices=run/"notices"
    notices.mkdir()
    shutil.copy2(ROOT/"LICENSE",notices/"captured-application-MIT.txt")
    shutil.copy2(WORK/"inputs/python314/tools/LICENSE.txt",notices/"CPython-3.14.7-LICENSE.txt")
    shutil.copy2(host / "LICENSE.txt", notices / "Microsoft-WebView2-SDK-LICENSE.txt")
    packages=[]
    for distribution in metadata.distributions():
        name=distribution.metadata["Name"]
        packages.append({"name":name,"version":distribution.version})
        for item in distribution.files or []:
            relative=str(item).replace("\\","/")
            if any(token in relative.lower() for token in ("license","copying","notice")):
                original=Path(distribution.locate_file(item))
                if original.is_file():
                    target=notices/"python-packages"/name/relative
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(original,target)
    # Vendor Qt license resources accompany the installed PySide wheel.
    import PySide6
    qt=Path(PySide6.__file__).parent
    for name in ("Qt/licenses", "Qt/resources/qtwebengine_resources.pak"):
        path=qt/name
        if path.is_dir():shutil.copytree(path,notices/"Qt-licenses")
    (notices/"PRIVATE-CANDIDATE.txt").write_text(
        "Private test candidate, unsigned. Available vendor notices are included.\n"
        "Exact Qt/Chromium and native source/license/public redistribution obligations remain open.\n"
        "OCR native archive selection includes libarchive's GPL build; no public clearance is claimed.\n")
    if args.preview_materials:
        (notices/'PRIVATE-CANDIDATE.txt').unlink()
        shutil.copytree(args.preview_materials, notices/'distribution')
        (notices/'README.txt').write_text('Unsigned Windows Desktop preview candidate.\n'
            'Read distribution/REDISTRIBUTION.md, BUILD_AND_REPLACEMENT.md and SOURCE_MATERIALS.json.\n'
            'All corresponding-source companions must accompany any approved binary release.\n')
    (run/"resolved-python.json").write_text(json.dumps(sorted(packages,key=lambda x:x["name"].lower()),indent=2)+"\n")
    inventory=[{"path":p.relative_to(notices).as_posix(),"sha256":sha(p)}
               for p in sorted(notices.rglob("*")) if p.is_file()]
    (notices/"INVENTORY.json").write_text(json.dumps(inventory,indent=2)+"\n")
    ocr=WORK/"ocr-bundle-final"
    for item in json.loads((WORK/"ocr-inventory.json").read_text()):
        if sha(ocr/item["path"])!=item["sha256"]:
            raise ValueError("Prepared OCR bytes changed")
    prepared=run/'prepared-ocr'
    shutil.copytree(ocr,prepared)
    from package_windows.ocr_manifest import adapt
    provenance=json.dumps(adapt(prepared/'bin/tesseract.exe'),indent=2)+'\n'
    (run/'ocr-manifest-provenance.json').write_text(provenance)
    (prepared/'licenses/DLMS-WINDOWS-MANIFEST-MODIFICATION.txt').write_text(
        'DLMS Desktop modified the bundled Tesseract application manifest to opt this process into UTF-8.\n'
        'Vendor executable input was preserved; existing privileges and compatibility settings were retained.\n'+provenance)
    ocr=prepared
    env=dict(os.environ,DLMS_TESSERACT_BUNDLE_ROOT=str(ocr),DLMS_WINDOWS_BUILD_INFO=str(run/"build-info.json"),
             DLMS_WINDOWS_NOTICES=str(notices),DLMS_WEBVIEW2_HOST=str(host),PYTHONHASHSEED="0",
             DLMS_WV_BUILD_INSTRUMENTED="1" if args.instrumented else "0")
    if args.preview_materials:
        version_text=(ROOT/'package_windows_webview2/version.txt').read_text().replace(
            'DLMS Desktop private project','DLMS project').replace('WebView2 Windows Candidate','Windows Preview').replace(
            '0.1.0 Windows candidate',source_backend_version()+' Windows preview')
        version_tuple=','.join(source_backend_version().split('.')[:3])+',0'
        version_text=version_text.replace('(0,1,0,0)','('+version_tuple+')').replace("'0.1.0.0'",repr(source_backend_version()+'.0'))
        (run/'version-preview.txt').write_text(version_text)
        env.update(DLMS_WINDOWS_PUBLIC_PREVIEW='1',DLMS_WINDOWS_VERSION_RESOURCE=str(run/'version-preview.txt'))
        env.update(DLMS_WINDOWS_PINNED_NATIVE=str(run/'pinned-native'),
                   DLMS_WINDOWS_PINNED_NATIVE_RECORDS=str(run/'pinned-native-inputs.json'))
    with (run/"freeze.log").open("w") as log:
        result=subprocess.run([sys.executable,"-m","PyInstaller","--noconfirm","--clean",
            "--distpath",str(run/"dist"),"--workpath",str(run/"build"),
            str(ROOT/"package_windows_webview2/DLMS-Desktop-WebView2.spec")],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"Freeze failed; retain {run/'freeze.log'}")
    name="DLMS-Desktop-WebView2-Instrumented" if args.instrumented else "DLMS-Desktop-WebView2"
    payload=run/"dist"/name
    inventory=[{"path":p.relative_to(payload).as_posix(),"bytes":p.stat().st_size,"sha256":sha(p)}
               for p in sorted(payload.rglob("*")) if p.is_file()]
    (run/"payload-inventory.json").write_text(json.dumps(inventory,indent=2)+"\n")
    print(payload/(name+".exe"))

if __name__=="__main__":main()
