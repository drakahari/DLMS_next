"""Local manual theme registry. No app imports, network access, or persistence.

Original themes and Ethereal presentation are preserved verbatim. The pinned
source manifest contains upstream colors; derived web tokens live here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DEFAULT_THEME = "purple-gold"

LEGACY_PALETTES = {'dark': {'scheme': 'dark',
          'page': '#eaf2ff',
          'muted': '#b8c2cc',
          'heading': '#ffffff',
          'body_base': '#020814',
          'body_overlay': 'rgba(2,8,20,.72)',
          'body_overlay_2': 'rgba(2,8,20,.84)',
          'shell': 'rgba(3,12,28,.66)',
          'sidebar1': 'rgba(5,18,40,.96)',
          'sidebar2': 'rgba(3,13,30,.94)',
          'main1': 'rgba(3,12,28,.60)',
          'main2': 'rgba(2,10,23,.78)',
          'panel1': 'rgba(6,20,45,.82)',
          'panel2': 'rgba(5,17,38,.74)',
          'surface': 'rgba(5,18,39,.58)',
          'surface2': 'rgba(17,31,56,.78)',
          'input_bg': 'rgba(3,13,30,.78)',
          'input_text': '#eaf3ff',
          'border': 'rgba(86,158,255,.35)',
          'border_soft': 'rgba(98,155,255,.24)',
          'nav_text': '#e8f2ff',
          'nav_muted': '#b9c8dc',
          'accent': '#1b9ff2',
          'accent2': '#138ad6',
          'accent3': '#0f6fb3',
          'accent_text': '#78bfff',
          'on_accent': '#06192b',
          'link': '#62b5ff',
          'link_hover': '#9bd2ff',
          'shadow': 'rgba(0,0,0,.42)'},
 'light': {'scheme': 'light',
           'page': '#17253a',
           'muted': '#53657d',
           'heading': '#0b1b33',
           'body_base': '#eaf0f7',
           'body_overlay': 'rgba(239,244,250,.84)',
           'body_overlay_2': 'rgba(229,237,246,.90)',
           'shell': 'rgba(248,251,255,.92)',
           'sidebar1': 'rgba(247,250,254,.98)',
           'sidebar2': 'rgba(237,244,251,.98)',
           'main1': 'rgba(250,252,255,.94)',
           'main2': 'rgba(239,245,251,.96)',
           'panel1': 'rgba(255,255,255,.97)',
           'panel2': 'rgba(244,248,252,.97)',
           'surface': 'rgba(237,244,251,.96)',
           'surface2': 'rgba(230,238,248,.96)',
           'input_bg': '#ffffff',
           'input_text': '#10213a',
           'border': 'rgba(55,103,153,.34)',
           'border_soft': 'rgba(71,111,151,.24)',
           'nav_text': '#26384f',
           'nav_muted': '#61738a',
           'accent': '#076fb5',
           'accent2': '#08659e',
           'accent3': '#084f7c',
           'accent_text': '#075f9f',
           'on_accent': '#ffffff',
           'link': '#075f9f',
           'link_hover': '#043f6c',
           'shadow': 'rgba(29,52,76,.16)'},
 'purple-gold': {'scheme': 'dark',
                 'page': '#fff8e8',
                 'muted': '#d7cbe6',
                 'heading': '#ffffff',
                 'body_base': '#160b2b',
                 'body_overlay': 'rgba(24,10,47,.74)',
                 'body_overlay_2': 'rgba(13,7,29,.86)',
                 'shell': 'rgba(28,11,53,.82)',
                 'sidebar1': 'rgba(38,13,69,.97)',
                 'sidebar2': 'rgba(22,8,43,.97)',
                 'main1': 'rgba(28,12,51,.78)',
                 'main2': 'rgba(15,8,31,.90)',
                 'panel1': 'rgba(43,20,75,.88)',
                 'panel2': 'rgba(27,13,50,.86)',
                 'surface': 'rgba(56,27,92,.66)',
                 'surface2': 'rgba(65,31,103,.72)',
                 'input_bg': 'rgba(29,14,52,.92)',
                 'input_text': '#fff8e8',
                 'border': 'rgba(255,198,47,.48)',
                 'border_soft': 'rgba(220,183,88,.30)',
                 'nav_text': '#fff8e8',
                 'nav_muted': '#d7cbe6',
                 'accent': '#f2c230',
                 'accent2': '#d8a914',
                 'accent3': '#a87c00',
                 'accent_text': '#ffd85a',
                 'on_accent': '#241900',
                 'link': '#ffd85a',
                 'link_hover': '#fff0a6',
                 'shadow': 'rgba(0,0,0,.48)'},
 'maroon-gold': {'scheme': 'dark',
                 'page': '#f5f2ed',
                 'muted': '#bfc2c9',
                 'heading': '#ffffff',
                 'body_base': '#0d0e10',
                 'body_overlay': 'rgba(18,8,11,.80)',
                 'body_overlay_2': 'rgba(8,9,10,.92)',
                 'shell': 'rgba(18,19,22,.94)',
                 'sidebar1': 'rgba(91,0,19,.98)',
                 'sidebar2': 'rgba(60,0,13,.99)',
                 'main1': 'rgba(22,23,26,.94)',
                 'main2': 'rgba(11,12,14,.97)',
                 'panel1': 'rgba(31,32,36,.95)',
                 'panel2': 'rgba(23,24,27,.95)',
                 'surface': 'rgba(43,44,49,.90)',
                 'surface2': 'rgba(35,36,40,.94)',
                 'input_bg': 'rgba(16,17,20,.97)',
                 'input_text': '#f5f2ed',
                 'border': 'rgba(255,204,51,.24)',
                 'border_soft': 'rgba(190,194,202,.20)',
                 'nav_text': '#fff8f1',
                 'nav_muted': '#dbc8cc',
                 'accent': '#ffcc33',
                 'accent2': '#ffb71e',
                 'accent3': '#c69214',
                 'accent_text': '#ffde7a',
                 'on_accent': '#211700',
                 'link': '#ffde7a',
                 'link_hover': '#fff0b8',
                 'shadow': 'rgba(0,0,0,.56)'},
 'ethereal': {'scheme': 'dark',
              'page': '#ffcead',
              'muted': '#c9b8a6',
              'heading': '#ffcead',
              'body_base': '#060b1e',
              'body_overlay': 'rgba(6,11,30,.86)',
              'body_overlay_2': 'rgba(4,8,22,.94)',
              'shell': '#040816',
              'sidebar1': '#060b1e',
              'sidebar2': '#040816',
              'main1': '#060b1e',
              'main2': '#040816',
              'panel1': '#10172f',
              'panel2': '#10172f',
              'surface': '#0c1229',
              'surface2': '#131a3a',
              'input_bg': '#060b1e',
              'input_text': '#ffcead',
              'border': '#6d7db6',
              'border_soft': '#6d7db6',
              'nav_text': '#ffcead',
              'nav_muted': '#c9b8a6',
              'accent': '#7d82d9',
              'accent2': '#7d82d9',
              'accent3': '#7d82d9',
              'accent_text': '#c2c4f0',
              'on_accent': '#060b1e',
              'link': '#c2c4f0',
              'link_hover': '#ffcead',
              'shadow': 'rgba(0,0,0,.18)'}}

ETHEREAL_PRESENTATION = {'--theme-body-font': 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
 '--theme-display-font': 'ui-monospace, "Cascadia Mono", "Segoe UI Mono", Menlo, Consolas, monospace',
 '--theme-control-radius': '6px',
 '--theme-panel-radius': '10px',
 '--theme-panel-padding': '24px',
 '--theme-panel-shadow': '0 4px 12px rgba(0,0,0,.18)',
 '--theme-heading-shadow': 'none',
 '--theme-heading-line-height': '1.15',
 '--theme-page-title-size': 'clamp(26px, 2.4vw, 36px)',
 '--theme-page-title-small': '24px',
 '--theme-page-header-space': '16px',
 '--theme-quiet-border': 'color-mix(in srgb, var(--theme-border) 30%, var(--theme-panel-1))',
 '--theme-control-border': '#6d7db6',
 '--theme-legacy-primary-text': '#060b1e',
 '--theme-focus-ring': '#c2c4f0',
 '--theme-progress-fill': '#7d82d9',
 '--theme-selection-bg': '#c2c4f0',
 '--theme-selection-text': '#060b1e'}


def _rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _mix(color, other, amount):
    return '#' + ''.join(f'{round(a * (1 - amount) + b * amount):02x}'
                         for a, b in zip(_rgb(color), _rgb(other)))


def contrast(first, second):
    """sRGB contrast for opaque palette tokens; rendered states need browser QA."""
    def luminance(color):
        values = [value / 255 for value in _rgb(color)]
        return sum((v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4) * weight
                   for v, weight in zip(values, (.2126, .7152, .0722)))
    a, b = luminance(first), luminance(second)
    return (max(a, b) + .05) / (min(a, b) + .05)


def _readable(color, backgrounds, minimum=5.5):
    """Keep the source hue where possible, mixing toward readable black/white."""
    target = max(('#000000', '#ffffff'),
                 key=lambda candidate: min(contrast(candidate, bg) for bg in backgrounds))
    for step in range(101):
        adjusted = _mix(color, target, step / 100)
        if min(contrast(adjusted, bg) for bg in backgrounds) >= minimum:
            return adjusted
    raise ValueError('Theme surfaces cannot share a readable foreground')


def _web_palette(source):
    """Derive opaque web surfaces and semantic roles from a terminal palette.

    Source ANSI names are deliberately not used as educational feedback roles.
    All derivations are deterministic and kept separate from the source manifest.
    """
    scheme = source['mode']
    bg, fg = source['background'], source['foreground']
    panel, surface, raised = (_mix(bg, fg, amount) for amount in (.03, .05, .07))
    backgrounds = (bg, panel, surface, raised)
    page = _readable(fg, backgrounds, 7)
    muted = _readable(source['muted'], backgrounds)
    accent = _readable(source['accent'], backgrounds, 4.5)
    accent_text = _readable(source['accent'], backgrounds)
    on_accent = max(('#000000', '#ffffff'), key=lambda value: contrast(value, accent))
    border = _readable(source['muted'], backgrounds, 3)
    selection = _readable(accent, (on_accent,), 7)
    colors = dict(scheme=scheme, page=page, muted=muted, heading=page,
                  body_base=bg, body_overlay=bg, body_overlay_2=bg, shell=bg,
                  sidebar1=bg, sidebar2=bg, main1=bg, main2=bg,
                  panel1=panel, panel2=panel, surface=surface, surface2=raised,
                  input_bg=bg, input_text=page, border=border, border_soft=border,
                  nav_text=page, nav_muted=muted, accent=accent, accent2=accent,
                  accent3=accent, accent_text=accent_text, on_accent=on_accent,
                  link=accent_text, link_hover=page,
                  shadow='rgba(0,0,0,.16)' if scheme == 'light' else 'rgba(0,0,0,.42)')
    extra = {'--theme-focus-ring': accent_text, '--theme-progress-fill': accent,
             '--theme-control-border': border, '--theme-selection-bg': selection,
             '--theme-selection-text': on_accent, '--theme-placeholder': muted,
             '--theme-legacy-primary-text': on_accent, '--theme-primary-action-text': on_accent, '--theme-primary-action-bg': accent}
    # Familiar feedback hues remain distinguishable even in monochrome themes.
    for role, hue in (('success', '#2f9b6d'), ('warning', '#c58b19'), ('error', '#c63f52')):
        state_surface = _mix(surface, hue, .08)
        extra[f'--theme-semantic-{role}-text'] = _readable(hue, (*backgrounds, state_surface))
        extra[f'--theme-semantic-{role}-surface'] = state_surface
        extra[f'--theme-semantic-{role}-border'] = _readable(hue, (*backgrounds, state_surface), 3)
    # Chart colors identify categories, never correctness. The textual legend
    # remains authoritative; fixed ordering is independent of empty categories.
    for index, hue in enumerate(('#387cca', '#9956c8', '#aa8000', '#008778', '#d26937',
                                 '#ba4b91', '#608c2e', '#388aab', '#b85862', '#737c8b')):
        extra[f'--theme-chart-{index}'] = _readable(hue, backgrounds, 3)
    return colors, extra


SOURCE_MANIFEST = json.loads((Path(__file__).with_name('theme_sources') / 'omarchy-v4.0.4.json').read_text())
_NAMES = {'dark': 'Dark', 'light': 'Light', 'purple-gold': 'Purple & Gold',
          'maroon-gold': 'Maroon & Gold', 'ethereal': 'Ethereal'}
THEME_REGISTRY = {
    key: {'id': key, 'name': _NAMES[key], 'group': 'DLMS', 'scheme': colors['scheme'],
          'colors': colors, 'extra_tokens': ETHEREAL_PRESENTATION if key == 'ethereal' else {},
          'upstream_id': 'ethereal' if key == 'ethereal' else None}
    for key, colors in LEGACY_PALETTES.items()
}
for _source in SOURCE_MANIFEST['themes']:
    if _source['palette']['mode'] not in ('light', 'dark'):
        raise ValueError('Invalid bundled theme classification')
    for _field in ('background', 'foreground', 'muted', 'accent'):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', _source['palette'][_field]):
            raise ValueError('Invalid bundled source color')
    if _source['upstream_id'] == 'ethereal':
        continue
    _colors, _extra = _web_palette(_source['palette'])
    _id = _source['dlms_id']
    if _id in THEME_REGISTRY or _id != 'omarchy-' + _source['upstream_id']:
        raise ValueError('Duplicate or unstable bundled theme identifier')
    THEME_REGISTRY[_id] = {
        'id': _id, 'name': _source['upstream_id'].replace('-', ' ').title(),
        'group': 'Omarchy · ' + _colors['scheme'].title(), 'scheme': _colors['scheme'],
        'colors': _colors, 'extra_tokens': _extra, 'upstream_id': _source['upstream_id'],
    }
THEME_IDS = frozenset(THEME_REGISTRY)


def normalize_theme(value, default=DEFAULT_THEME):
    candidate = value.strip().lower() if isinstance(value, str) else ''
    return candidate if candidate in THEME_IDS else default


def get_theme(value):
    return THEME_REGISTRY[normalize_theme(value)]


def theme_groups():
    """Public selector metadata only; never persist this derived list."""
    return [{'label': group, 'options': [{'id': item['id'], 'name': item['name']}
                                        for item in THEME_REGISTRY.values() if item['group'] == group]}
            for group in ('DLMS', 'Omarchy · Light', 'Omarchy · Dark')]
