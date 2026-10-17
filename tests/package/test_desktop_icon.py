"""Original artwork and launcher resources remain tied to one declared input."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
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
    generated = {path.relative_to(target): path for path in target.rglob('*') if path.is_file()}
    assert set(generated) == {
        Path('dlms-badge.svg'), Path('dlms_omarchy.png'),
        *(Path(f'icons/hicolor/{size}x{size}/apps/{APP_ID}.png') for size in (16, 24, 32, 48, 64)),
        Path('icons/windows/DLMSDesktop.ico'), Path('icons/macos/DLMSDesktop.icns'),
    }
    for name, path in generated.items():
        if name.suffix == '.svg':
            assert path.read_bytes() == (expected / name).read_bytes()
        else:
            _assert_same_icon_pixels(path, expected / name)
    provenance = (expected / 'ICON_PROVENANCE.md').read_text()
    assert 'MIT License' in provenance and 'No external image' in provenance


def _assert_same_icon_pixels(actual, expected):
    # Compressed PNG streams vary with the native encoder (CI produced the
    # exact same RGBA image in 3214 bytes versus the source's 3201). Preserve
    # exact source SHA checks above, and compare every generated representation
    # by format, dimensions and all decoded pixels, never approximate similarity.
    with Image.open(actual) as left, Image.open(expected) as right:
        assert left.format == right.format
        if left.format == 'ICO':
            assert left.ico.sizes() == right.ico.sizes()
            frames = ((left.ico.getimage(size), right.ico.getimage(size))
                      for size in sorted(left.ico.sizes()))
        elif left.format == 'ICNS':
            assert sorted(left.info['sizes']) == sorted(right.info['sizes'])
            frames = ((left.icns.getimage(size), right.icns.getimage(size))
                      for size in sorted(left.info['sizes']))
        else:
            assert left.format == 'PNG'
            frames = ((left, right),)
        for before, after in frames:
            assert before.size == after.size
            assert before.convert('RGBA').tobytes() == after.convert('RGBA').tobytes()


def test_regeneration_allows_only_encoding_variation(tmp_path):
    first, second = tmp_path / 'first.png', tmp_path / 'second.png'
    image = Image.new('RGBA', (32, 32), '#12324a')
    image.save(first, compress_level=0)
    image.save(second, compress_level=9)
    assert first.read_bytes() != second.read_bytes()
    _assert_same_icon_pixels(first, second)
    image.putpixel((0, 0), (255, 0, 0, 255))
    image.save(second)
    with pytest.raises(AssertionError):
        _assert_same_icon_pixels(first, second)
    image.resize((16, 16)).save(second)
    with pytest.raises(AssertionError):
        _assert_same_icon_pixels(first, second)
