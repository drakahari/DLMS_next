# Appendix: Glossary

This glossary defines names that appear in the DLMS interface and manual. The
linked chapters explain the corresponding workflows.

## A

### Adaptive Study

A personalized Generated Practice session that balances several current
learning signals across quizzes and concepts. Choose it when you want DLMS to
decide what needs attention without limiting the session to one concept or one
kind of weakness. See [Study and Review](07-study-and-review.md#use-adaptive-study-for-a-balanced-focus).

### Analytics

Attempt-level summaries such as average, best, latest, and per-quiz
performance. Analytics is based on recorded results; **Learning Intelligence**
uses broader question- and concept-level evidence. See
[History, Results, and Progress](09-history-results-and-progress.md).

### Anki Tools

The DLMS area for creating Anki `.apkg` decks and printable cards from supported
quiz, missed-question, custom, and Law material. Anki is a separate
application. See [Anki, Decks, and Printable Cards](14-anki-decks-and-printable-cards.md).

### Attempt

One run through a quiz, especially a completed Exam Mode result stored in
History. An interrupted attempt can also have a Resume checkpoint in the
current browser.

## B

### Backup

A ZIP snapshot of the persistent DLMS workspace intended for recovery or
transfer. A backup is broader than a Portable Quiz Bundle and can contain
personal history and settings. See
[Maintenance, Backup, and Data Management](17-maintenance-backup-and-data-management.md).

### Build Quiz

The main content-creation hub. It leads to direct authoring and text, PDF/image,
matching CSV, and External AI workflows. See
[Creating and Importing Content](04-creating-and-importing-content.md).

## C

### Concept

A reusable topic label attached to a question. Learning Intelligence can
combine evidence for the same concept across several quizzes.

### Concept Review

A Generated Practice session focused on one concept selected by the user. It is
also launched through **Study concept** in Learning Intelligence. See
[Study and Review](07-study-and-review.md#use-concept-review-for-one-chosen-concept).

### Content Pack

The managed, validated form of reusable pack content. Content Packs are
installed, inspected, exported, or removed through content management; their
learner-facing material appears in Study Packs. See
[Study Packs and Content Packs](13-study-packs-and-content-packs.md).

## D

### Deck

A collection of study cards prepared for Anki or printing. A deck is not an
interactive DLMS quiz, even when quiz questions supply its cards.

### Due Questions

DLMS's question-level spaced schedule. Each eligible source question becomes
due according to its saved correctness history; a correct streak advances
through longer intervals and a wrong answer returns the interval to one day.
See [Study and Review](07-study-and-review.md#review-due-questions).

### Duplicate Question Review

An advisory Quiz Library tool that finds exact and conservative possible
duplicates among source questions. It does not automatically merge, rewrite,
or delete anything. See
[Quiz Library and Organization](05-quiz-library-and-organization.md#review-possible-duplicates).

## E

### Exam Mode

A timed, test-like way to take a quiz. Answers are submitted as an attempt and
the completed result is recorded in History. See
[Taking Quizzes](06-taking-quizzes.md#use-exam-mode-for-a-test-like-attempt).

### External AI

An optional, provider-neutral workflow in which DLMS prepares a prompt and the
user manually exchanges content with a conversational AI service. DLMS does not
call the provider through an API. See
[External AI Workflows](12-external-ai-workflows.md).

## F

### Folder

A persistent, user-created Quiz Library grouping. A hidden folder is removed
from the normal folder display but is not deleted; search and dynamic views can
still surface relevant quizzes. A Folder is different from a Smart View.

## G

### Generated Practice

The Quiz Library category for saved Adaptive Study, Smart Review, Concept
Review, Due Questions, and Topic Retention practice. Generated copies preserve
their relationship to source questions so answers contribute to the right
learning evidence. Uncategorized sessions appear in an automatic Library group,
and cards can show live source-quiz summaries when lineage is available. They
are not automatically cleaned up. See
[Quiz Library and Organization](05-quiz-library-and-organization.md#recognize-generated-practice).

## H

### History

The area containing saved completed attempts, results, missed questions, and
attempt review. History is persistent server data; a browser-local Resume
checkpoint is not History. See
[History, Results, and Progress](09-history-results-and-progress.md).

### Hotspot

An image question answered by selecting a saved circle or polygon target. DLMS
supports pointer and keyboard answer paths and keyboard region authoring. See
[Matching, Terminology, and Image-Based Content](11-matching-terminology-and-image-based-content.md#clickable-regions).

## I

### Image Prep

A non-destructive Image Study editing mode for adding supported masks and labels
while retaining the source image. It is not a general-purpose photo editor.

## L

### LAN/server mode

An explicit non-loopback runtime that makes one DLMS workspace reachable on a
trusted local network. It does not add accounts, authentication, or TLS.
In-app/API and automatic browser-presence shutdown are unavailable; stop the
process or service on the host computer. See
[Platform and Runtime Notes](appendix-platform-and-runtime-notes.md#lanserver-mode).

### Learning Intelligence

DLMS's concept-oriented view of learning evidence across quizzes. It presents
accuracy, recent performance, Mastery, Trend, evidence, and actions for targeted
practice. See [Learning Intelligence](08-learning-intelligence.md).

### Local desktop mode

The normal loopback-only runtime in which DLMS runs on the user's computer and
opens a local browser interface. It supports the in-app **Shutdown DLMS** action
and, when enabled and eligible, optional browser-presence shutdown.

### Low Score

A Smart View containing quizzes whose latest completed attempt is below 75%.
It is not a Mastery or weak-concept measure.

## M

### Mastery

A 0–100 Learning Intelligence indicator that combines overall performance,
recent performance, amount of evidence, and recency. It is an aid to deciding
what to study, not a permanent label or the same thing as raw accuracy. See
[Understanding Mastery](08-learning-intelligence.md#understand-mastery).

### Matching

A question or activity that pairs left/right values, commonly terms and
definitions. It may use dropdowns or an interactive answer-and-target layout.

### Missed-question review

A retry of questions answered incorrectly in a particular completed attempt.
It starts from actual misses in that attempt and is different from broader
Smart Review or scheduled Due Questions.

### Mixed Quiz

A curated, reusable quiz composed from questions in two or more source quizzes.
It remains visually distinct from transient Generated Practice. See
[Quiz Library and Organization](05-quiz-library-and-organization.md#keep-mixed-quizzes-distinct).

### Multi-select question

A choice question with more than one correct answer. Select every answer you
believe is correct. DLMS also uses **multiple-answer** in some import and Review
& Repair screens for the same answer behavior.

## N

### Needs Review

A Smart View containing quizzes with source questions that are currently due
or overdue. It is schedule-derived and is unrelated to Review & Repair.

### Not enough data

A Learning Intelligence state for a concept supported by fewer than three
responses. It means DLMS is deliberately avoiding a strong conclusion, not
that the learner has zero knowledge or has failed.

## O

### OCR

Optical character recognition performed locally by DLMS for supported
screenshots, scanned pages, and targeted image-only regions. OCR output can be
imperfect and must be reviewed. Selectable-text PDF extraction is not OCR. See
[PDF, Smart PDF, and OCR](10-pdf-smart-pdf-and-ocr.md).

### OCR Imported

A Smart View for quizzes carrying explicit local OCR provenance. It is not
based on a filename guess and does not mean every ordinary PDF import appears
there.

## P

### Portable Quiz Bundle

A versioned ZIP for moving selected ordinary quizzes, supported metadata,
folders, and media between DLMS installations. It excludes personal history,
scores, and scheduling state and is not a full backup. See
[Import, Export, and Portability](15-import-export-and-portability.md#move-quizzes-with-a-portable-quiz-bundle).

## Q

### Question Bank

A saved, reviewed collection extracted from source material. It can generate
question practice through several selection strategies and is separate from
the Quiz Library.

### Quiz

A saved set of choice, matching, or hotspot questions that can be taken in
Study Mode or Exam Mode, with supported images where applicable.

### Quiz Library

The main screen for finding, organizing, opening, editing, exporting, and
managing saved quizzes. See
[Quiz Library and Organization](05-quiz-library-and-organization.md).

## R

### Recently Added

A Smart View for quizzes with a reliable creation or import time in the last
30 days. It means recently added, not recently studied.

### Restore

A staged and validated replacement of persistent DLMS data from a backup. DLMS
creates a pre-restore safety backup before applying the confirmed replacement.
Restore is not the same as importing a quiz or pack.

### Resume

Continue a valid interrupted quiz checkpoint saved in the current browser.
Successfully completed and saved sessions clear their recovery state. A Resume
card does not synchronize to another browser.

### Review & Repair

A staging step where extracted or AI-produced questions or pairs can be
corrected, excluded, ordered, validated, and explicitly confirmed before
publication. It is not itself the final quiz.

### Review Schedule

The screen that presents both question-level **Due Questions** and concept-level
**Topic Retention Schedule** information and actions.

## S

### Shutdown DLMS

The immediate in-app stop action available in local desktop mode. It is
unavailable in LAN/server mode, where the process or service must be stopped on
the host computer.

### Smart PDF

DLMS's structured analysis of selectable PDF text, including classification,
bank creation, and bounded OCR assistance. The screen a user opens is named
**PDF & Image Import**; Smart PDF is not a separate generic visual-reading
service.

### Smart Review

A Generated Practice session drawn broadly from source questions associated
with weak concepts. Adaptive Study balances more kinds of signals, while
Concept Review focuses on one user-selected concept.

### Smart View

A dynamic Quiz Library filter based on current metadata, history, learning
state, or browser-local recovery. It does not move or store quizzes like a
Folder.

### Source question

An ordinary authored or imported question that supplies canonical learning
content. Generated copies point back to it when that relationship is known.

### Study concept

The Learning Intelligence action that starts Concept Review for a selected
concept.

### Study Mode

An untimed learning mode that records completed answers and shows immediate
correctness, explanations, and supported teaching detail. See
[Taking Quizzes](06-taking-quizzes.md#use-study-mode-for-guided-learning).

### Study Pack

An installed, learner-facing collection of matching, image/hotspot, or quiz
material. Management of the underlying package occurs through Content Packs.

## T

### Terminology Bank

A saved, reviewed collection of terms and definitions used to generate
matching or choice practice.

### This browser

A label indicating that an unfinished Resume checkpoint belongs only to the
current browser profile or device. Server-derived due counts and completed
history remain shared by clients of the same DLMS instance.

### Today’s Review

The Dashboard's concise daily action plan and the recommended answer to “What
should I study right now?” It combines links to existing recommendations and
unfinished work rather than acting as one new review algorithm. See
[Study and Review](07-study-and-review.md#start-with-todays-review).

### Topic Retention Schedule

Concept-level review timing based on available concept mastery and evidence. It
schedules topics, not individual questions, and is distinct from Due Questions.

### Trend

A Learning Intelligence direction—Improving, Stable, Declining, or not enough
data—based on recent adjacent result windows. Trend measures direction; Mastery
summarizes current strength.

## U

### Unfinished

A Smart View for valid interrupted quiz checkpoints in the current browser.
Its membership can differ between clients connected to the same DLMS server.

## W

### Weak area

A concept with enough recorded evidence whose current learning measures meet
DLMS's weak-area criteria. A concept with too little evidence is not labeled
weak merely because few answers exist.
