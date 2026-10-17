"""Isolated native snapshot transport proof; not ordinary chooser acceptance."""
import argparse
import hashlib
import json
import time


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);a=p.parse_args()
    import package_windows_webview2
    package_windows_webview2.ACTIVE=True
    from desktop.webview2_shell import DesktopWindow
    import desktop.shell
    desktop.shell.DesktopWindow=DesktopWindow
    from tests.gate1.qt_checks import QtChecks
    from desktop.isolation import PROJECT,AREA
    from desktop.windows_file_selection import capture,SnapshotStore
    q=QtChecks(a.profile,automated=True)
    report={'source_instrumented':True,'normal_package':False,'chooser_contract_tested':False}
    store=None
    try:
        fixture=PROJECT/'.gate1/windows-native'/(a.profile+' ordinary 日本語')
        fixture.mkdir(mode=0o700,exist_ok=False)
        source=fixture/'question bank é 日本語.txt'
        original=(PROJECT/'fixtures/gate1-neutral-quiz.txt').read_bytes()
        source.write_bytes(original)
        batch=capture([source],blocked_roots=[AREA])
        store=SnapshotStore(q.paths['root'])
        try:snapshots=store.stage(batch)
        finally:batch.close()
        snapshot=snapshots[0]
        source.write_bytes(b'Changed after the snapshot; browser must see the original.\n')
        try:snapshot.path.write_bytes(b'Forbidden mutation')
        except PermissionError:report['sealed_copy_write_denied']=True
        else:raise AssertionError('The retained snapshot did not exclude writes')
        q.go('/upload')
        # Direct test-only substitution isolates Chrome's actual file reading
        # from the separate native chooser/consent workflow under development.
        q.window.view.page().chooseFiles=lambda *args:[str(snapshot.path)]
        done=[]
        q.window.view.command('eval',script="document.querySelector('input[name=file]').click();true",world=0,
                              gesture=True,callback=done.append)
        deadline=time.monotonic()+10
        while not done and time.monotonic()<deadline:q.delay(.05)
        q.wait("document.querySelector('input[name=file]').files.length===1")
        actual=q.js("""(async()=>{const f=document.querySelector('input[name=file]').files[0];
          const hash=await crypto.subtle.digest('SHA-256',await f.arrayBuffer());
          return {name:f.name,size:f.size,sha256:[...new Uint8Array(hash)].map(x=>x.toString(16).padStart(2,'0')).join('')}})()""")
        assert actual=={'name':source.name,'size':len(original),'sha256':hashlib.sha256(original).hexdigest()},actual
        q.go('/library')
        assert snapshot.path.is_file() and not store.closed
        report.update(passed=True,actual_browser_file=actual,original_changed_after_copy=True,
                      retained_across_navigation=True)
    finally:
        q.close();q.delay(.3);report['close_complete']=q.window._close_complete
        if store is not None and report['close_complete']:
            report['cleanup_errors']=list(store.close())
            report['snapshot_root_removed']=not store.path.exists()
        (q.paths['root']/'wv-snapshot-read.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)
    assert report.get('passed') and report['close_complete'] and not report['cleanup_errors'] and report['snapshot_root_removed']


if __name__=='__main__':main()
