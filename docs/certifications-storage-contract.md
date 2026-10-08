# My Certifications: storage and compatibility

This is an earned-credential log, independent of Exam Plans, question evidence,
quiz scoring and review schedules. Nothing in this module awards learning credit,
quiz completion, issuer approval or verified renewal.

## Schema 7

The existing SQLite migration runner adds seven tables in its transaction:
`certification_state`, `certifications`, `certification_cycles`,
`certification_training`, `certification_allocations`,
`certification_attachments` and `certification_actions`. Fresh profiles use the
same definitions in `init.sql`. Existing rows in other tables are untouched.
Schema readiness includes the singleton generation/revision guard. Interrupted
migration rolls back; the version advances only after validation. Rerunning a
successful migration is a read/check operation. Older builds reject version 7.

Record IDs are random, stable identifiers. Dates are validated calendar dates
(`YYYY-MM-DD`), with no timezone conversion. Cycles remain separate; new cycles
start after recorded earlier cycles and contain no automatically carried credits.
Changing a cycle’s credit unit is blocked once it has allocations, to avoid
silently reinterpreting existing credit amounts. Each activity has at most one
allocation per cycle. The user may explicitly associate it with other cycles or
credentials. Activity edits do not change existing allocation amounts. Submitted
and accepted credit are in the cycle’s recorded unit; accepted cannot exceed
submitted. Allocated hours cannot exceed the activity’s hours when saved.

## Atomic evidence and retry behavior

Evidence uses managed attachment IDs and SQLite BLOBs, avoiding filesystem paths,
original filenames, collisions and record/file split commits. Each original and
stored upload is limited to 10 MiB; total managed evidence to 256 MiB. Raster inputs
are single-frame PNG/JPEG/WebP, at most 16 million pixels. They are stored as
lossless PNG with orientation applied and metadata removed. Keep original files
separately if original metadata matters. PDFs must be valid, unencrypted and have
1–1,000 pages. Scripts, automatic/executable actions, XFA and embedded files are
rejected. PDFs are download-only. Serving uses validated media types, generated
names, `nosniff`, no caching and a restrictive sandbox CSP.

Every form carries a random request identity plus the profile’s generation and
revision. A write locks SQLite with `BEGIN IMMEDIATE`, validates the current
revision, stores data/evidence and a replay result in one commit. Exact retries
return that result. Reusing an identity for changed inputs fails. Concurrent/stale
forms do not overwrite later work. Record fields and form revisions are read
from one database snapshot. Required form context is validated before writing,
including edits to existing cycles and allocations. Concurrent reads cannot
attach a newer revision
to stale fields. Restore rotates the generation, invalidating
all pre-restore forms, including otherwise replayable requests. Settings display
count uses the existing shared registry lock and atomic portal-config writer.
Certification requests acquire that shared lock before opening the database and
retain it through connection closure. They cannot save into a database file
replaced during restore; waiting stale forms check the restored generation.

Removal requires confirmation. Certification deletion cascades only its cycles
and allocations; shared training remains. Activity deletion removes that
activity’s allocations. Only attachments unreferenced by all remaining records
are removed. Detaching evidence never deletes its parent record. Missing evidence
is reported without inventing replacement files or deleting factual records.

## Backup, restore and resets

The existing portable backup includes `results.db`; all certification records and
evidence travel in its consistent SQLite snapshot. Existing archive path, size,
CRC and staged-recovery checks remain. Staged semantic validation additionally
checks certification fields, relationship integrity, managed references,
checksums and attachment formats before application. Missing attachments remain
explicitly unavailable. Relationship and duplicate-allocation checks do not trust
foreign-key declarations supplied by the imported database. Both startup and
restore also require the cascade and unique-allocation constraints used by later
edits and removals; valid rows alone do not make a malformed schema safe. Corrupt or active
files fail validation. Old backups
without these tables migrate in the disposable restore stage to an empty
certification collection. They do not retain records absent from that backup.
Restore retains the existing pre-restore safety backup and recovery journal.
Learning Intelligence, Study-history, quiz-library and source-content resets
preserve certifications. A settings reset resets display/prompt choices but keeps
records. Full-data reset/removal includes certifications with all profile data.

**Rollback requires a pre-upgrade backup.** Stop DLMS normally, preserve the
upgraded data root separately, and restore a verified pre-upgrade backup with the
matching older build into a separate supported data root. Check the restored data
before using it as the working profile. Swapping binaries alone cannot undo a
database migration. Never edit schema numbers or remove tables to force access.
Restoring the older backup loses all changes made since that backup, including
new Study history and settings, not only certifications. Keep the upgraded root
and a current backup separately so those later records remain recoverable with
the compatible newer application.

## AI assistance and Help capture

The same Settings provider choices and manual copy/open pattern as Law and Study
Packs are used. The certification template is independently editable/resettable.
Only explicitly selected name/issuer/earned date, cycle policy/dates/requirements
and allocated activity name/provider/date/hours/credit amounts are curated.
Notes, record IDs, attachment IDs, documents and document text are excluded.
The exact prompt remains editable before copying. No prompt is sent to DLMS’s
external provider URL, and no AI result is parsed into saved records.

The all-theme certification Firefox workflow accepts
`DLMS_CERTIFICATION_CAPTURE_DIR` for actual screenshots and focused Help crops.
Copy its `certifications-trophy.webp` and `certifications-cycle.webp` to
`static/help_assets`, verify dimensions/alt text and captions, and run Help checks.
Use disposable sample records only. The design ZIP’s issuer badges and sample
records are not shipped or seeded. `DLMS.spec` already includes complete static
and template directories; new Python modules use ordinary imported dependencies.
