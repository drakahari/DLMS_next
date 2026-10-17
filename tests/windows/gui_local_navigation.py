"""Source Qt superseded-load probe, distinct from normal-package evidence."""
import argparse
import json
from pathlib import Path
import time

from PySide6.QtCore import QTimer,QUrl
from tests.gate1.qt_checks import QtChecks
from desktop.isolation import PROJECT

def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);a=p.parse_args()
    q=QtChecks(a.profile,automated=True);events=[]
    out=PROJECT/'.gate1/windows-native/chooser-blanking-01'/f'{a.profile}-navigation.json'
    try:
        view=q.window.view
        def finished(ok):
            events.append({'ok':ok,'loading':view.page().isLoading(),'visible':view.isVisible(),
                           'fallback':q.window.settings_fallback.isVisible(),
                           'route':view.url().path(),'renderer':view.page().renderProcessPid()})
        view.loadFinished.connect(finished)
        for _ in range(12):
            view.setUrl(QUrl(f'http://127.0.0.1:{q.window.port}/settings/backup'))
            QTimer.singleShot(5,lambda:view.setUrl(QUrl(f'http://127.0.0.1:{q.window.port}/upload')))
            q.delay(.02)
            view.setUrl(QUrl(f'http://127.0.0.1:{q.window.port}/'))
            q.delay(.15)
        q.wait("document.readyState==='complete' && location.pathname==='/'",20)
        q.delay(1)
        state={'view_visible':view.isVisible(),'fallback_visible':q.window.settings_fallback.isVisible(),
               'backend_alive':q.window.backend.poll() is None,'events':events}
        out.write_text(json.dumps(state,indent=2)+'\n')
        print(json.dumps({'events':len(events),'canceled_while_loading':sum(not x['ok'] and x['loading'] for x in events),
                          'view_visible':state['view_visible'],'fallback_visible':state['fallback_visible']}))
    finally:q.close()

if __name__=='__main__':main()
