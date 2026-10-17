"""Create a neutral Study Pack with supported image and quiz datasets.

Output is disposable and deliberately outside Git. No owner content is read.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path
import zipfile

from PIL import Image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--polygon", action="store_true", help="Use a supported polygon target for shape acceptance")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    output = Path(args.output).resolve()
    if not output.is_relative_to(project / ".gate1"):
        raise ValueError("Output must be in this project's disposable .gate1 area")
    output.parent.mkdir(parents=True, exist_ok=True)
    folder = "DLMS_Study_closure_datasets"
    pack_id = "closure_datasets"
    manifest = {
        "schema_version": 1, "id": pack_id, "name": "Closure Dataset Pack",
        "version": "1.0.0", "content_domain": "medical", "datasets": [],
        "image_datasets": [{"id": "image_set", "title": "Image Set", "type": "hotspot", "path": "data/image_set.json"}],
        "quiz_datasets": [{"id": "quiz_set", "title": "Quiz Set", "type": "quiz", "path": "data/quiz_set.json"}],
    }
    source = {"organization": "Synthetic Test", "license": "CC0"}
    target = ({"type": "polygon", "points": [[.35, .35], [.65, .35], [.65, .65], [.35, .65]]}
              if args.polygon else {"type": "circle", "x": .5, "y": .5, "radius": .1})
    image_set = {
        "schema_version": 1, "id": "image_set", "title": "Image Set", "source": source,
        "images": [{"id": "diagram", "file": "images/diagram.png", "license": "CC0",
                    "alt_text": "Neutral colored test diagram", "hotspots": [
                        {"id": "center", "label": "Center", "shape": target},
                    ]}],
    }
    quiz_set = {
        "schema_version": 1, "id": "quiz_set", "title": "Quiz Set", "source": source,
        "questions": [
            {"type": "choice", "question": "Select the neutral marker.", "image_id": "diagram",
             "choices": [{"text": "Marker", "is_correct": True}, {"text": "Other", "is_correct": False}]},
            {"type": "matching", "question": "Match the neutral terms.",
             "pairs": [{"left": "Alpha", "right": "First"}, {"left": "Beta", "right": "Second"}]},
        ],
        "images": [{"id": "diagram", "file": "images/diagram.png", "license": "CC0"}],
    }
    raster = Image.new("RGB", (32, 24), (70, 130, 190))
    pixels = BytesIO()
    raster.save(pixels, format="PNG")
    entries = {
        "manifest.json": json.dumps(manifest, sort_keys=True).encode(),
        "data/image_set.json": json.dumps(image_set, sort_keys=True).encode(),
        "data/quiz_set.json": json.dumps(quiz_set, sort_keys=True).encode(),
        "images/diagram.png": pixels.getvalue(),
        "PACK_VALIDATION.json": json.dumps({"schema_version": 1, "pack_id": pack_id,
                                               "overall_status": "PASS", "checks": []}).encode(),
    }
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative, data in entries.items():
            archive.writestr(f"{folder}/{relative}", data)
    print(output)


if __name__ == "__main__":
    main()
