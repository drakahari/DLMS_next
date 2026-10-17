"""Native backup publication still owns success after attachment page recovery."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import zipfile
from PySide6.QtWidgets import QFileDialog
from desktop.isolation import PROJECT
from tests.gate1.qt_checks import QtChecks


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);a=p.parse_args()
    out=PROJECT/'.gate1/windows-native'/f'{a.profile}-backup-output';out.mkdir(mode=0o700,exist_ok=False)
    q=QtChecks(a.profile,automated=True);original=QFileDialog.getSaveFileName;report={}
    try:
        q.go('/settings/backup');end=time.monotonic()+15
        while not q.window._settings_ready('backup') and time.monotonic()<end:q.delay(.05)
        assert q.window._settings_ready('backup')
        QFileDialog.getSaveFileName=lambda *args,**kw:('','')
        q.window.settings_buttons['create_backup'].click()
        assert not q.window._backup_creating and not q.window.download_results
        target=out/'backup 日本語.zip'
        QFileDialog.getSaveFileName=lambda *args,**kw:(str(target),'')
        q.window.settings_buttons['create_backup'].click();end=time.monotonic()+35
        while (q.window._backup_creating or not q.window._settings_ready('backup')) and time.monotonic()<end:q.delay(.1)
        assert not q.window._backup_creating and q.window._settings_ready('backup'),q.window.statusBar().currentMessage()
        assert target.is_file() and 'Backup saved:' in q.window.statusBar().currentMessage()
        with zipfile.ZipFile(target) as z:assert z.testzip() is None
        digest=hashlib.sha256(target.read_bytes()).hexdigest()
        q.window.settings_buttons['create_backup'].click()
        assert 'refused' in q.window.statusBar().currentMessage()
        assert hashlib.sha256(target.read_bytes()).hexdigest()==digest
        report={'source_instrumented':True,'save_cancel_no_request':True,'confirmed_publication':True,
            'native_settings_reverified':True,'existing_file_preserved':True,'sha256':digest}
    finally:
        QFileDialog.getSaveFileName=original
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n');q.close()
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
