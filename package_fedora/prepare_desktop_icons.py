"""Convert the retained original round blue DLMS master; never redraw it.

This build-time operation changes no installed icons or operating-system state.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parent.parent
MASTER = ROOT / "desktop_assets/dlms-icon-master.png"
MASTER_SHA256 = "be929c60a0a63373d698934930bac8af686d3a8242072e25954118f783b1af93"
# Historical runtime/installer path, generated from MASTER like every other size.
SOURCE = ROOT / "desktop_assets/dlms_omarchy.png"
SOURCE_SHA256 = "f14a4011e95c2823ab7b29da3904010338a6ad22222d9aabf367189945c06888"
APP_ID = "io.github.drakahari.DLMSDesktop"
LINUX_SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
WINDOWS_SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> None:
    if hashlib.sha256(MASTER.read_bytes()).hexdigest() != MASTER_SHA256:
        raise ValueError("Canonical DLMS master differs; do not regenerate from another image")
    with Image.open(MASTER) as image:
        if image.format != "PNG" or image.size != (1024, 1024):
            raise ValueError("Canonical DLMS master must be the retained 1024-pixel PNG")
        artwork = image.convert("RGBA")
    SOURCE.parent.mkdir(parents=True, exist_ok=True)
    artwork.resize((64, 64), Image.Resampling.LANCZOS).save(SOURCE, "PNG")
    for size in LINUX_SIZES:
        target = ROOT / f"desktop_assets/icons/hicolor/{size}x{size}/apps/{APP_ID}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        artwork.resize((size, size), Image.Resampling.LANCZOS).save(target, "PNG")
    ico = ROOT / "desktop_assets/icons/windows/DLMSDesktop.ico"
    ico.parent.mkdir(parents=True, exist_ok=True)
    artwork.save(ico, format="ICO", sizes=[(size, size) for size in WINDOWS_SIZES])
    icns = ROOT / "desktop_assets/icons/macos/DLMSDesktop.icns"
    icns.parent.mkdir(parents=True, exist_ok=True)
    artwork.save(icns, format="ICNS", append_images=[
        artwork.resize((size, size), Image.Resampling.LANCZOS)
        for size in (32, 64, 128, 256, 512, 1024)
    ])


if __name__ == "__main__":
    main()
