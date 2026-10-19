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
    from package_fedora.prepare_desktop_icons import MASTER, MASTER_SHA256, LINUX_SIZES, WINDOWS_SIZES
    assert hashlib.sha256(MASTER.read_bytes()).hexdigest() == MASTER_SHA256
    assert MASTER.read_bytes() == (ROOT / 'static/favicon.ico').read_bytes()
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA256
    with Image.open(MASTER) as original:
        assert original.format == 'PNG' and original.size == (1024, 1024)
        artwork = original.convert('RGBA')
    with Image.open(SOURCE) as image:
        assert image.size == (64, 64)
        assert image.convert('RGBA').tobytes() == artwork.resize((64, 64), Image.Resampling.LANCZOS).tobytes()
    for size in LINUX_SIZES:
        path = ROOT / f"desktop_assets/icons/hicolor/{size}x{size}/apps/{APP_ID}.png"
        with Image.open(path) as image:
            assert image.format == 'PNG' and image.size == (size, size)
            assert image.convert('RGBA').tobytes() == artwork.resize((size, size), Image.Resampling.LANCZOS).tobytes()
    with Image.open(ROOT / 'desktop_assets/icons/windows/DLMSDesktop.ico') as image:
        assert image.format == 'ICO'
        assert image.ico.sizes() == {(size, size) for size in WINDOWS_SIZES}
        for size in image.ico.sizes():
            frame = image.ico.getimage(size).convert('RGBA')
            assert frame.tobytes() == artwork.resize(size, Image.Resampling.LANCZOS).tobytes()
    with Image.open(ROOT / 'desktop_assets/icons/macos/DLMSDesktop.icns') as image:
        assert image.format == 'ICNS'
        sizes = image.info['sizes']
        assert max(w * scale for w, h, scale in sizes) == 1024
        for size in sizes:
            frame = image.icns.getimage(size).convert('RGBA')
            assert frame.tobytes() == artwork.resize(frame.size, Image.Resampling.LANCZOS).tobytes()
    app = QApplication.instance() or QApplication([])
    icon = QIcon(str(MASTER))
    assert not icon.isNull()
    for size in (16, 32, 64, 256):
        assert not icon.pixmap(size, size).isNull()
    assert app is not None


def test_launcher_template_is_uninstalled():
    template = (ROOT / f"package_fedora/desktop/{APP_ID}.desktop.in").read_text()
    assert "Exec=@EXECUTABLE@" in template
    assert f"Icon={APP_ID}" in template
    assert "Terminal=false" in template


def test_original_master_conversion_is_exact(tmp_path, monkeypatch):
    from package_fedora import prepare_desktop_icons as icons
    target = tmp_path / 'desktop_assets'
    target.mkdir()
    monkeypatch.setattr(icons, 'ROOT', tmp_path)
    monkeypatch.setattr(icons, 'SOURCE', target / 'dlms_omarchy.png')
    master = target / 'dlms-icon-master.png'
    master.write_bytes(icons.MASTER.read_bytes())
    monkeypatch.setattr(icons, 'MASTER', master)
    icons.main()
    expected = ROOT / 'desktop_assets'
    generated = {path.relative_to(target): path for path in target.rglob('*') if path.is_file()}
    assert set(generated) == {
        Path('dlms-icon-master.png'), Path('dlms_omarchy.png'),
        *(Path(f'icons/hicolor/{size}x{size}/apps/{APP_ID}.png') for size in icons.LINUX_SIZES),
        Path('icons/windows/DLMSDesktop.ico'), Path('icons/macos/DLMSDesktop.icns'),
    }
    for name, path in generated.items():
        if name.name == 'dlms-icon-master.png':
            assert path.read_bytes() == (expected / name).read_bytes()
        else:
            _assert_same_icon_pixels(path, expected / name)
    provenance = (expected / 'ICON_PROVENANCE.md').read_text()
    assert 'AI-generated' in provenance and 'not known' in provenance
    assert 'be929c60a0a63373d698934930bac8af686d3a8242072e25954118f783b1af93' in provenance
    assert not (expected / 'dlms-badge.svg').exists()


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


def test_tampered_master_refused_before_generating(tmp_path, monkeypatch):
    from package_fedora import prepare_desktop_icons as icons
    master = tmp_path / 'wrong.png'
    Image.new('RGBA', (1024, 1024), 'red').save(master)
    monkeypatch.setattr(icons, 'MASTER', master)
    monkeypatch.setattr(icons, 'ROOT', tmp_path)
    monkeypatch.setattr(icons, 'SOURCE', tmp_path / 'output.png')
    with pytest.raises(ValueError, match='Canonical DLMS master differs'):
        icons.main()
    assert not (tmp_path / 'output.png').exists()


def test_platform_icon_references_use_canonical_resources():
    master = 'desktop_assets/dlms-icon-master.png'
    ico = 'desktop_assets/icons/windows/DLMSDesktop.ico'
    icns = 'desktop_assets/icons/macos/DLMSDesktop.icns'
    for name in ('desktop/shell.py', 'package_appimage/build.py', 'tools/build_appimage.py'):
        assert master in (ROOT / name).read_text(), name
    for name in ('package_windows/DLMS-Desktop.spec', 'package_windows_webview2/DLMS-Desktop-WebView2.spec'):
        assert ico in (ROOT / name).read_text(), name
    for name in ('package_windows/installer.iss', 'package_windows_webview2/installer.iss'):
        assert ico.replace('/', chr(92)) in (ROOT / name).read_text(), name
    for name in ('package_macos/DLMS-Desktop.spec', 'tools/macos_test_wrapper.py', 'DLMS.spec'):
        assert icns in (ROOT / name).read_text(), name
    assert '/win32icon:$projectRoot/desktop_assets/icons/windows/DLMSDesktop.ico' in (ROOT / 'windows_webview2/build.ps1').read_text()
    from package_fedora.install_pilot import ARTWORK_SHA256
    assert ARTWORK_SHA256 == SOURCE_SHA256
    # Browser favicon URL remains stable and contains the exact master bytes.
    assert (ROOT / master).read_bytes() == (ROOT / 'static/favicon.ico').read_bytes()


def test_resource_manifest_matches_every_declared_file():
    import json
    record = json.loads((ROOT / 'desktop_assets/ICON_RESOURCES.json').read_text())
    assert record['canonical_master'] == 'desktop_assets/dlms-icon-master.png'
    assert record['master_sha256'] == hashlib.sha256((ROOT / record['canonical_master']).read_bytes()).hexdigest()
    assert len(record['resources']) == 14
    paths = set()
    for item in record['resources']:
        assert item['path'] not in paths
        paths.add(item['path'])
        path = ROOT / item['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']
        with Image.open(path) as image:
            assert image.format == item['format'] and list(image.size) == item['size']
    assert {str(p.relative_to(ROOT)) for p in (ROOT / 'desktop_assets/icons').rglob('*') if p.is_file()} <= paths
