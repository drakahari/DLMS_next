"""Final-file FUSE lifetime/Local-return check with exact daemon identification."""
from pathlib import Path
import argparse,os,json,subprocess,time
from tests.package.normal_local_settings_smoke import backend_nonce,descendants,starttime,stop_exact_owned,request


def main():
    p=argparse.ArgumentParser();p.add_argument('--image',type=Path,required=True);p.add_argument('--normal-evidence',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.absolute();out.mkdir(mode=0o700,parents=True,exist_ok=False);base=a.normal_evidence.absolute();image=a.image.absolute()
    env={'PATH':'/nonexistent','FUSERMOUNT_PROG':'/usr/bin/fusermount3','LANG':'C.UTF-8','QT_QPA_PLATFORM':'offscreen'}
    for k,leaf in [('HOME','home'),('XDG_DATA_HOME','data'),('XDG_CONFIG_HOME','config'),('XDG_CACHE_HOME','cache'),('TMPDIR','tmp'),('XDG_RUNTIME_DIR','runtime')]:env[k]=str(base/leaf)
    state=base/'data/dlms-desktop-appimage-test/profiles/appimage01';expected=json.loads((state/'desktop-profile.json').read_text());outer=image.stat()
    with (out/'launch.log').open('w') as log:
        proc=subprocess.Popen([str(image),'--profile','appimage01'],env=env,cwd=out,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);known={proc.pid:starttime(proc.pid)};daemons={}
        try:
            until=time.monotonic()+35
            while time.monotonic()<until:
                assert proc.poll() is None;known.update({n:starttime(n) for n in descendants(proc.pid)})
                owner=backend_nonce(proc.pid)
                if owner:
                    try:
                        if request(expected['port'],owner[1],'GET','/_desktop/ready')[0]==200:break
                    except OSError:pass
                time.sleep(.08)
            else:raise TimeoutError('return to Local')
            window=json.loads((state/'instance-owner.json').read_text());pipe=os.readlink(f"/proc/{window['pid']}/fd/3")
            # Only stat process/executable metadata globally. Inspect contents
            # solely after matching this exact task-built AppImage inode+UID.
            for entry in Path('/proc').iterdir():
                if not entry.name.isdigit():continue
                try:
                    if entry.stat().st_uid!=os.getuid():continue
                    exe=(entry/'exe').stat()
                    if (exe.st_dev,exe.st_ino)!=(outer.st_dev,outer.st_ino):continue
                    raw=(entry/'environ').read_bytes();values=dict(x.split(b'=',1) for x in raw.split(b'\0') if b'=' in x)
                    if values.get(b'HOME')!=env['HOME'].encode() or values.get(b'TMPDIR')!=env['TMPDIR'].encode():continue
                    peer=any(os.readlink(fd)==pipe for fd in (entry/'fd').iterdir())
                    if peer:daemons[int(entry.name)]=starttime(int(entry.name))
                except (OSError,ValueError):pass
            assert len(daemons)==1,daemons
            assert request(expected['port'],owner[1],'GET','/library')[0]==200
            assert request(expected['port'],owner[1],'GET','/study-history')[0]==200
            assert json.loads((state/'desktop-profile.json').read_text())==expected
            assert request(expected['port'],owner[1],'POST','/api/shutdown')[0]==200;assert proc.wait(timeout=30)==0
            end=time.monotonic()+8
            while time.monotonic()<end and any(starttime(pid)==born for pid,born in daemons.items()):time.sleep(.05)
            assert all(starttime(pid)!=born for pid,born in daemons.items()),('FUSE-daemon-leftover',daemons)
            assert not stop_exact_owned(proc,known)
            (out/'result.json').write_text(json.dumps({'normal_final_AppImage':True,'returned_to_Local':True,'same_profile_origin':expected,'exact_FUSE_daemon_identity':daemons,'FUSE_daemon_exited_after_close':True,'backend_helpers_cleaned':True,'no_unrelated_signaling':True},indent=2)+'\n')
            print('Normal AppImage return-to-Local and exact FUSE daemon/backend/helper cleanup passed')
        finally:assert not stop_exact_owned(proc,known)

if __name__=='__main__':main()
