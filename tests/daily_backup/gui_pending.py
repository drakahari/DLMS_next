"""Simulated accepted-record gate through native backup UI; no app mutation."""
import argparse,json,time
from pathlib import Path
from PySide6.QtWidgets import QFileDialog
from desktop.requests import PendingRequests
from desktop.profile_state import read_manifest,atomic_json
from tests.gate1.qt_checks import QtChecks
from tests.settings.gui_native_roundtrip import facts


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);a=p.parse_args()
    q=QtChecks(a.profile,automated=True);old=QFileDialog.getSaveFileName
    folder=q.paths['root'].parent.parent/'daily-backup'/'pending-visible';folder.mkdir(parents=True,exist_ok=True)
    destination=folder/(a.profile+'.zip')
    try:
        before=facts(q.paths['backend']);identity=read_manifest(q.paths,a.profile)
        requests=object.__new__(PendingRequests);requests.root=q.paths['root']/'pending-requests'
        identifier='daily_backup_pending_0001';payload={'request_id':identifier,'marks':[]}
        context={'profile_uuid':identity['uuid'],'epoch':identity['epoch']}
        record=requests._record('review_save',payload,identifier,context)
        leaf=requests._path('review_save',identifier);atomic_json(leaf,record)
        q.go('/settings/backup')
        QFileDialog.getSaveFileName=lambda *args,**kw:(str(destination),'')
        q.window.settings_buttons['create_backup'].click()
        q.wait("document.body.innerText.includes('Accepted Desktop actions')",20)
        deadline=time.monotonic()+10
        while q.window._backup_creating and time.monotonic()<deadline:q.delay(.1)
        assert not destination.exists() and not q.window._backup_creating, (str(q.window.view.url().toString()),q.window.statusBar().currentMessage())
        assert facts(q.paths['backend'])==before and json.loads(leaf.read_text())==record
        leaf.rename(q.paths['root']/'simulated-pending-preserved.json')
        print(json.dumps({'pass':True,'simulated_accepted_record':True,'visible_refusal':True,'destination_absent':True,'data_unchanged':True}))
    finally:
        QFileDialog.getSaveFileName=old;q.close()

if __name__=='__main__':main()
