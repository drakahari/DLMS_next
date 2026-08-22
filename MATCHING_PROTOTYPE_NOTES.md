# DLMS Matching Prototype Notes

Baseline: DLMS 2.5.0

Implemented in this prototype:
- New generic question type: `matching`
- Manual builder question-type selector
- Matching pair editor with add/delete pair controls
- Backward-compatible SQLite migration (`questions.question_type`)
- New `matching_pairs` table
- JSON persistence/rebuild support for matching questions
- Playable dropdown-based matching UI
- Per-question shuffled right-side answers
- Study-mode correct/incorrect feedback
- Exam-mode whole-question scoring
- Missed-question snapshot support for matching
- Basic edit support for existing matching questions
- Existing questions with no explicit type continue to behave as `choice`

Intentionally deferred:
- Medical terminology content packs and source-attribution UI
- Drag-and-drop matching presentation
- Matching-specific Anki export
- Matching-specific AI review prompt
- Pair deletion from the Edit Quiz page (pairs can be edited and added; deletion is supported in the creation builder)
- Full runtime test in the build container (Flask dependency could not be installed because this environment has no package-network access)

Validation completed here:
- Python syntax compile: PASS
- JavaScript syntax check: PASS
- SQLite schema creation and matching-pair insert: PASS

Recommended desktop test:
1. Back up the existing DLMS application data directory/results.db.
2. Run this prototype against a copy/test data directory first.
3. Create one matching-only quiz.
4. Create one mixed quiz containing a normal choice question and a matching question.
5. Test Study and Exam modes.
6. Edit a matching pair, save, and retest.
7. Verify an existing 2.5.0 quiz still plays and scores normally.
