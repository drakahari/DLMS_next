# Synthetic candidate fixtures

These are selectable test inputs, not application executables, personal quizzes, profiles, history, APKG decks or backups. Copy them into a newly created ordinary Documents or Downloads folder before native selection.

- `neutral-quiz.txt`: unchanged tracked `tests/fixtures/macos_handoff/neutral-quiz.txt`, originally `fixtures/gate1-neutral-quiz.txt`; four authored neutral choice questions, answers B, C, A, B. An all-correct review scores 4/4. For an attempt-specific missed-export check, deliberately answer the first two wrong, then export only the second missed question.
- `ocr-question.png`: unchanged tracked `tests/fixtures/macos_handoff/ocr-question.png`, from the project synthetic OCR corpus. Use the quiz-screenshot importer and review extracted choices before publishing.
- `scanned.pdf`: unchanged tracked `tests/fixtures/macos_handoff/scanned.pdf`, generated synthetic OCR PDF. The HTTPS-port question has C / 443 correct. OCR output is reviewed, not assumed exact.
- `synthetic-hotspot-pack.zip`: unchanged `tests/fixtures/hotspot-preservation/synthetic-pack.zip` under a clearer display name. Import through the Study Pack workflow. It contains original synthetic fictional questions, a drawn blue-circle/orange-square diagram, and circle/polygon targets. The pack declares CC0-1.0 for its text and diagram; repository code/tests retain MIT licensing. This is a portable fixture, never a backup or profile. Do not extract or edit it merely to make an import pass.
- `EXPECTED.json`: unchanged expectations for neutral quiz/OCR. The original OCR filenames are retained. Hotspot expectations are given above and in the tracked source fixture README.

These copies preserve their source bytes. `SHA256SUMS` binds every file here except itself. No real-file selection, protected-file bypass or personal-data adoption is authorized by a walkthrough. Generate backup ZIPs and APKG outputs only from the fresh synthetic application profile; do not commit them. Source-level fixtures do not establish native platform acceptance.
