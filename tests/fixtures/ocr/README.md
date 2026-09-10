# OCR fixture corpus

These images are synthetic, project-created, redistribution-safe fixtures with no third-party quiz
content or interface branding. They exercise the screenshot OCR import safety
and packaging boundaries; normalized-observation unit tests provide the stable
layout-inference assertions because OCR engine output can vary slightly by
native Tesseract build.

The corpus covers explicit and inferred labels, six/eight choices, two/three
correct answers, unrelated interface chrome, ambiguous text, low resolution,
rotation, and Unicode. `screenshot-explicit-abcd.png` was generated with the
built-in image-generation tool from an original DLMS fixture prompt. The other
fixtures were rendered locally from original text with Pillow.

`generate_result_layout_fixtures.py` produces the two self-authored,
neutral reviewed-result screenshots retained in this corpus. More specific
result-layout regressions are rendered in memory by the tests so their PNGs
are never added to the repository. Those dynamic cases cover selected rows,
dedicated check/X markers, explicit A–D labels beside noisy radio controls,
early-label sequence recovery, C/© confusion, trailing control artifacts, and
Explanation boundaries. They contain no third-party quiz text or branding.
