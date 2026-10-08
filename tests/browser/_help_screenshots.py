"""Focused Help captures from live controls; ordinary tests never refresh assets."""

import base64
import io
import json
import math
from pathlib import Path

from PIL import Image


HELP_SCREENSHOTS = {
    'settings-appearance-theme.webp': ('/settings/appearance', '.settings-form-section:first-of-type', 390),
    'settings-appearance-save.webp': ('/settings/appearance', '.settings-form-actions', 390),
    'sidebar-theme-selector.webp': ('/settings/appearance', '.dashboard-nav a[href="/settings"], .dashboard-nav a[href="/help/"], .dashboard-theme-quick, .dashboard-navigation-customize, .dashboard-sidebar-version', 1440),
    'settings-layout-study-areas.webp': ('/settings/layout', '#studyAreasHeading, .layout-study-area:nth-of-type(1), .layout-study-area:nth-of-type(2)', 390),
    'settings-layout-restore.webp': ('/settings/layout', '.settings-form-actions, #layoutRestoreDefaults', 390),
}


def capture_help_screenshots(browser, base_url, output):
    """Crop DOM bounds in unmodified Firefox screenshots, retaining native text size."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for filename, (route, selector, width) in HELP_SCREENSHOTS.items():
        browser.set_viewport(width, 1000)
        browser.navigate(base_url + route)
        browser.wait_for_page_ready()
        browser.wait_for("document.querySelector('#dlmsQuickTheme')?.options.length === 26")
        browser.evaluate('document.fonts.ready.then(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))')
        bounds = browser.evaluate("(() => {const nodes=[...document.querySelectorAll(" + json.dumps(selector) + ")];"
                                  "const r=nodes.map(n=>n.getBoundingClientRect());"
                                  "return [Math.min(...r.map(b=>b.left))+scrollX,Math.min(...r.map(b=>b.top))+scrollY,"
                                  "Math.max(...r.map(b=>b.right))+scrollX,Math.max(...r.map(b=>b.bottom))+scrollY];})()")
        shot = browser.command('browsingContext.captureScreenshot', {'context': browser.context, 'origin': 'document'})
        with Image.open(io.BytesIO(base64.b64decode(shot['data']))) as image:
            assert all(math.isfinite(v) for v in bounds), (filename, bounds)
            # Firefox omits the vertical scrollbar from document captures.
            assert image.width == browser.evaluate('document.documentElement.clientWidth'), (filename, image.size, width)
            box = (max(0, math.floor(bounds[0]) - 8), max(0, math.floor(bounds[1]) - 8),
                   min(image.width, math.ceil(bounds[2]) + 8), min(image.height, math.ceil(bounds[3]) + 8))
            image.crop(box).convert('RGB').save(output / filename, format='WEBP', lossless=True)


def capture_control(browser, filename, selector):
    """Refresh one filled Exam Plan control crop without losing form state."""
    filename = Path(filename)
    filename.parent.mkdir(parents=True, exist_ok=True)
    browser.evaluate('document.fonts.ready.then(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))')
    bounds = browser.evaluate("(() => {const r=document.querySelector("+json.dumps(selector)+").getBoundingClientRect();return [r.left+scrollX,r.top+scrollY,r.right+scrollX,r.bottom+scrollY];})()")
    shot = browser.command('browsingContext.captureScreenshot', {'context':browser.context,'origin':'document'})
    with Image.open(io.BytesIO(base64.b64decode(shot['data']))) as image:
        image.crop((max(0,math.floor(bounds[0])-8),max(0,math.floor(bounds[1])-8),min(image.width,math.ceil(bounds[2])+8),min(image.height,math.ceil(bounds[3])+8))).convert('RGB').save(filename,format='WEBP',lossless=True)
