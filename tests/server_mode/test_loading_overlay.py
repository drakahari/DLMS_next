"""Loading renderer stays active, but native pixels/input remain covered."""
from types import SimpleNamespace
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QLabel,QWidget,QStackedLayout
from desktop.shell import DesktopWindow
from desktop.settings_surface import THEME_REGISTRY

@pytest.fixture(scope='module')
def application():
    return QApplication.instance() or QApplication([])

@pytest.mark.parametrize('size',[(1000,720),(420,650),(840,1300)])
@pytest.mark.parametrize('theme',['light','dark','ethereal'])
def test_full_opaque_overlay_input_and_failure(application,size,theme):
    shell=QWidget();stack=QStackedLayout(shell);stack.setStackingMode(QStackedLayout.StackingMode.StackAll);stack.setContentsMargins(0,0,0,0)
    view=QWidget(shell);view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    label=QLabel('Loading Server page…',shell);color=THEME_REGISTRY[theme]['colors']['body_base'];label.setStyleSheet(f'background:{color};')
    stack.addWidget(view);stack.addWidget(label);shell.resize(*size);shell.show();application.processEvents()
    window=SimpleNamespace(view=view,server_status=label,_server_surface_stack=stack,_server_view_focus_policy=view.focusPolicy())
    try:
        for loading in [True,False,True]:
            DesktopWindow._set_server_page_exposed(window,False,loading=loading);application.processEvents()
            assert not window._server_page_exposed and not view.isEnabled()
            assert view.focusPolicy()==Qt.FocusPolicy.NoFocus and not view.hasFocus()
            assert view.isVisible()==loading
            assert label.geometry()==shell.rect() and stack.currentWidget() is label
            for x,y in [(1,1),(shell.width()-2,1),(1,shell.height()-2),(shell.width()//2,shell.height()//2)]:assert shell.childAt(x,y) is label
            assert not label.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        DesktopWindow._set_server_page_exposed(window,True);application.processEvents()
        assert window._server_page_exposed and view.isEnabled() and view.isVisible()
        assert view.focusPolicy()==Qt.FocusPolicy.StrongFocus and not label.isVisible()
        assert stack.currentWidget() is view
    finally:shell.close();shell.deleteLater();application.processEvents()

@pytest.mark.parametrize('theme',list(THEME_REGISTRY))
def test_loading_base_is_an_opaque_color(theme):
    from PySide6.QtGui import QColor
    color=QColor(THEME_REGISTRY[theme]['colors']['body_base'])
    assert color.isValid() and color.alpha()==255
