"""Original artwork and launcher resources remain tied to one declared input."""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from package_fedora.prepare_desktop_icons import APP_ID, ROOT, SOURCE, SOURCE_SHA256


def test_selected_artwork_and_resources():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA256
    with Image.open(SOURCE) as image:
        assert image.size == (64, 64)
    for size in (16, 24, 32, 48, 64):
        path = ROOT / f"desktop_assets/icons/hicolor/{size}x{size}/apps/{APP_ID}.png"
        with Image.open(path) as image:
            assert image.size == (size, size)
    with Image.open(ROOT / "desktop_assets/icons/windows/DLMSDesktop.ico") as image:
        assert image.size == (64, 64)
    with Image.open(ROOT / "desktop_assets/icons/macos/DLMSDesktop.icns") as image:
        assert image.size[0] >= 64
    app = QApplication.instance() or QApplication([])
    icon = QIcon(str(SOURCE))
    assert not icon.isNull()
    assert not icon.pixmap(16, 16).isNull()
    assert not icon.pixmap(32, 32).isNull()
    assert app is not None


def test_launcher_template_is_uninstalled():
    template = (ROOT / f"package_fedora/desktop/{APP_ID}.desktop.in").read_text()
    assert "Exec=@EXECUTABLE@" in template
    assert f"Icon={APP_ID}" in template
    assert "Terminal=false" in template


def test_original_badge_regeneration_is_exact(tmp_path, monkeypatch):
    from package_fedora import prepare_desktop_icons as icons
    target = tmp_path / 'desktop_assets'
    target.mkdir()
    monkeypatch.setattr(icons, 'ROOT', tmp_path)
    monkeypatch.setattr(icons, 'SOURCE', target / 'dlms_omarchy.png')
    icons.main()
    expected = ROOT / 'desktop_assets'
    for path in target.rglob('*'):
        if path.is_file():
            assert path.read_bytes() == (expected / path.relative_to(target)).read_bytes()
    provenance = (expected / 'ICON_PROVENANCE.md').read_text()
    assert 'MIT License' in provenance and 'No external image' in provenance
