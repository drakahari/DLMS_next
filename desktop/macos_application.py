"""Route native Quit/reopen through the existing bounded Desktop lifecycle."""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication


class MacApplication(QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        self.desktop_window = None

    def event(self, event):
        window = getattr(self, 'desktop_window', None)
        if window is not None:
            if event.type() == QEvent.Type.Quit:
                if window._closing:
                    return super().event(event)
                # closeEvent owns pending-save/maintenance/Server decisions.
                window.close()
                event.accept()
                return True
            if event.type() == QEvent.Type.ApplicationActivate:
                if not window._closing:
                    window.showNormal()
                    window.raise_()
                    window.activateWindow()
        return super().event(event)

    def bind_window(self, window):
        self.desktop_window = window
        menu = window.menuBar().addMenu('DLMS Desktop')
        quit_action = QAction('Quit DLMS Desktop', window)
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(window.close)
        menu.addAction(quit_action)
