"""Make a neutral portable quiz with a supported image, logo and matching pair."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile

from PIL import Image


def png(color: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (8, 8), color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if not output.is_relative_to(project / ".gate1"):
        raise ValueError("Fixture output must stay in the Desktop disposable area")
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    image = png((20, 70, 120))
    logo = png((80, 30, 100))
    media_path = "assets/quiz-001/asset-001.png"
    logo_path = "assets/quiz-001/asset-002.png"
    manifest = {
        "format": "dlms-portable-quiz-bundle", "schema_version": 2,
        "created_at": "2026-10-11T12:00:00-05:00",
        "created_by": {"application": "DLMS", "version": "3.3.0"},
        "quizzes": [{
            "bundle_id": "quiz-001", "title": "Synthetic Portable Media",
            "folder": "Synthetic Portable", "exam_minutes": 45,
            "logo": "dlms-bundle-asset:" + logo_path,
            "assets": [
                {"path": path, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw), "role": role}
                for path, raw, role in ((media_path, image, "question-media"), (logo_path, logo, "quiz-logo"))
            ],
            "questions": [{
                "number": 1, "type": "choice", "question": "Which neutral item is shown?",
                "explanation": "Synthetic image exercise.", "concepts": ["Portable media"],
                "source": {"organization": "Synthetic Test", "license": "CC0"},
                "media": {"image_url": "dlms-bundle-asset:" + media_path,
                          "image_alt": "Neutral blue tile", "image_edits": [],
                          "image_source": {"license": "CC0"}},
                "choices": [
                    {"key": "choice-001", "label": "C", "text": "Blue tile", "is_correct": True},
                    {"key": "choice-002", "label": "A", "text": "Red tile", "is_correct": False},
                ],
            }, {
                "number": 2, "type": "matching", "question": "Match neutral words.",
                "explanation": "Two synthetic pairs.", "concepts": ["Portable matching"],
                "source": {"organization": "Synthetic Test", "license": "CC0"},
                "media": {}, "round_size": 2, "direction": "definition_to_term",
                "pairs": [
                    {"left": "Alpha", "right": "First", "category": "Letters", "explanation": "", "verification": {}},
                    {"left": "Beta", "right": "Second", "category": "Letters", "explanation": "", "verification": {}},
                ],
            }],
        }],
    }
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("dlms-quiz-bundle.json", json.dumps(manifest, ensure_ascii=False))
        archive.writestr(media_path, image)
        archive.writestr(logo_path, logo)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
