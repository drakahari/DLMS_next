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
