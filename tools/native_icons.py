"""Build platform icon formats from DLMS's existing macOS/browser artwork."""
from pathlib import Path

from PIL import Image


def windows_icon(source: Path, destination: Path) -> Path:
    """The historical favicon.ico is PNG data; produce a real multi-size ICO."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image.convert("RGBA").save(
            destination, format="ICO",
            sizes=[(size, size) for size in (16, 24, 32, 48, 64, 128, 256)],
        )
    return destination


def desktop_icon(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image.convert("RGBA").resize((256, 256), Image.Resampling.LANCZOS).save(
            destination, format="PNG",
        )
    return destination
