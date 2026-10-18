"""Compile a conventional installer only from an already-tested frozen payload."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
from .acceptance import require_normal_acceptance

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/".gate1/windows-native"

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--candidate",required=True)
    parser.add_argument("--acceptance",type=Path,required=True);parser.add_argument("--test-scope",action="store_true")
    parser.add_argument("--installer-release",help="isolated same-payload update qualification identity")
    parser.add_argument("--installer-revision",help="fresh installer-only output revision; frozen payload is unchanged")
    args=parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", args.candidate):
        raise ValueError("Unsafe candidate identity")
    candidate=(WORK/args.candidate).resolve(strict=True)
    if candidate.parent!=WORK:raise ValueError("Candidate must be a task-local frozen build")
    mode_file=candidate/'build-mode.json'
    if mode_file.exists() and json.loads(mode_file.read_text()) != {'instrumented':False}:
        raise ValueError('Instrumented native-controls payloads cannot qualify an installer')
    payload=candidate/"dist/DLMS-Desktop-WebView2";acceptance=json.loads(args.acceptance.read_text())
    require_normal_acceptance(acceptance, payload/"DLMS-Desktop-WebView2.exe", candidate/"payload-inventory.json")
    release=args.installer_release or args.candidate
    if args.installer_release and (not args.test_scope or not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", release)):
        raise ValueError("Alternate release identity is limited to isolated update testing")
    output=candidate/(("installer-isolated-"+release) if args.test_scope else "installer")
    if args.installer_revision:
        if not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*",args.installer_revision):
            raise ValueError("Unsafe installer revision")
        output=output/args.installer_revision
    from desktop.windows_files import assert_path
    assert_path(output)
    output.mkdir(parents=True,exist_ok=False)
    command=[str(WORK/"inno-portable/ISCC.exe"),"--no-ide-signtools","/DPayload="+str(payload),"/DRelease="+release,
             "/DOutputRoot="+str(output)]
    if args.test_scope:command.append("/DTestScope=1")
    info=json.loads((candidate/'build-info.json').read_text())
    if info.get('target') == 'Windows 11 x86-64 Desktop preview':
        from .preview_materials import verify
        verify(payload/'_internal/notices/distribution')
        version=info.get('backend_version', '')
        if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',version):
            raise ValueError('Preview backend version must be an exact numeric release')
        command.extend(['/DPublicPreview=1','/DBackendVersion='+version])
    command.append(str(ROOT/"package_windows_webview2/installer.iss"))
    def digest(path):
        with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    provenance={"installer_script_sha256":digest(ROOT/'package_windows_webview2/installer.iss'),
                "compiler_sha256":digest(WORK/'inno-portable/ISCC.exe'),
                "payload_inventory_sha256":digest(candidate/'payload-inventory.json'),
                "normal_acceptance_sha256":digest(args.acceptance)}
    with (output/"compile.log").open("w") as log:
        subprocess.run(command,cwd=ROOT/"package_windows_webview2",stdout=log,stderr=subprocess.STDOUT,check=True)
    if digest(ROOT/'package_windows_webview2/installer.iss')!=provenance['installer_script_sha256']:
        raise ValueError('Installer source changed during compilation')
    artifacts=[]
    for path in output.glob("*.exe"):
        with path.open("rb") as stream:sha=hashlib.file_digest(stream,"sha256").hexdigest()
        artifacts.append({"file":path.name,"bytes":path.stat().st_size,"sha256":sha,"signed":False,
                          "application":"DLMSDesktopWebView2Candidate", "release":release,
                          "installer_revision":args.installer_revision,
                          "isolated_variant":args.test_scope,**provenance})
    (output/"artifacts.json").write_text(json.dumps(artifacts,indent=2)+"\n")
    print(json.dumps(artifacts,indent=2))

if __name__=="__main__":main()
