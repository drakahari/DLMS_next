"""Compile a conventional installer only from an already-tested frozen payload."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/".gate1/windows-native"

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--candidate",required=True)
    parser.add_argument("--acceptance",type=Path,required=True);parser.add_argument("--test-scope",action="store_true")
    parser.add_argument("--installer-release",help="isolated same-payload update qualification identity")
    args=parser.parse_args();candidate=(WORK/args.candidate).resolve(strict=True)
    if candidate.parent!=WORK:raise ValueError("Candidate must be a task-local frozen build")
    payload=candidate/"dist/DLMS-Desktop";acceptance=json.loads(args.acceptance.read_text())
    if Path(acceptance["normal_executable"]).resolve()!=payload/"DLMS-Desktop.exe" or len(acceptance["runs"])<2:
        raise ValueError("Normal executable acceptance does not match the payload")
    inventory=json.loads((candidate/"payload-inventory.json").read_text())
    if {p.relative_to(payload).as_posix() for p in payload.rglob("*") if p.is_file()} != {x["path"] for x in inventory}:
        raise ValueError("Unknown or missing payload files; installer refused")
    for item in inventory:
        with (payload/item["path"]).open("rb") as stream:
            if hashlib.file_digest(stream,"sha256").hexdigest()!=item["sha256"]:raise ValueError("Tested payload bytes changed")
    release=args.installer_release or args.candidate
    if args.installer_release and (not args.test_scope or not release.replace("-", "").isalnum()):
        raise ValueError("Alternate release identity is limited to isolated update testing")
    output=candidate/(("installer-isolated-"+release) if args.test_scope else "installer")
    output.mkdir(exist_ok=False)
    command=[str(WORK/"inno-portable/ISCC.exe"),"/DPayload="+str(payload),"/DRelease="+release,
             "/DOutputRoot="+str(output)]
    if args.test_scope:command.append("/DTestScope=1")
    command.append(str(ROOT/"package_windows/installer.iss"))
    def digest(path):
        with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    provenance={"installer_script_sha256":digest(ROOT/'package_windows/installer.iss'),
                "compiler_sha256":digest(WORK/'inno-portable/ISCC.exe'),
                "payload_inventory_sha256":digest(candidate/'payload-inventory.json'),
                "normal_acceptance_sha256":digest(args.acceptance)}
    with (output/"compile.log").open("w") as log:
        subprocess.run(command,cwd=ROOT/"package_windows",stdout=log,stderr=subprocess.STDOUT,check=True)
    if digest(ROOT/'package_windows/installer.iss')!=provenance['installer_script_sha256']:
        raise ValueError('Installer source changed during compilation')
    artifacts=[]
    for path in output.glob("*.exe"):
        with path.open("rb") as stream:sha=hashlib.file_digest(stream,"sha256").hexdigest()
        artifacts.append({"file":path.name,"bytes":path.stat().st_size,"sha256":sha,"signed":False,"isolated_variant":args.test_scope,**provenance})
    (output/"artifacts.json").write_text(json.dumps(artifacts,indent=2)+"\n")
    print(json.dumps(artifacts,indent=2))

if __name__=="__main__":main()
