"""Normal frozen manager/launcher test; fresh synthetic output only, no host input."""
from pathlib import Path
import argparse
import json,os,subprocess,shutil,hashlib,tarfile
from package_fedora.install_pilot import paths,sha256
from package_fedora.manual_replace import normal_launcher_path,payload_inventory
from tests.package.installed_pilot_smoke import launch
parser=argparse.ArgumentParser();parser.add_argument('--archive',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--check-variant',action='store_true');args=parser.parse_args()
out=args.output.absolute();out.mkdir(mode=0o700,parents=True,exist_ok=False)
archive=args.archive.absolute()
extraction=out/'fresh extraction';extraction.mkdir(mode=0o700)
with tarfile.open(archive,'r:zst') as tar:tar.extractall(extraction,filter='data')
payload=extraction/'DLMS-Desktop';wrapper=payload/'Install-DLMS-Desktop'
home=out/'synthetic-home';home.mkdir(mode=0o700)
env={'PATH':'/nonexistent','HOME':str(home),'LANG':'C.UTF-8'}
def cli(*args):
 p=subprocess.run([str(wrapper),*args,'--home',str(home)],cwd=out,env=env,capture_output=True,text=True,timeout=180)
 with (out/'cli-records.jsonl').open('a') as log:log.write(json.dumps({'args':args,'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr})+'\n')
 assert p.returncode==0,(args,p.stdout,p.stderr)
 return json.loads(p.stdout)
plan=cli('install','--artifact',str(archive),'--sha256',sha256(archive));installed=cli('apply','--plan',plan['plan_file'],'--confirm',plan['plan']['confirmation'])
os.environ['PATH']='/nonexistent'
runs=[launch(normal_launcher_path(home),paths(home)['data'],out,i,session_wayland=False) for i in (1,2)]
assert runs[0]['profile_uuid']==runs[1]['profile_uuid'] and runs[0]['origin_port']==runs[1]['origin_port']
result={'normal_package':True,'instrumented':False,'archive_sha256':sha256(archive),'initial_install':installed,'runs':runs,'owned_helpers_cleaned':True,'same_profile_and_origin':True}
if args.check_variant:
 modified=out/'external modified payload';shutil.copytree(payload,modified,symlinks=True)
 lib=modified/'_internal/PySide6/Qt/lib/libQt6Svg.so.6';assert lib.is_file() and not lib.is_symlink()
 original_hash=sha256(lib)
 with lib.open('ab') as stream:stream.write(b'\nDLMS-DISPOSABLE-COMPATIBLE-TAIL-MARKER\n')
 variant=cli('prepare-variant','--base-payload',str(payload),'--modified-payload',str(modified),'--variant-output',str(out/'variant'),'--release','user-compatible-svg-20261013','--base-inventory',payload_inventory(payload))
 plan=cli('update','--artifact',variant['archive'],'--sha256',variant['sha256']);update=cli('apply','--plan',plan['plan_file'],'--confirm',plan['plan']['confirmation'])
 variant_runs=[launch(normal_launcher_path(home),paths(home)['data'],out,i,session_wayland=False) for i in (3,4)]
 assert all(x['profile_uuid']==runs[0]['profile_uuid'] and x['origin_port']==runs[0]['origin_port'] for x in variant_runs)
 from package_fedora.manual_replace import verify
 manifest,_=verify(home)
 assert manifest['active_release']=='user-compatible-svg-20261013'
 installedlib=paths(home)['opt']/'versions/user-compatible-svg-20261013/DLMS-Desktop/_internal/PySide6/Qt/lib/libQt6Svg.so.6'
 assert sha256(installedlib)==sha256(lib)!=original_hash
 result={'normal_package':True,'instrumented':False,'archive_sha256':sha256(archive),'initial_install':installed,'runs':runs,'variant':variant,'update':update,'variant_runs':variant_runs,'owned_helpers_cleaned':True,'same_profile_and_origin':True,'modified_library_sha256':sha256(lib),'base_library_sha256':original_hash,'limitations':['app-local/offscreen; no physical visual/input acceptance','compatible nonloaded ELF tail alteration, not a real rebuilt-library ABI guarantee','no owner installation changed']}
 (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
 print('Normal frozen installation, reopen, separate QtSvg variant preparation/update/reopen and guarded inventory passed')
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print('Normal final package install/launch/reopen and exact owned cleanup passed')
