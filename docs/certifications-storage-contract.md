# My Certifications: storage and compatibility

This is an earned-credential log, independent of Exam Plans, question evidence,
quiz scoring and review schedules. Nothing in this module awards learning credit,
quiz completion, issuer approval or verified renewal.

## Schema 7 foundation, additive schema 8 and schema 9 guard

The existing SQLite migration runner adds seven tables in its transaction:
`certification_state`, `certifications`, `certification_cycles`,
`certification_training`, `certification_allocations`,
`certification_attachments` and `certification_actions`. Fresh profiles use the
same definitions in `init.sql`. Existing rows in other tables are untouched.
Schema readiness includes the singleton generation/revision guard. Interrupted
migration rolls back; the version advances only after validation. Rerunning a
successful migration is a read/check operation. Older builds reject databases above their supported schema version. Schema 7 builds refuse schema 8; schema 8 builds refuse schema 9.

Record IDs are random, stable identifiers. Dates are validated calendar dates
(`YYYY-MM-DD`), with no timezone conversion. Periods remain separate. Schema 8 adds a unique positive `period_order` per credential, initialized from schema 7’s existing `(start, id)` order without changing dates or files. Known starts and expirations must remain ordered, but starts may be unknown and early-renewal coverage may overlap. Recording date is distinct from coverage. Current editing updates the same period; new renewal requires a later expiration and carries no credit or certificate forward.
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

The same Settings provider choices and synchronous copy/launch behavior as the
Study question/answer AI-review action are used through `manual-ai.js`. Newly
generated quiz pages load this helper; older shared-script quiz pages retain the
existing fallback. Copy & open AI attempts copying before opening the configured
provider with no prompt in its URL. Clipboard failure and blocked-tab uncertainty
are reported separately; independent Copy and a real manual provider link remain. The certification template is independently editable/resettable.
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


## Portfolio tracking (schema 8)

Optional JSON metadata extends existing records without inventing historical
verification or assistance. Existing schema-7 JSON remains valid and unchanged.
Unknown requirements retain their legacy numeric storage default only for format
compatibility; the UI and AI label them unknown unless explicitly recorded.
A known zero is distinguishable from an unknown requirement. Free-text issuers
and custom rules use every workflow; no preset is required.

Training URLs/topics are optional public context; private notes stay excluded.
Proposed amounts, review flags, sources and reporting-date exceptions are separate
from submitted/accepted amounts. Library hours sum each activity once. A unique
allocation per activity/period prevents duplicate cycle credit. Period and annual
views partition saved allocations; caps affect displayed progress, not saved
facts. Unknown reporting dates/rules never imply compliance. Years are calendar
or user-anchored anniversary; irregular years remain explicitly manual. February
29 anchors clamp to February 28 in non-leap years, disclosed before selection.

Directional relationships live with the source credential as bounded metadata.
Deleted targets remain unavailable references, not silently substituted records.
Confirmed target renewals snapshot the source name, issuer, trigger and rule in
the new target period. Removal of a relationship never erases that history.
Nothing automatically updates other credentials or adds training credit.

`show_certifications` defaults true. It masks the trophy card and certification
sidebar group, preserving the independent card mapping and display count. Scoped
layout restores do not change this master toggle. Settings remains reachable.
The portfolio prompt uses its own setting and reset; existing prompts remain
independent. These settings use the existing portable JSON backup.

## Rule sources checked 2026-10-07

Presets are stored in `dlms/services/certification_presets.py` and copied into an
editable form only. No network or rule refresh occurs at runtime. Rules must be
checked for the user's actual credential/version, route and reporting dates.

- [ISACA 2026 CPE policy](https://www.isaca.org/-/media/files/isacadp/project/isaca/certification/general/cpe_policy.pdf): CISM 20 annually, 120 over three years; 90 aligned with the credential exam content, at most 30 other development. Calendar reporting years and special initial-year reporting apply. Activity-specific limits, fees, ethics and audit remain conditions to verify.
- [ISC2 member policy v7](https://www.isc2.org/policies-procedures/member-policies): CISSP 120 over three years, including at least 90 Group A; up to 30 Group B. Forty annually is suggested pacing, not a mandatory annual minimum. Personal reporting boundaries are not inferred.
- [PeopleCert FAQ](https://www.peoplecert.org/help-and-support/FAQ): version and renewal route matter. The preset is intentionally incomplete; Plus CPD and examination routes must not be conflated. ITIL v3 must not inherit ITIL 4 renewal rules.
- [LPI renewal](https://www.lpi.org/our-certifications/renewal/): current exams, higher-level certification and optional membership are different renewal routes. No personal expiration or related renewal is applied automatically.
- [LPI PDU policy](https://www.lpi.org/member/pdu-procedures-and-policies/): membership route has 60 PDUs per three-year cycle; Education minimum 30/cap 50, Community cap 20, Experience cap 30. Activity-specific conversion and caps remain manual. No carry-forward is automated.
- [LPI membership program](https://www.lpi.org/membership-program-2/): a PDU cycle begins with membership activation, distinct from the one/three-year paid membership term and certification status. Its FAQ explicitly says there is no 20-PDU annual minimum; it separately requires 20 recent PDUs for inactive holders applying for membership. The renewal page still says 20 annually. The preset leaves this conflicting annual obligation unknown pending confirmation. Sixty PDUs is a membership-cycle requirement, not a three-year certification validity period; no certification expiration is calculated from it.

The CompTIA multiple-renewal source could not be reliably retrieved in this
review. No built-in CompTIA mapping is enabled. Manual directional relationships
with explicit evidence/confirmation are available for all issuers.

## Exact time and simple planning (schema 9)

Schema 9 adds no tables or columns and converts no saved JSON. Its repeat-safe
migration validates the schema-8 state before advancing the version in the
existing transaction. The version guard is necessary: older writers would drop
the new exact-duration field and reject unknown estimates. Keep a schema-8 backup
before upgrading; use the rollback procedure above with the matching old source.

New time entries store optional `duration_minutes`, a nonnegative number with up
to two decimal places. `hours` remains a two-decimal compatibility projection.
9 h 22 min stores exactly 562 minutes, even though that projection is 9.37 hours.
All displayed learning-time totals, form values, bounds and AI context use exact
minutes. Legacy records without this field retain original `hours`; 9.37 hours
means 562.2 minutes. Opening or saving unchanged time does not round, reinterpret
or add a new field to that legacy record. Backup carries the exact JSON.

A contribution's `proposed` value may be null for an unknown estimate. Existing
zero values stay zero. Approximate progress uses the explicit estimate (at least
accepted credit), or submitted/accepted credit when no estimate exists. It never
adds workflow stages. Existing reporting boundaries and known category caps
apply; unclassified estimates remain visible in approximate progress. Detailed
accepted-credit calculations and saved amounts are unchanged. Neither calculation
asserts issuer approval. Only hours-based units get an editable duration-derived
starting estimate; credits/CPE/CPD/PDU need user input.

`use_training` saves explicitly selected course/period contributions in one locked
transaction with one replay identity. Child allocation writes and receipts commit
or roll back together. An error saves none of the selected changes. Exact retries
return the same result; changed inputs, stale revisions and pre-restore identities
fail. Existing contributions keep submitted/accepted values and reporting details.

`certification_display_count` retains existing 3/6/all values and now accepts any
positive whole number (bounded input length). `certification_sort` defaults to the
existing earned-date order; name/expiration are explicit saved alternatives. These
settings use existing locked atomic persistence and portable backup, alongside
`show_certifications`. Scoped dashboard/sidebar resets preserve these choices.

## Focused editors (schema 9 unchanged)

Identity, planning goal and detailed-requirements forms use the same existing
records and action receipts. Identity edits merge only identity, expiration,
badge/certificate and private-note fields into the current record/period. Goal
edits change only the target, unit, planning deadline and optional annual amount;
they do not alter expiration, attachments, history or recorded contributions.
The short goal editor never changes a recorded mandatory annual minimum; correct
that rule in Manage detailed requirements. For an optional
pacing goal, explicitly clearing it returns that annual goal to unknown.

The merge occurs inside the existing locked write, after generation, receipt and
revision checks. Receipt hashes cover the original submitted patch, so a lost
acknowledgement is replayable even after a later edit. Changed inputs under the
same request ID and stale competing edits remain rejected. New task routes are
GET editors; they never create a period or learning evidence. Advanced fields
omitted from these short forms remain intact. Full legacy save callers remain
supported. No schema migration or new backup format is introduced.

Targets are user-recorded planning amounts, not verified issuer requirements.
Existing policy sources/check status remain separately recorded; editing a goal
does not verify the changed amount against those sources. Unit changes with
existing contributions remain blocked. Estimates, submitted credit, accepted
credit, course duration and associated duration keep their existing meanings.
Unchecked rows in Use toward renewal are ignored, not removed. Selected rows
save atomically; updating an existing relationship changes its estimate only.

Category removal and suggested requirements require explicit UI actions; a
suggestion first shows source/version information for review, then fills the
unsaved form. Save remains necessary. Neither action touches recorded credit.
The existing pre-upgrade-backup rollback requirements above still apply: changing
binaries alone cannot reverse schema 9 or restore earlier data.
