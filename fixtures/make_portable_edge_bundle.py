"""Create a neutral format-2 portable bundle with intentionally unusual choices.

The captured editor still requires unique labels.  This fixture exercises the
existing portable receiver without asking the editor to author such content.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import zipfile


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    project = Path(__file__).resolve().parents[1]
    if not output.is_relative_to(project / ".gate1"):
        raise ValueError("Fixture output must stay in the Desktop disposable area")
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format": "dlms-portable-quiz-bundle",
        "schema_version": 2,
        "created_at": "2026-10-11T12:00:00-05:00",
        "created_by": {"application": "DLMS", "version": "3.3.0"},
        "quizzes": [{
            "bundle_id": "quiz-001",
            "title": "Portable Unusual Choices",
            "folder": "Synthetic Portable",
            "exam_minutes": 30,
            "logo": None,
            "assets": [],
            "questions": [{
                "number": 1,
                "type": "choice",
                "question": "Which repeated label belongs to the intended answer?",
                "explanation": "Preserve labels and identities without normalization.",
                "concepts": [],
                "source": {},
                "media": {},
                "choices": [
                    {"key": "choice-001", "label": "D", "text": "Same visible text", "is_correct": False},
                    {"key": "choice-002", "label": "D", "text": "Same visible text", "is_correct": True},
                    {"key": "choice-003", "label": "A", "text": "Another option", "is_correct": False},
                ],
            }, {
                "number": 2,
                "type": "choice",
                "question": "Which nonconsecutive labels are both correct?",
                "explanation": "Two correct choices remain distinct.",
                "concepts": [],
                "source": {},
                "media": {},
                "choices": [
                    {"key": "choice-001", "label": "Z", "text": "First correct", "is_correct": True},
                    {"key": "choice-002", "label": "C", "text": "Incorrect", "is_correct": False},
                    {"key": "choice-003", "label": "M", "text": "Second correct", "is_correct": True},
                ],
            }],
        }],
    }
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("dlms-quiz-bundle.json", json.dumps(manifest, ensure_ascii=False))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
