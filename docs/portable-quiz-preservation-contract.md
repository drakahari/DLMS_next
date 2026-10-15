# Portable quiz preservation and choice order

## Schema 11

`choices.choice_order` is a zero-based per-question display position. The new
unique index covers `(question_id, choice_order)`. Migration runs in the existing
bootstrap transaction: existing rows receive positions in their previous
`label,id` display order. Equal labels use ascending existing choice ID; choices
are separate rows, never merged. IDs, labels, text and correctness are unchanged.
In particular, quiz 92/question 45 remains A/B/C/D/R and quiz 163/question 31
remains A/B/C/D. Row-ID order alone would have changed both.

Application writers explicitly assign positions; array-based publication uses
input array order. Editor additions append to the maximum position, deletions
leave gaps, and label edits do not reorder rows. Readers use
`choice_order,label,id`. Defensive NULL rows from legacy/manual SQL sort first
using the prior label/ID rule; the supported application writers never create
NULL positions. Invalid explicit positions or a differently defined uniqueness
index are rejected on startup/restore. Assessment and marked-question revisions
hash the ordered content, not the added column itself; migration retains them.
The regression oracle in `tests/schema10_revision_reference.py` freezes the
pre-migration revision functions from `856131ad333dc8d9fb7b32b010cf96c70dea93e4`,
with their source hash. It runs without Git history, including shallow CI
checkouts. It must not be replaced by the current reader when testing migration.

Affected readers include rendering, learning/recommendations, Study revisions,
Exam validation, composition, duplicates, editor and Anki. Content lineage and
historical results are unchanged. Backup includes the SQLite column and index.
Compatible old backups migrate transactionally during staged restore. Older
applications refuse schema 11 before writing; never lower the schema marker.

## Format 2

The ZIP trust boundary and resource limits are unchanged. Incoming archives are
untrusted: paths, exact structures/types, declarations, hashes, media decoding,
references and bounded resource checks are enforced before publication. Each
choice array preserves separate entries in order, with an archive-local unique
`choice-NNN` key, original label/text and an exact boolean correct flag. Import
uses new local DB row IDs and the array position. Keys do not imply answer
correctness or source learning identity. Format 1 remains supported for previously
valid bundles; older receivers reject version 2 before publishing anything.

Preserved portable content: title/folder, Exam duration, ordered supported
questions, text/explanations, ordered separate choices/flags, supported matching
pairs/options, concepts, human-readable source information, source numbering,
supported media metadata and media bytes. Installation-local IDs, generated
composition references, attempts, Study sessions, schedules, settings and learner
identity are not portable. Asset paths relocate safely. Absent optional text
stored as NULL is represented as empty text; no missing answer is inferred.
This is content transfer, not a byte-identical database backup.

Readiness is recomputed locally. Duplicate labels, missing required text and
missing correct answers are safely preservable, but block whole-quiz graded
launch/claim/save. Valid unique label gaps are ready. Generated practice rejects
an unsafe selected question instead of silently omitting it. Hotspot and malformed
matching preservation are outside this format; unsupported records fail explicitly.
The reserved Image Study stem suffix identifies its stored
choice surrogate; export blocks it rather than losing runtime target geometry.
Some creators store no image metadata in that surrogate. Imports reject the
same reserved representation, including older lossy bundles; missing geometry
cannot be reconstructed from a choice surrogate.

Preflight groups all detected warnings/blockers by selected quiz and question;
warning confirmation is bound to freshly checked selection/report. Export blockers
stop the entire download. Checks are bounded to 100,000 inspected questions per
selection; exceeding that budget explicitly blocks export and asks for a smaller
batch. Per-quiz, manifest, media and archive budgets still apply. Complete download
publication uses the existing two-job admission bound and isolated temporary
files. A collection contains only ordinary bounded bundles plus an inventory;
extract first and import each bundle. It is not a nested-archive import format.

## Old pages and recovery

Current shared JavaScript maps selections using actual labels. New submissions
carry `answerEncoding=choice-labels-v1`; the server requires it for nonpositional
labels. Old ambiguous queues are retained and rejected before browser ownership
changes. Their meaning is not guessed. Older self-contained pages for such quizzes
must be explicitly regenerated in the editor. No automatic personal regeneration
or historical answer/score rewrite is performed. Contiguous older clients retain
the existing supported contract. Readiness checks fail visibly and never award
credit merely for opening, importing or checking a quiz.

## Rollback

Before upgrading, keep a verified pre-upgrade full-data backup outside the profile.
Switching binaries alone cannot undo schema 11. Preserve the upgraded profile and
latest backup separately; stop only the intended application normally. Run the
compatible older application with a separate supported data root and restore the
verified pre-upgrade backup through its staged workflow. Check records and files
before choosing that profile. All changes after the pre-upgrade backup are absent
from that restored profile. Do not transplant individual tables or rename schema
versions. Production migration and a fresh packaged build require separate approval.
