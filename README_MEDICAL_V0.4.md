# DLMS Medical v0.4.0 Core Update

Replace only:

- `app.py`
- `static/script.js`
- `static/style.css`

This update:

1. Preserves Medical Pack per-term category, explanation, and verification metadata
   when generating and rebuilding matching quizzes.
2. Adds safe database migrations for those fields in `matching_pairs`.
3. Shows richer Study Mode feedback after each matching selection:
   - correct / incorrect
   - correct match when missed
   - content category
   - source-checked badge
   - optional explanation
   - reference basis
4. Displays the Medical Pack's declared image-framework readiness.
5. Does not yet render anatomy hotspot questions; v0.4 establishes the validated
   content format first.

Existing quizzes remain backward-compatible because the new DB columns are nullable.
