"""Render original geometric DLMS badge artwork and its launcher resources.

This is a build-time conversion. It does not replace the captured web favicon.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "desktop_assets/dlms_omarchy.png"
SOURCE_SHA256 = "1ec18ded1259863148e89e3021a2defe185aaaeb1a68dc7d9747690467aa8315"
APP_ID = "io.github.drakahari.DLMSDesktop"


def original_badge():
    """Original block lettering, no imported image, font, logo or traced paths.

    The simple five-by-seven letter grids below are authored for this project.
    SVG and raster forms use the same geometry. See ICON_PROVENANCE.md.
    """
    letters = (
        ('11110', '10001', '10001', '10001', '10001', '10001', '11110'),
        ('10000', '10000', '10000', '10000', '10000', '10000', '11111'),
        ('10001', '11011', '10101', '10101', '10001', '10001', '10001'),
        ('01111', '10000', '10000', '01110', '00001', '00001', '11110'),
    )
    scale = 8
    image = Image.new('RGBA', (64 * scale, 64 * scale))
    draw = ImageDraw.Draw(image)
    def box(coords):
        return tuple(int(n * scale) for n in coords)
    draw.rounded_rectangle(box((2, 2, 62, 62)), radius=14 * scale, fill='#12324a')
    draw.rounded_rectangle(box((3, 3, 61, 61)), radius=13 * scale,
                           outline='#37d3e8', width=2 * scale)
    rectangles = []
    for index, letter in enumerate(letters):
        for row, cells in enumerate(letter):
            for column, cell in enumerate(cells):
                if cell == '1':
                    x, y = 9 + index * 12 + column * 2, 25 + row * 2
                    rectangles.append(f'  <rect x="{x}" y="{y}" width="2" height="2"/>')
                    # ImageDraw includes both endpoints; keep exact cell widths.
                    draw.rectangle((x * scale, y * scale, (x + 2) * scale - 1,
                                    (y + 2) * scale - 1), fill='#ffffff')
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">\n'
           '  <title>DLMS original block-letter badge</title>\n'
           '  <rect x="2" y="2" width="60" height="60" rx="14" fill="#12324a"/>\n'
           '  <rect x="4" y="4" width="56" height="56" rx="12" fill="none" stroke="#37d3e8" stroke-width="2"/>\n'
           '  <g fill="#ffffff">\n' + '\n'.join(rectangles) + '\n  </g>\n</svg>\n')
    return image, svg


def main() -> None:
    image, svg = original_badge()
    (ROOT / 'desktop_assets/dlms-badge.svg').write_text(svg, encoding='utf-8')
    image.resize((64, 64), Image.Resampling.LANCZOS).save(SOURCE, 'PNG')
    artwork = image
    for size in (16, 24, 32, 48, 64):
        target = ROOT / f"desktop_assets/icons/hicolor/{size}x{size}/apps/{APP_ID}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        artwork.resize((size, size), Image.Resampling.LANCZOS).save(target, "PNG")
    ico = ROOT / "desktop_assets/icons/windows/DLMSDesktop.ico"
    ico.parent.mkdir(parents=True, exist_ok=True)
    artwork.save(ico, format="ICO", sizes=[(size, size) for size in (16, 24, 32, 48, 64)])
    icns = ROOT / "desktop_assets/icons/macos/DLMSDesktop.icns"
    icns.parent.mkdir(parents=True, exist_ok=True)
    artwork.save(icns, format="ICNS")


if __name__ == "__main__":
    main()
