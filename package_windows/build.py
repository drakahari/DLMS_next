"""Freeze one normal Windows payload with honest uncommitted provenance."""
from pathlib import Path
import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".gate1/windows-native"

def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--release", required=True)
    args=parser.parse_args()
    if not args.release.replace("-", "").isalnum():
        raise ValueError("Invalid release identity")
    if sys.platform != "win32" or sys.version_info[:3] != (3,14,7):
        raise RuntimeError("Use the verified native CPython 3.14.7 build environment")
    run = WORK / args.release
    run.mkdir(exist_ok=False)
    files=[]
    for folder in ("desktop", "desktop_assets", "dlms", "templates", "static", "tools", "package_windows", "tests"):
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
              "source_commit":commit+" + uncommitted "+snapshot,
              "target":"Windows 11 x86-64 native candidate",
              "support":"Private unsigned candidate. Physical acceptance and public distribution unqualified."}
    (run/"build-info.json").write_text(json.dumps(identity,indent=2)+"\n")
    notices=run/"notices"
    notices.mkdir()
    shutil.copy2(ROOT/"LICENSE",notices/"captured-application-MIT.txt")
    shutil.copy2(WORK/"inputs/python314/tools/LICENSE.txt",notices/"CPython-3.14.7-LICENSE.txt")
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
             DLMS_WINDOWS_NOTICES=str(notices),PYTHONHASHSEED="0")
    with (run/"freeze.log").open("w") as log:
        result=subprocess.run([sys.executable,"-m","PyInstaller","--noconfirm","--clean",
            "--distpath",str(run/"dist"),"--workpath",str(run/"build"),
            str(ROOT/"package_windows/DLMS-Desktop.spec")],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"Freeze failed; retain {run/'freeze.log'}")
    payload=run/"dist/DLMS-Desktop"
    inventory=[{"path":p.relative_to(payload).as_posix(),"bytes":p.stat().st_size,"sha256":sha(p)}
               for p in sorted(payload.rglob("*")) if p.is_file()]
    (run/"payload-inventory.json").write_text(json.dumps(inventory,indent=2)+"\n")
    print(payload/"DLMS-Desktop.exe")

if __name__=="__main__":main()
