"""Exercise the actual Phase 2 mutations and views using the shared Firefox harness."""
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.browser, pytest.mark.skipif(
    os.environ.get('DLMS_RUN_BROWSER_TESTS') != '1', reason='Opt-in isolated Firefox validation')]


@pytest.mark.parametrize('theme', ['light', 'dark', 'purple-gold', 'maroon-gold'])
@pytest.mark.parametrize('viewport', [(1920, 1080), (1100, 900)])
def test_phase2_real_workflows(monkeypatch, theme, viewport):
    monkeypatch.syspath_prepend(str(ROOT / 'tools'))
    import capture_demo_video_screenshots as capture
    monkeypatch.setattr(capture, 'WIDTH', viewport[0])
    monkeypatch.setattr(capture, 'HEIGHT', viewport[1])
    # Original packed source, saved response, validation/install, real APKG
    # response, saved playable hotspot, editor, and staged structured response.
    ids = {'201', '204', '209', '213', '218', '224', '226', '232', '233', '234', '236', '237'}
    items = [f for f in capture.DOCUMENTATION_FRAMES if f.id in ids]
    output = ROOT / 'build/demo-video/phase2/theme-checks' / f'{theme}-{viewport[0]}'
    original_prepare = capture.prepare

    def prepare(*args):
        original_prepare(*args)
        browser = args[0]
        assert browser.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')

    monkeypatch.setattr(capture, 'prepare', prepare)
    records = capture.capture(items, output, theme)
    assert {r['id'] for r in records} == ids
    assert all(r['dimensions'] == list(viewport) and r['theme'] == theme for r in records)
