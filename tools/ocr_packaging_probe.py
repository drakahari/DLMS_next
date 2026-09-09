"""Frozen-only Tesseract packaging gate used by DLMS release validation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dlms.services.ocr import (
    OCRCancelledError,
    OCRTimeoutError,
    recognize_image_bytes,
    resolve_tesseract_runtime,
)


def main() -> int:
    if not getattr(sys, "frozen", False):
        raise SystemExit("The OCR packaging probe must run as a frozen executable.")
    resource_root = Path(sys._MEIPASS)
    fixture = resource_root / "ocr-probe" / "dlms-question.png"
    runtime = resolve_tesseract_runtime()
    fixture_bytes = fixture.read_bytes()
    try:
        recognize_image_bytes(
            fixture_bytes,
            source_id="packaging-timeout-probe",
            source_width=1200,
            source_height=700,
            runtime=runtime,
            timeout_seconds=0.000001,
        )
    except OCRTimeoutError:
        timeout_termination = True
    else:
        raise SystemExit("Frozen OCR timeout probe did not terminate the engine.")
    try:
        recognize_image_bytes(
            fixture_bytes,
            source_id="packaging-cancel-probe",
            source_width=1200,
            source_height=700,
            runtime=runtime,
            cancel_requested=lambda: True,
        )
    except OCRCancelledError:
        cancellation_termination = True
    else:
        raise SystemExit("Frozen OCR cancellation probe did not terminate the engine.")
    observations = recognize_image_bytes(
        fixture_bytes,
        source_id="packaging-probe",
        source_width=1200,
        source_height=700,
        runtime=runtime,
        timeout_seconds=20.0,
    )
    recognized = " ".join(item.text for item in observations)
    expected = ("DLMS", "protocol", "HTTPS")
    if not all(token.casefold() in recognized.casefold() for token in expected):
        raise SystemExit(f"Unexpected OCR output: {recognized!r}")
    print(
        json.dumps(
            {
                "bundled": runtime.bundled,
                "engine": "tesseract",
                "version": runtime.version,
                "observation_count": len(observations),
                "recognized": recognized,
                "timeout_termination": timeout_termination,
                "cancellation_termination": cancellation_termination,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
