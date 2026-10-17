"""Native Settings focus/layout checks with explicit asynchronous readiness.

Space/Tab/Backtab events target only our Qt widgets. Chooser cancellation is
stubbed inside the process; this does not claim physical chooser acceptance.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import time
import sys
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog
from tests.gate1.qt_checks import QtChecks


def ready(q,kind):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        if q.window._settings_ready(kind):return
        q.delay(.05)
    raise TimeoutError('Native Settings document was not verified: '+kind)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--profile',required=True)
    a=p.parse_args()
    if not a.profile.startswith('dailyjourney'):raise ValueError('Dedicated synthetic profile required')
    q=QtChecks(a.profile,automated=True)
    report={'profile':a.profile,'kind':'instrumented-frozen-Qt' if getattr(sys,'frozen',False) else 'source-app-local-Qt','physical_keyboard':False,
            'scale':q.app.devicePixelRatio(),'layouts':[]}
    old_open,old_save=QFileDialog.getOpenFileName,QFileDialog.getSaveFileName
    calls=[]
    try:
        db=q.paths['backend']/'results.db'
        before=hashlib.sha256(db.read_bytes()).hexdigest()
        q.go('/settings/backup');ready(q,'backup')
        QFileDialog.getOpenFileName=lambda *args,**kwargs:(calls.append('import') or ('',''))
        QFileDialog.getSaveFileName=lambda *args,**kwargs:(calls.append('save') or ('',''))
        for action in ('backup','create_backup'):
            button=q.window.settings_buttons[action]
            button.setFocus();q.delay(.1)
            QTest.keyClick(button,Qt.Key.Key_Space);q.delay(.1)
            assert button.hasFocus() and not q.window.import_in_progress and not q.window._backup_creating
            QTest.keyClick(button,Qt.Key.Key_Tab);q.delay(.1)
            target=q.app.focusWidget()
            assert target is not None and target is not button
            QTest.keyClick(target,Qt.Key.Key_Backtab);q.delay(.1)
            assert button.hasFocus()
        assert calls==['import','save'],calls
        report['cancel_focus_and_tab_order']=True
        report['inline_status']=q.window.settings_panel.action_status['create_backup'].text()
        assert 'canceled' in report['inline_status'].lower()
        for theme in ('light','dark','ethereal'):
            for kind in ('backup','reset-remove'):
                q.go('/settings/'+kind);ready(q,kind)
                panel=q.window.settings_panel
                panel.set_theme(theme)
                for width in (1280,640):
                    q.window.resize(width,850);q.delay(.2)
                    assert panel.stack.isVisible()
                    for action in (('create_backup','backup') if kind=='backup' else ('exam','study','learning')):
                        button=q.window.settings_buttons[action]
                        scroll=panel.backup_page[0] if kind=='backup' else panel.reset_page[0]
                        scroll.ensureWidgetVisible(button,20,40)
                        button.setFocus();q.delay(.1)
                        assert button.isVisible() and button.width()>100 and button.hasFocus()
                        assert button.accessibleName()
                    image=q.paths['root']/f'daily-settings-{theme}-{kind}-{width}.png'
                    assert q.window.grab().save(str(image))
                    report['layouts'].append(dict(theme=theme,page=kind,width=width,screenshot=str(image),
                        page_visible=True,native_controls_visible=True))
        assert hashlib.sha256(db.read_bytes()).hexdigest()==before
        report['database_unchanged']=True
        report['pass']=True
    finally:
        QFileDialog.getOpenFileName,QFileDialog.getSaveFileName=old_open,old_save
        (q.paths['root']/'daily-settings.json').write_text(json.dumps(report,indent=2)+'\n')
        q.close()
    print(json.dumps(report,indent=2))
    return 0 if report.get('pass') else 1

if __name__=='__main__':raise SystemExit(main())
