# 18. Troubleshooting

Most DLMS problems can be diagnosed without editing a database, generated quiz
file, or application directory. Start with the exact message shown on screen,
keep the original source material, and avoid a broad reset until you understand
what it removes.

If DLMS is working well enough to open Settings, create and download a backup
before substantial recovery work. The procedures and exact reset scopes are in
[Maintenance, Backup, and Data Management](17-maintenance-backup-and-data-management.md).

## Startup and browser problems

### DLMS did not open a browser

The application may have started even if automatic browser launch was disabled,
unavailable in a headless or SSH session, or unsuccessful.

For a normal local desktop launch, open this address yourself:

```text
http://127.0.0.1:9001/
```

A terminal launch also prints the address to use. If the page does not load,
confirm that the DLMS process is still running and check the startup output for
an error. Browser-launch behavior does not change the network bind: a headless
launch remains loopback-only unless LAN/server mode was explicitly requested.

### DLMS appears to be already running

Open `http://127.0.0.1:9001/` before starting another local copy. If the
Dashboard responds, reconnect to the existing process. If it does not, return
to the terminal, service manager, or process manager that started DLMS, confirm
that the old process has stopped, and then launch it again.

### The operating system blocks the first launch

Current Windows and macOS packages may show SmartScreen or Gatekeeper warnings
because they are not code-signed or notarized. Confirm that the package came
from the official release and matches its published SHA-256 before bypassing a
warning. Use the platform-specific steps in
[Installation and First Launch](02-installation-and-first-launch.md#install-on-windows-11)
or [the macOS instructions](02-installation-and-first-launch.md#install-on-macos-apple-silicon).

On Linux, confirm that you extracted the correct target-specific archive and
that the executable retained its execute permission.

## Shutdown and runtime problems

### Closing the browser did not stop DLMS

Closing a browser is not an unconditional shutdown command. In local desktop
mode, use **Shutdown DLMS** for an immediate stop. Automatic shutdown after the
last page closes happens only when browser-presence shutdown is enabled and the
loopback-only runtime is eligible; it waits for a grace period of about five
minutes.

In LAN/server mode, neither in-app shutdown nor browser-presence shutdown is
available. Closing client browsers does not stop the server. Stop the DLMS
process or service from the host computer.

### Shutdown DLMS is unavailable

The runtime was started in explicit LAN/server mode. The disabled control and
its explanation are intentional, and calling the shutdown action directly is
also blocked. Use the host computer's terminal, service manager, or process
manager to stop the process.

If you intended ordinary local use, stop that server instance on the host and
start DLMS again in its normal loopback-only mode. Do not decide the runtime
mode from the address of one requesting browser.

## Interface and settings problems

### A study area is missing from the navigation

Open **Settings → Navigation** and check whether the area is hidden. Hiding a
study area removes its navigation link without deleting its content. Show it
again and save the page.

On a second browser connected to the same server, refresh the page after a
settings change. Saved settings are host-side, but an already-open page may not
redraw itself immediately.

### The theme, title, or background is not what you expected

Open **Settings → Appearance** and review all values before choosing **Save
Appearance**. Leaving the background chooser empty keeps the existing image; it
does not clear it. A broad **Reset Application Settings** restores the theme,
title, background, navigation, parsing, External AI, lifecycle, and folder
configuration—not just Appearance—so do not use it to make one small visual
change.

### A quiz page looks older than the current interface

First refresh the browser page. If existing playable quiz pages remain stale or
inconsistent, **Rebuild All Quiz Pages** can regenerate their derived HTML and
JSON from canonical saved quiz data.

This is occasional repair, not a routine post-update requirement. Read its
preservation contract in
[Rebuild all quiz pages](17-maintenance-backup-and-data-management.md#rebuild-all-quiz-pages)
before confirming it.

## Quiz, Resume, and History problems

### Resume appears on one browser but not another

An interrupted Study or Exam checkpoint is stored for that browser profile and
is labeled **This browser**. Another computer or browser profile connected to
the same DLMS server does not receive it.

Completed attempts, History, due schedules, and other saved learning activity
are server-shared after refresh. This difference is expected: unfinished
recovery protects a local interruption without turning every client into the
same active quiz screen.

### A completed quiz has no Resume card

That is normal. After the final response is saved and the attempt is completed,
DLMS clears the finished browser checkpoint. Exam Mode attempts can be reviewed
in **History**. Study Mode activity contributes learning evidence but does not
create the same completed-attempt listing. Resume is for genuinely interrupted
work, not a shortcut to past results.

If the final save failed, the checkpoint should remain so the answer can be
retried. Avoid clearing browser data until you have confirmed that the completed
attempt appears in History.

### Another browser sees completed work but not the unfinished quiz

This is the same state boundary. The completed attempt is persistent server
data; the unfinished checkpoint belongs only to the browser in which it was
started. Return to that original browser to resume, or start a separate session
on the other client.

### Questions are still due after completing Due Questions

Today’s Review reports the total currently due, while one review session uses a
limited next batch. The Dashboard's default next batch is up to 20 questions;
Review Schedule can request 10, 20, 30, or 50. If more questions were due than
the completed batch included, DLMS recalculates the remainder and offers
another Due Questions action.

A completed batch should not reappear as Resume. If a Resume item is labeled
**This browser**, refresh after completion and confirm that the completed
activity appears in History before treating it as a recovery problem.

### I cannot submit an answer

Check the instruction for the current question type:

- a single-answer question needs one selected choice;
- a multi-select question may require the complete set of choices before the
  answer is correct, though you can still submit a selected response;
- a matching question needs its displayed pairs completed; and
- an image or hotspot activity expects the indicated point or region selection.

If controls do not respond after a refresh, record the quiz title, question
number, mode, and exact visible message. Do not edit the generated quiz files.

## PDF, image, and OCR problems

### OCR is unavailable

Selectable-text PDF import remains usable without OCR. OCR-dependent buttons
are unavailable when DLMS cannot verify a complete local OCR runtime.

Official native packages include their validated local OCR resources. If OCR
is missing from a packaged build, record the exact package and platform and
report the packaging problem; installing a separate system Tesseract does not
repair the frozen package. When running from source, follow the repository's
source setup for optional OCR dependencies, then restart DLMS.

### A PDF produced little or no usable text

The PDF may contain scanned page images rather than selectable text. When DLMS
detects low-text pages and OCR is available, it can offer selective scanned-page
OCR for the affected pages. Confirm only the pages you need, then inspect the
result in Review & Repair.

If the PDF contains selectable text but its structure is unusual, choose the
most accurate content type rather than Auto-detect and review the extracted
records. See [PDF, Smart PDF, and OCR](10-pdf-smart-pdf-and-ocr.md).

### OCR text or pairings are imperfect

OCR creates a draft, not trusted answers. In Review & Repair, compare the text
with the available source preview, correct wording and choices or pairs, resolve
incomplete material, and confirm the correct answers or term-definition
relationships yourself.

Terminology OCR removes the original uploaded images or rendered PDF pages
after OCR processing. The repair stage keeps source names, candidate text, and
unassigned material, but not the original page image. Keep the original source
open separately if you may need a visual comparison during repair.

### An import or review session expired

Import and Review & Repair stages can use temporary data. If DLMS says a stage
is unavailable or expired, return to the original import screen and start again
from the unchanged source file. Do not assume a temporary preview is a saved
bank or published quiz.

### An upload was rejected

Confirm that you chose the correct workflow and supported input type. A Portable
Quiz Bundle, a Study Pack ZIP, a full DLMS backup, an Anki package, a PDF, and
an image are not interchangeable even when several are archives or downloadable
files. Also check the count and size guidance displayed beside the upload.

DLMS rejects malformed or unsafe structures rather than importing a partial or
untrusted result. Keep the original file unchanged while resolving the error.

## Import, export, and portability problems

### An export did not contain History

Portable Quiz Bundles, Study Pack ZIPs, quiz text files, Anki decks, printable
cards, and External AI exchange formats are content-focused. They do not serve
as full recovery snapshots. Use **Settings → Backup & Restore** when you need
attempts, scores, learning evidence, settings, and the broader persistent
workspace.

The format comparison in
[Import, Export, and Portability](15-import-export-and-portability.md#choose-the-right-format)
shows the intended use of each file type.

### A text-exported quiz lost rich behavior after reimport

Classic quiz text represents question text, A–Z choices, and correct-answer
labels. It is not the full-fidelity format for matching pairs, hotspots, images,
concepts, explanations, or lineage. Use a Portable Quiz Bundle to move supported
rich ordinary quizzes between DLMS installations.

### An imported quiz was renamed

Portable Quiz Bundle import does not overwrite or merge an existing quiz with
the same title. The preview proposes a collision-safe imported name, and both
quizzes remain available after publication. This is a safety feature, not lost
metadata.

### An Anki file does not open in DLMS

An `.apkg` file is for the external Anki application. DLMS generates it as an
outside-study resource; it is not a DLMS quiz-import or backup format. Open or
import it in Anki. Most users should use the guided `.apkg` workflow rather
than legacy tab-separated compatibility exports.

## Library and generated-content questions

### Generated practice remains in the Quiz Library

Adaptive Study, Smart Review, Due Questions, Topic Retention Schedule, and
Concept Review can publish Generated Practice quizzes. DLMS does not
automatically delete them. Use the **Generated Practice** Smart View and the
generation-kind badges to distinguish them from ordinary source quizzes.
Successfully completed sessions show a Completed badge and remain playable;
their Library group is collapsed by default when they are Uncategorized.

A Mixed Quiz is curated and reusable, so it is labeled separately rather than
treated as transient Generated Practice. Hiding or deleting a quiz has the
same user-controlled implications described in
[Quiz Library and Organization](05-quiz-library-and-organization.md); do not
assume that a generated label makes deletion automatic.

### A Smart View changed without moving my quizzes

Smart Views are dynamic filters, not folders. Their membership can change when
you complete an attempt, add content, change learning evidence, or create
generated practice. Select the normal full-library view to leave the filter;
the quizzes have not been moved.

## Backup and restore problems

### A backup is rejected before confirmation

DLMS validates the archive before replacing data. It can reject an invalid or
incompatible backup, an unsafe path or symbolic link, duplicate paths,
unexpected structure, excessive files or expansion, or an upload above the
1 GiB limit. Use the original ZIP created by **Backup & Restore**; do not
unpack, edit, and re-zip its contents.

Because validation did not reach confirmation, current DLMS data remains
unchanged.

### A restore failed after confirmation

DLMS creates a pre-restore safety backup before applying the snapshot and
attempts to restore the prior workspace if the operation fails. Read the exact
failure page. If it says a pre-restore backup was created, leave that archive
in place and avoid further resets until you have verified the current data.

Return to **Backup & Restore** only after recording the message. If DLMS is no
longer reachable, preserve the data directory and backup files rather than
manually replacing individual database or generated files.

### Restore succeeded but an old Resume item is gone

This is deliberate. A successful restore replaces server data and clears
unfinished checkpoints in the browser that performed it so they cannot resume
against a different workspace. Open History or the Quiz Library in the
restored state and begin a new session.

## Before using a reset

Do not use **Reset DLMS to Fresh State** or permanent removal as general
troubleshooting shortcuts. Instead:

1. identify whether the problem concerns History, Learning Intelligence,
   published quizzes, imported source content, settings, or only derived quiz
   pages;
2. create and download a backup;
3. compare the exact actions in
   [Maintenance, Backup, and Data Management](17-maintenance-backup-and-data-management.md#choose-the-right-data-tool);
4. choose the narrowest matching action; and
5. read the confirmation before proceeding.

Permanent data removal has no automatic recovery backup and deletes backups
stored inside the DLMS data directory. Copy a backup elsewhere first.

## Gather useful information when a problem remains

When asking for help, record information that identifies the environment and
workflow without exposing private study material:

- the DLMS version shown in Help;
- operating system and native package name, or that you are running from
  source;
- local desktop or LAN/server mode;
- the page and action that led to the problem;
- the exact displayed error or status message;
- whether the issue persists after a normal page refresh; and
- for import problems, the general file type and size without sharing private
  contents unless you have chosen to do so.

Use the safe error message shown in the application; a packaged desktop launch
does not guarantee an accessible application log. If restore reports that recovery
is still required, stop editing, retain the safety backup and recovery files, and
restart after checking disk space and data-folder access. If recovery still fails,
seek help before deleting files or resetting DLMS. Do not post
backups, private quizzes, credentials, or personal learning History in a public
issue.
