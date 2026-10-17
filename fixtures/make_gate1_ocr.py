"""Create neutral synthetic image/PDF sources inside an explicit disposable directory."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw, ImageFont


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    font_path = subprocess.check_output(["fc-match", "-f", "%{file}", "sans"], text=True).strip()
    font = ImageFont.truetype(font_path, 31)
    image = Image.new("RGB", (1300, 600), "white")
    draw = ImageDraw.Draw(image)
    lines = [
        "Gate 1 synthetic OCR fixture",
        "1. Which shape has three sides?",
        "A. Circle",
        "B. Triangle",
        "C. Square",
        "Answer: B",
    ]
    for index, line in enumerate(lines):
        draw.text((45, 45 + index * 78), line, fill="black", font=font)
    image.save(args.output / "gate1-ocr.png")
    image.save(args.output / "gate1-scanned.pdf", "PDF", resolution=150.0)


if __name__ == "__main__":
    main()
