"""Qt and the uninstalled launcher template use one desktop-entry identity."""
from pathlib import Path

from PySide6.QtWidgets import QApplication

from desktop.identity import DESKTOP_FILE_ID, configure_application_identity


def test_desktop_entry_identity():
    app = QApplication.instance() or QApplication(["DLMS-Desktop"])
    configure_application_identity(app)
    assert app.desktopFileName() == DESKTOP_FILE_ID
    template = (Path(__file__).resolve().parents[2] / "package_fedora/desktop"
                / f"{DESKTOP_FILE_ID}.desktop.in").read_text()
    assert f"Icon={DESKTOP_FILE_ID}\n" in template
    assert "StartupWMClass=" not in template  # X11 mapping awaits installed qualification.
    assert "Exec=@EXECUTABLE@\n" in template
