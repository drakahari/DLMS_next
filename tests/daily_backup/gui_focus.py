"""App-local native key events only; never host desktop input."""
import argparse,json
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog
from tests.gate1.qt_checks import QtChecks


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    q=QtChecks(a.profile,automated=True);a.output.mkdir(parents=True,exist_ok=False)
    old_open,old_save=QFileDialog.getOpenFileName,QFileDialog.getSaveFileName
    calls=[]
    try:
        q.go('/settings/backup');assert q.window._settings_ready('backup')
        QFileDialog.getOpenFileName=lambda *args,**kw:(calls.append('import') or ('',''))
        QFileDialog.getSaveFileName=lambda *args,**kw:(calls.append('save') or ('',''))
        for action in ('backup','create_backup'):
            button=q.window.settings_buttons[action];button.setFocus();q.delay(.1)
            QTest.keyClick(button,Qt.Key.Key_Space);q.delay(.1)
            assert button.hasFocus() and not q.window.import_in_progress and not q.window._backup_creating
            QTest.keyClick(button,Qt.Key.Key_Tab);q.delay(.1)
            assert q.app.focusWidget() is not button
            QTest.keyClick(q.app.focusWidget(),Qt.Key.Key_Backtab);q.delay(.1)
            assert button.hasFocus()
        for theme in ('light','dark','ethereal'):
            q.window.settings_panel.set_theme(theme)
            for width in (1280,640):
                q.window.resize(width,850);q.delay(.2)
                for action in ('create_backup','backup'):
                    button=q.window.settings_buttons[action]
                    q.window.settings_panel.backup_page[0].ensureWidgetVisible(button,20,40)
                    button.setFocus();q.delay(.2)
                    assert button.isVisible() and button.width()>100
                    q.window.grab().save(str(a.output/f'{theme}-{width}-{action}.png'))
        result={'pass':True,'app_local_space':calls,'cancel_returns_focus':True,'tab_backtab':True,'physical_input':False}
        (a.output/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    finally:
        QFileDialog.getOpenFileName,QFileDialog.getSaveFileName=old_open,old_save;q.close()

if __name__=='__main__':main()
