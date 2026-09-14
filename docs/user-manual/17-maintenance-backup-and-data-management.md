# 17. Maintenance, Backup, and Data Management

DLMS stores quizzes, study sources, settings, and learning history as one local
workspace. This chapter explains how to protect that workspace and how to use
maintenance or removal tools without confusing actions that have very
different scopes.

Start with the narrowest action that solves the problem. Before a substantial
reset, upgrade, or transfer, create a backup and keep a copy outside the live
DLMS data directory.

## Choose the right data tool

| Goal | Use | Main effect |
| --- | --- | --- |
| Protect or move the complete persistent workspace | **Create & Download Backup** | Creates a portable recovery ZIP containing persistent DLMS data. |
| Replace the workspace with a saved recovery point | **Restore from Backup** | Validates, previews, and then restores a DLMS backup after confirmation. |
| Move selected quizzes without personal history | **Portable Quiz Bundle** | Transfers eligible quiz content, not the whole installation. |
| Repair stale playable quiz pages | **Rebuild All Quiz Pages** | Regenerates derived page files without changing canonical quiz data. |
| Remove only completed attempt records | **Clear Saved Results from Database and Dashboard** | Deletes attempts, saved attempt answers, and missed-question History. |
| Start learning measurements over | **Reset Learning Intelligence** | Deletes answer evidence used for Mastery, recommendations, and schedules. |
| Remove published quizzes and their results | **Reset Quiz Library & Results** | Clears the Quiz Library, quiz records/artifacts, and related learning/history data. |
| Remove reusable imported source material | **Clear Imported / Source Content** | Removes source banks, removable packs, drafts, and staging while preserving published quizzes. |
| Restore all interface preferences to defaults | **Reset Application Settings** | Resets the saved portal configuration and custom background. |
| Return active DLMS data to a first-run state | **Reset DLMS to Fresh State** | Removes almost all active data but preserves backup ZIPs. |
| Remove the complete DLMS data directory | **Remove DLMS Data from This Computer** | Deletes active data and backups in that directory, then shuts DLMS down. |

The Portable Quiz Bundle workflow is covered in
[Import, Export, and Portability](15-import-export-and-portability.md#move-quizzes-with-a-portable-quiz-bundle).
It is not a substitute for a backup.

## Create a backup

Open **Settings → Backup & Restore**, then choose **Create & Download Backup**.
DLMS creates a ZIP snapshot and sends it to your browser as a download. The
backup page may also list up to five recent safety backups retained on the host
computer.

A backup includes persistent material such as:

- quizzes, generated quiz artifacts, question data, quiz assets, and logos;
- the database containing attempts, History, missed-question records, and
  learning activity;
- application settings and the custom background;
- installed Study Packs and Content Packs;
- PDF & Image Import question and terminology banks and relevant saved drafts;
- Law Study content; and
- other persistent runtime data recorded in the backup manifest.

It deliberately excludes temporary uploads, transient import/staging work,
temporary logo previews, database sidecar files, atomic working files, and
older backup archives. An in-progress transient import should therefore be
published or saved through its normal workflow before you depend on a backup
to preserve it.

The downloaded backup can contain personal learning history and private study
material. Store it with the same care as the source material. Copy an important
backup to a location outside the DLMS data directory so that permanent removal,
disk failure, or loss of the host computer does not remove your only recovery
copy.

## Restore a backup

Restore replaces the current persistent workspace; it is not an additive quiz
import. Use it only with a DLMS backup you trust.

1. Open **Settings → Backup & Restore**.
2. Under **Restore from Backup**, select a DLMS portable-backup ZIP. The upload
   may be up to 298 MiB.
3. Choose **Validate Backup & Continue**.
4. Read the validation report. It identifies the backup version and creation
   time, file and expanded-data totals, and summaries of content such as
   quizzes, attempts, packs, and source banks.
5. Read all warnings. If a restored custom External AI URL is unsafe or no
   longer acceptable, DLMS may clear or normalize it and explain the change.
6. Choose **Restore This Backup** only when the report describes the snapshot
   you intend to use. Choose **Cancel Restore** to remove the staged upload and
   leave current data unchanged.

<!-- Screenshot: UM-26 — Backup & Restore with a validated restore staged for confirmation -->

Before applying a confirmed restore, DLMS creates a pre-restore safety backup
of the current workspace. It then replaces persistent data and rebuilds trusted
playable quiz pages from the restored canonical quiz records. When the restore
finishes, follow the displayed instruction to reload DLMS.

A successful restore clears unfinished quiz checkpoints in the browser that
performed it. Those checkpoints referred to the pre-restore workspace and are
not safe to resume after replacement. Other browser profiles may still hold
old browser-local checkpoints; discard them rather than trying to continue
them against restored server data.

If validation fails, no restore is offered. DLMS rejects unsafe archive paths,
symbolic links, duplicate or case-colliding files, incompatible structure, and
excessive files or expansion. If applying a validated restore fails, DLMS
attempts to recover the previous workspace from the pre-restore snapshot and
keeps that backup in its backup folder. Record the displayed error and avoid
repeating destructive actions until you know which workspace is active.

## Understand safety backups

The scoped reset actions under **Reset & Remove** create a safety backup before
they change data. **Reset DLMS to Fresh State** also preserves backup ZIPs in
the DLMS backup folder.

Two actions are important exceptions:

- **Clear Saved Results from Database and Dashboard** asks for confirmation but
  does not create an automatic safety backup; and
- **Remove DLMS Data from This Computer** creates no recovery backup and deletes
  backup ZIPs stored inside the data directory.

Create and copy your own backup elsewhere before either action if you might
need the removed data.

## Clear saved results only

Under **Settings → Reset & Remove**, **Clear Saved Results from Database and
Dashboard** removes completed attempts, their saved answers, and
missed-question History. The quizzes remain in the Quiz Library.

This is narrower than resetting Learning Intelligence. Existing learning-event
evidence remains, so Learning Intelligence can still reflect activity even
after the attempt list has been cleared. If your goal is to reset Mastery,
recommendations, diagnostics, and review schedules, use the separate Learning
Intelligence reset instead.

The browser asks for confirmation. The removal is not reversible through the
normal interface unless the old data exists in a backup.

## Reset Learning Intelligence

**Reset Learning Intelligence** clears the recorded answer evidence used for
Mastery, recommendations, diagnostics, and scheduled review. Its derived
Learning Intelligence and review-schedule results begin again with no evidence.

It preserves quizzes, questions, concepts and tags, Study Packs, application
settings, completed attempt records, missed-question History, imported source
content, and backup archives. DLMS creates a safety backup before the reset.

Use this only when you deliberately want to start DLMS's learning measurements
over. It is not necessary simply because a quiz score was disappointing.

## Reset the Quiz Library and results

**Reset Quiz Library & Results** removes the published quiz collection and its
related records: questions and choices, generated quiz page data and assets,
quiz logos, attempts and missed-question History, concepts and learning events
tied to the questions, and Quiz Library organization records.

It preserves reusable source areas and configuration, including installed
Study Packs and Content Packs, PDF & Image Import banks and drafts, Law Study
content, settings and backgrounds, and existing backup archives. DLMS creates
a safety backup first.

Because saved source banks and packs remain, you may be able to generate new
quizzes from them later. Those new quizzes are not restorations of the deleted
quiz identities or their History; use a backup if you need the original
published state.

## Clear imported or source content

**Clear Imported / Source Content** removes reusable material used to create
activities, including non-protected Content Packs, PDF & Image Import question
and terminology banks, PDF and image-builder drafts, External AI drafts,
temporary uploads, and import/staging content. Protected packs remain.

Already-published quizzes are preserved. Before a removable Content Pack is
deleted, DLMS copies dependencies needed by existing quizzes into quiz-owned
storage where required. This keeps those quizzes usable; it does not preserve
the removed pack or source bank as reusable material.

DLMS creates a safety backup before clearing the source content.

## Reset application settings

**Reset Application Settings** removes the saved portal configuration and
custom background, then recreates current defaults. This resets:

- the theme, Dashboard title, and background;
- optional subject-navigation visibility;
- Parsing options;
- External AI helper, provider, URL, and prompt-template settings;
- the Application Lifecycle preference; and
- Quiz Library folder definitions and hidden-folder settings.

Quizzes and their existing folder assignments remain. A folder still assigned
to a quiz can continue to appear from that assignment, but empty custom folders
and saved hidden-folder state are lost. Quizzes, History, Study Packs, Content
Packs, PDF & Image Import banks, Law Study content, and backup archives are
otherwise preserved.

DLMS creates a safety backup first. Prefer an individual settings page when
you only want to change one category.

## Reset DLMS to a fresh state

**Reset DLMS to Fresh State** removes essentially all active user and runtime
data, including quizzes and generated pages, database records and History,
learning evidence, packs and source banks, Law Study content, drafts and
assets, and saved settings. DLMS then recreates the empty folders, database,
and default configuration it needs to continue running.

Existing backup ZIPs in the DLMS backup folder are preserved, including the
safety backup created before this reset. The installed executable or source
files are not removed. After the reset, the browser that performed it clears
its unfinished-quiz checkpoints.

Use this only when you want a first-run workspace but still want recovery
backups kept inside DLMS.

## Permanently remove DLMS data

**Remove DLMS Data from This Computer** is the broadest and least recoverable
data action. It deletes the verified DLMS application-data directory—including
quizzes, History, settings, packs, source banks, drafts, assets, caches, and
all manual or safety backup ZIPs stored there—and then shuts down DLMS.

It does not uninstall the DLMS executable or remove source files. Launching the
application again creates a new empty data directory.

To enable the action, type the exact phrase shown by the page:

```text
REMOVE DLMS DATA
```

Then accept the final confirmation. The action creates no automatic recovery
backup. Before continuing, download or copy every backup you want to keep to a
location outside the displayed DLMS data directory. Normal DLMS behavior
cannot undo the removal.

## Rebuild all quiz pages

**Rebuild All Quiz Pages** is an occasional maintenance and recovery tool. You
normally do not need to run it after updating DLMS. Use it only when DLMS
specifically instructs you to refresh generated quiz pages, when existing quiz
pages look stale or inconsistent with the current quiz interface, or when the
generated page files need repair.

The canonical saved quiz records remain the source of truth. Rebuild regenerates
only the derived playable HTML and JSON. It does **not** change:

- questions, choices, answers, or correctness;
- quiz IDs or question IDs;
- concepts or question lineage;
- Quiz Library identity, folders, or ordering;
- source or provenance details; or
- scores, attempts, learning events, History, or other learning evidence.

To run it:

1. Open **Settings → System Tools**.
2. Read the maintenance description and choose **Rebuild All Quiz Pages**.
3. Confirm that you want to rebuild all registered quiz pages from saved quiz
   data.
4. Wait for the live status to report the number rebuilt and the number that
   failed.

<!-- Screenshot: UM-27 — Rebuild All Quiz Pages and its confirmation -->

Each quiz's derived files are replaced safely. If one quiz cannot be rebuilt,
DLMS keeps that quiz's previous page files, continues reporting the overall
result, and leaves canonical quiz data unchanged. Record the failure count and
check the local application log before deciding whether further recovery is
needed.

## Other System Tools

**Image Study Editor** appears beside the rebuild action because it is an
advanced content tool, not because it repairs quizzes. It edits pack-owned
image-study metadata and is documented in
[Matching, Terminology, and Image-Based Content](11-matching-terminology-and-image-based-content.md#refine-images-and-clickable-regions).
Do not open it as a general reset or page-repair step.

## A safe maintenance sequence

When you are unsure what to do:

1. Record the exact problem and any displayed error.
2. Avoid deleting the affected source or repeating a failed import.
3. Create and download a backup if DLMS is otherwise operating normally.
4. Use the narrowest repair or reset whose stated scope matches the problem.
5. Read the confirmation and preservation details before proceeding.
6. Keep the backup until you have verified the result.

See [Troubleshooting](18-troubleshooting.md) for symptom-based guidance before
using a destructive tool.
