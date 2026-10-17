"""External supervisor for a separate instrumented executable, never shipped in normal payload.

Requires an existing closed, marked, synthetic Study fixture; copies and verifies
it before every scenario, then checks exact original evidence remains unchanged.
Uses application-local Qt checks and exact PID/birth cleanup, not host input.
"""
from pathlib import Path
import os,json,subprocess,time,shutil,hashlib,argparse,re,fcntl
from tests.package.normal_local_settings_smoke import descendants,starttime,stop_exact_owned
parser=argparse.ArgumentParser(description='Instrumented-only accepted Study shutdown/reopen matrix')
parser.add_argument('--exe',type=Path,required=True)
parser.add_argument('--seed-data',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--profile',default='frpending')
parser.add_argument('--platform',choices=['offscreen','wayland','xcb'],default='offscreen')
a=parser.parse_args()
source=a.seed_data.absolute();out=a.output.absolute()
if not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}',a.profile):raise ValueError('Invalid synthetic profile name')
if source.is_symlink() or out.is_relative_to(source) or source.is_relative_to(out):
 raise ValueError('Evidence and output roots must be independent, with no source symlink')
if json.loads((source/'.dlms-desktop-disposable.json').read_text())!={'kind':'dlms-desktop-fedora-package-feasibility','version':1}:
 raise ValueError('Only explicitly marked disposable synthetic fixtures are allowed')
if any(p.is_symlink() for p in source.rglob('*')):
 raise ValueError('Synthetic fixture must not contain symlinks')
if (source/'profiles'/a.profile/'instance.lock').exists() or (source/'profiles'/a.profile/'instance-owner.json').exists():
 raise ValueError('Source fixture must be closed; do not retire ownership')
writer=(source/'profiles'/a.profile/'backend-writer.lock').open('rb')
fcntl.flock(writer.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
out.mkdir(mode=0o700,parents=True,exist_ok=False)
def hashes(root):return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
original=hashes(source)
exe=str(a.exe.absolute())
rows=[]
for case in ['pending','uncertain','pending-app','uncertain-app']:
 folder=out/case;folder.mkdir(mode=0o700);root=folder/'data';shutil.copytree(source,root,symlinks=True)
 assert hashes(root)==original
 env={'PATH':'/nonexistent','LANG':'C.UTF-8','QT_QPA_PLATFORM':a.platform}
 if a.platform!='offscreen':
  for key in ['DISPLAY','WAYLAND_DISPLAY','DBUS_SESSION_BUS_ADDRESS','XDG_RUNTIME_DIR','XDG_SESSION_TYPE','XDG_CURRENT_DESKTOP']:
   if key in os.environ:env[key]=os.environ[key]
 for key,leaf in [('HOME','home'),('XDG_DATA_HOME','xdg-data'),('XDG_CONFIG_HOME','config'),('XDG_CACHE_HOME','cache'),('TMPDIR','tmp'),('XDG_RUNTIME_DIR','runtime')]:
  if key=='XDG_RUNTIME_DIR' and a.platform!='offscreen' and key in env:continue
  d=folder/leaf;d.mkdir(mode=0o700);env[key]=str(d)
 for phase in [case,'reopen']:
  cmd=[exe,'--packaged-check','shutdown','--profile',a.profile,'--data-root',str(root),'--case',phase]
  with (folder/(phase+'.log')).open('w') as log:
   p=subprocess.Popen(cmd,env=env,cwd=folder,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);known={p.pid:starttime(p.pid)};peak_shm=0
   try:
    until=time.monotonic()+100
    while p.poll() is None and time.monotonic()<until:
     known.update({pid:starttime(pid) for pid in descendants(p.pid)})
     if a.platform=='offscreen':
      v=os.statvfs('/dev/shm');peak_shm=max(peak_shm,(v.f_blocks-v.f_bfree)*v.f_frsize)
     time.sleep(.1)
    assert p.poll()==0,(case,phase,p.returncode)
   finally:assert not stop_exact_owned(p,known)
  rows.append(dict(case=case,phase=phase,passed=True,owned_cleanup=True,Qt_platform=a.platform,peak_shm_bytes=peak_shm if a.platform=='offscreen' else None));print(rows[-1],flush=True)
 assert hashes(source)==original,'Original failed fixture must remain byte-for-byte unchanged'
 (out/'result.json').write_text(json.dumps(dict(instrumented_only=True,checks=rows,original_failed_fixture_preserved=True,input_hashes=original),indent=2)+'\n')
