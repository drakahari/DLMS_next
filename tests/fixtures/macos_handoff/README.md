# macOS handoff synthetic inputs

No owner content, profile, backup, credential or executable is included.

- `neutral-quiz.txt`: exact copy of tracked `fixtures/gate1-neutral-quiz.txt`; four neutral, self-authored single-choice questions. Answers in order: B,C,A,B.
- `ocr-question.png`: exact copy of tracked `tests/fixtures/ocr/dlms-question.png`; project synthetic OCR corpus. See its tracked corpus README for provenance.
- `scanned.pdf`: exact copy of tracked `tests/fixtures/ocr/pdf/fully-scanned.pdf`, generated from synthetic text by tracked `tests/fixtures/ocr/generate_pdf_fixtures.py`. One HTTPS-port question; C/443 is correct.
- `EXPECTED.json`: content expectations. OCR is reviewed, not assumed to be perfect.

`SHA256SUMS` binds all five supplied files. Copy this folder's contents to a newly created, visible Documents review folder before native owner selection. Do not point a walkthrough at hidden project fixtures. Never rename a TXT export to ZIP or feed a glossary image to an unrelated importer. Create backups through the running synthetic application; no backup archive is committed.
