"""Source Qt classification checks; never normal-package physical evidence."""
import argparse
import json

from PySide6.QtCore import QTimer
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWidgets import QFileDialog
from tests.gate1.qt_checks import QtChecks
from desktop.window_events import WindowEvents
from desktop.isolation import AREA,PROJECT

def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);a=p.parse_args()
    q=QtChecks(a.profile,automated=True)
    collector=WindowEvents(q.window);q.window.window_events=collector;collector.bind(q.window.view)
    try:
        q.delay(1.5)
        q.window.view.page().triggerAction(QWebEnginePage.WebAction.Reload)
        q.wait("document.readyState==='complete'",20);q.delay(1.5)
        q.go('/upload');q.delay(1.5)
        # This is the actual native Windows dialog in an app-local Qt harness,
        # canceled by its own Qt object. No desktop-wide input is generated.
        picker=QFileDialog(q.window,'Synthetic chooser probe',str(AREA))
        picker.setFileMode(QFileDialog.FileMode.ExistingFile)
        picker.setOption(QFileDialog.Option.DontUseNativeDialog,False)
        QTimer.singleShot(1200,picker.reject)
        code=picker.exec()
        assert code==0 and not picker.selectedFiles()
        q.window.resize(q.window.width()-80,q.window.height()-60);q.delay(1.5)
        collector.stop()
        records=[json.loads(x) for x in collector.path.read_text().splitlines()]
        assert any(x['event']=='document' and x['navigation']=='reload' for x in records)
        assert sum(x['event']=='document' for x in records)>=3
        assert not any(x['event']=='renderer-terminated' for x in records)
        assert any(x['event']=='native-window-bound' for x in records)
        assert any(x['event']=='sample' and x.get('exposed') is not None for x in records)
        assert all(x.get('utc','').endswith('Z') for x in records)
        assert records[-1]['event']=='capture-stop'
        backend={x['pid'] for x in records if x['event']=='backend'}
        assert len(backend)==1 and q.window.backend.pid in backend
        assert all(x['exit'] is None for x in records if x['event']=='backend')
        assert q.window.view.isVisible() and not q.window.settings_fallback.isVisible()
        result={'source_Qt':True,'native_picker_canceled':True,'reload_classified':True,
                'backend_stable':True,'no_renderer_termination':True,'normal_physical_acceptance':False,
                'trace':str(collector.path)}
        (PROJECT/'.gate1/windows-native/chooser-blanking-01'/f'{a.profile}-events.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))
    finally:collector.stop();q.close()

if __name__=='__main__':main()
