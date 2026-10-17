"""The frozen sidebar's captured SVG symbol has visible rendered pixels."""
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

from desktop.settings_icons import sidebar_icon


def test_captured_settings_symbol_renders():
    app = QApplication.instance() or QApplication([])
    icon = sidebar_icon("settings", "#edccaa")
    assert not icon.isNull()
    image = icon.pixmap(QSize(24, 24)).toImage()
    assert not image.isNull()
    assert any(image.pixelColor(x, y).alpha() > 0
               for y in range(image.height()) for x in range(image.width()))
    assert app is QApplication.instance()
