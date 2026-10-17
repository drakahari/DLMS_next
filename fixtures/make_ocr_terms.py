"""Create a neutral local OCR terminology image in the disposable area."""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


PROJECT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT / ".gate1/fixtures/closure-ocr-terms.png"
FONT = Path("/usr/share/fonts/google-noto-vf/NotoSans[wght].ttf")


def main() -> None:
    if not FONT.is_file():
        raise FileNotFoundError(f"Existing Fedora font unavailable: {FONT}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1600, 600), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(FONT), 66)
    for y, text in ((85, "Alpha: First neutral term"), (270, "Beta: Second neutral term")):
        draw.text((90, y), text, font=font, fill="black")
    image.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    main()
