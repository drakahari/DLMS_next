"""Qt-local feedback/keyboard checks; no host input and no data mutation."""
import argparse
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QMessageBox
from tests.gate1.qt_checks import QtChecks


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    q=QtChecks(a.profile,automated=True)
    save,opener,warning=QFileDialog.getSaveFileName,QFileDialog.getOpenFileName,QMessageBox.warning
    try:
        q.go('/settings/backup')
        panel=q.window.settings_panel
        assert q.window._settings_ready('backup')
        existing=a.output/'existing <synthetic>.zip';existing.write_bytes(b'unchanged synthetic zip placeholder')
        QFileDialog.getSaveFileName=lambda *args,**kw:(str(existing),'')
        button=q.window.settings_buttons['create_backup']
        ticket=q.window._begin_feedback('create_backup');q.window._feedback(ticket,'Prior successful backup','success')
        button.setFocus();QTest.keyClick(button,Qt.Key.Key_Return);q.delay(.2)
        label=panel.action_status['create_backup'];message=label.text()
        assert 'refused' in message and message==q.window.statusBar().currentMessage()
        assert existing.read_bytes()==b'unchanged synthetic zip placeholder'
        assert label.textFormat()==Qt.TextFormat.PlainText
        assert label.accessibleDescription()==message and button.hasFocus()
        assert not q.window._feedback(ticket,'Late saved','success')
        # Recovery/failure messages supersede terminal output in all representations.
        q.window.statusBar().showMessage('Recovery requires inspection')
        assert q.window.statusBar().accessibleDescription()=='Recovery requires inspection'
        q.window._render_backup_feedback()
        assert not label.isVisible() and not q.window.operation_feedback.message
        ticket=q.window._begin_feedback('create_backup')
        assert q.window.statusBar().accessibleDescription()==''
        q.window._feedback(ticket,message,'error')
        from desktop.settings_surface import THEME_REGISTRY
        coverage=[]
        for theme in THEME_REGISTRY:
            panel.set_theme(theme);q.window._style_mode_control(theme);q.delay(.03)
            assert label.property('severity')=='error' and label.text()==message
            assert '2px solid' in panel.styleSheet()
            coverage.append(theme)
        for theme in ('light','dark','ethereal'):
            panel.set_theme(theme);q.window._style_mode_control(theme)
            for width in (1280,640):
                q.window.resize(width,850);q.delay(.15)
                panel.backup_page[0].ensureWidgetVisible(label,12,12);q.delay(.15)
                assert label.width()>150 and label.height()>40
                assert panel.backup_page[0].horizontalScrollBar().maximum()==0
                q.window.grab().save(str(a.output/f'{theme}-{width}-refusal.png'))
        QFileDialog.getSaveFileName=lambda *args,**kw:('','')
        button.setFocus();QTest.keyClick(button,Qt.Key.Key_Space);q.delay(.1)
        assert button.hasFocus() and 'canceled' in label.text()
        assert label.text()==q.window.statusBar().currentMessage()
        QTest.keyClick(button,Qt.Key.Key_Tab);q.delay(.05)
        QTest.keyClick(q.app.focusWidget(),Qt.Key.Key_Backtab);q.delay(.05)
        assert button.hasFocus()
        QMessageBox.warning=lambda *args,**kw:None
        QFileDialog.getOpenFileName=lambda *args,**kw:(str(a.output/'not-there.zip'),'')
        importer=q.window.settings_buttons['backup'];importer.click();q.delay(.1)
        assert importer.hasFocus() and not q.window.import_in_progress
        assert panel.action_status['backup'].text()==q.window.statusBar().currentMessage()
        assert panel.action_status['backup'].property('severity')=='error'
        assert not panel.action_status['create_backup'].isVisible()
        QFileDialog.getOpenFileName=lambda *args,**kw:('','')
        importer.click();q.delay(.1)
        assert importer.hasFocus() and 'canceled' in panel.action_status['backup'].text()
        assert panel.action_status['backup'].text()==q.window.statusBar().currentMessage()
        result={'passed':True,'themes':coverage,'scale':q.window.devicePixelRatioF(),'keyboard':'application-local Return/Space/Tab/Backtab only','collision_unchanged':True,'inline_bottom_equal':True,'late_success_ignored':True,'invalid_import_focus':True,'physical_input':False}
        (a.output/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    finally:
        QFileDialog.getSaveFileName,QFileDialog.getOpenFileName,QMessageBox.warning=save,opener,warning
        q.close()

if __name__=='__main__':main()
