# Feature and Format Reference

This chapter is a quick reference for users who already know the main DLMS
workflows. Follow the links for complete instructions and safety guidance.

## Question and content types

| Type | What it is | Where to learn more |
| --- | --- | --- |
| Single-answer choice | A choice question with one correct answer. | [Creating and Importing Content](04-creating-and-importing-content.md#add-choice-questions) |
| Multi-select choice | A choice question with more than one correct answer. DLMS creates this behavior automatically when the author marks multiple choices correct. | [Creating and Importing Content](04-creating-and-importing-content.md#add-choice-questions) |
| Matching | A set of left/right pairs, often terms and definitions. A quiz can present the pairs as dropdowns or an interactive matching activity. | [Matching, Terminology, and Image-Based Content](11-matching-terminology-and-image-based-content.md) |
| Image-supported question | A choice or matching question that includes a supporting image. | [Matching, Terminology, and Image-Based Content](11-matching-terminology-and-image-based-content.md#create-image-based-study-material) |
| Hotspot | An image question answered by selecting a saved circle or polygon region. | [Matching, Terminology, and Image-Based Content](11-matching-terminology-and-image-based-content.md#clickable-regions) |
| Question Bank | A reviewed collection extracted from a PDF or related source. It can generate practice by random, unused, sequential, range, or all-question selection. | [PDF, Smart PDF, and OCR](10-pdf-smart-pdf-and-ocr.md#save-and-use-a-source-bank) |
| Terminology Bank | A reviewed collection of terms and definitions that can generate matching or choice practice. | [PDF, Smart PDF, and OCR](10-pdf-smart-pdf-and-ocr.md#save-and-use-a-source-bank) |
| Study Pack material | Installed matching, image, hotspot, or quiz material presented through the Study Packs catalog. | [Study Packs and Content Packs](13-study-packs-and-content-packs.md) |

## Ways to add content

| Starting material | Recommended method | Review before publication? | Detailed guide |
| --- | --- | --- | --- |
| A few questions you want to type | Short Quiz Builder | The builder validates the quiz when you save it. | [Direct quiz creation](04-creating-and-importing-content.md#create-a-quiz-directly) |
| Structured choice-question text | Paste text or upload a UTF-8 text file | Yes, when the parser sends the result through Review & Repair. | [Text import](04-creating-and-importing-content.md#import-structured-choice-question-text) |
| A matching CSV | Matching CSV import | Yes; inspect the pairs before publishing. | [Matching CSV](11-matching-terminology-and-image-based-content.md#import-a-matching-csv) |
| A selectable-text PDF | PDF & Image Import | Yes; inspect the extracted Question Bank or Terminology Bank. | [Selectable PDFs](10-pdf-smart-pdf-and-ocr.md#import-a-selectable-text-pdf) |
| A scanned or low-text PDF | Local OCR on selected candidate pages | Yes; OCR output always requires review. | [Scanned PDFs](10-pdf-smart-pdf-and-ocr.md#use-ocr-with-a-scanned-or-mixed-pdf) |
| Screenshots of choice questions | Screenshot OCR | Yes; visual highlighting does not establish correctness. | [Screenshot question OCR](10-pdf-smart-pdf-and-ocr.md#import-quiz-screenshots) |
| Images or a scanned PDF containing terms and definitions | OCR-assisted matching/terminology | Yes; ambiguous text remains available for repair instead of being silently paired. | [OCR-assisted terminology](11-matching-terminology-and-image-based-content.md#import-matching-material-with-ocr) |
| Images for a visual study activity | Image Study Builder | Use the builder/editor preview and test controls. | [Image Study](11-matching-terminology-and-image-based-content.md#create-image-based-study-material) |
| Structured content prepared by a conversational AI | External AI Builder | Yes; DLMS validates and stages the pasted result. | [External AI Workflows](12-external-ai-workflows.md) |
| An AI-produced Study Pack archive | AI Study Pack ZIP import | Yes; the archive follows Content Pack validation and review. | [AI Study Pack workflow](12-external-ai-workflows.md#create-an-ai-assisted-study-pack) |
| Quizzes exported from another DLMS installation | Portable Quiz Bundle import | Preview and confirm the validated bundle. | [Portable Quiz Bundles](15-import-export-and-portability.md#move-quizzes-with-a-portable-quiz-bundle) |
| A reusable Study Pack archive | Content Pack import | Review validation details before installation. | [Importing a Content Pack](13-study-packs-and-content-packs.md#import-a-content-pack-zip) |

## File and package comparison

These formats solve different problems. In particular, a Portable Quiz Bundle
is not a full backup, and an Anki deck is not an interactive DLMS quiz.

| Format or output | Primary purpose | Importable into DLMS? | Full backup? | Preserves rich DLMS quiz types? | Intended for external study? | Guide |
| --- | --- | --- | --- | --- | --- | --- |
| DLMS backup ZIP | Recover or transfer the complete persistent DLMS workspace. | Yes, through Backup & Restore. | Yes, for the DLMS data covered by the backup. | Yes, as part of the saved workspace. | No. | [Backup and restore](17-maintenance-backup-and-data-management.md) |
| Portable Quiz Bundle ZIP | Move selected ordinary quizzes, supported metadata, folders, and media between DLMS installations. | Yes. | No; it excludes personal study data and application-wide state. | Choice and matching content plus supported quiz media are preserved. | No. | [Portable Quiz Bundles](15-import-export-and-portability.md#move-quizzes-with-a-portable-quiz-bundle) |
| Content Pack / Study Pack ZIP | Install, export, or exchange a reusable pack of supported study material. | Yes, through Content Packs. | No; it is content, not a personal data snapshot. | It preserves the material supported by the pack format. | Primarily for DLMS study. | [Study Packs and Content Packs](13-study-packs-and-content-packs.md) |
| AI Study Pack ZIP | Carry a structured pack returned by an external conversational AI into DLMS validation and review. | Yes, through the AI Study Pack workflow. | No. | Only content allowed by the Study Pack contract. | It is an AI exchange format before becoming DLMS content. | [External AI Workflows](12-external-ai-workflows.md#create-an-ai-assisted-study-pack) |
| Anki `.apkg` | Study exported cards in Anki. | No guided DLMS re-import. | No. | No; interactive DLMS behavior becomes cards. | Yes. | [Anki, Decks, and Printable Cards](14-anki-decks-and-printable-cards.md) |
| Printable cards | Print or save a browser-formatted card layout. | No. | No. | No; this is a presentation format. | Yes. | [Printable cards](14-anki-decks-and-printable-cards.md#print-physical-cards) |
| Individual quiz `.txt` | Export or import classic choice-question text. | Yes, for the supported classic choice format. | No. | No; do not use it to preserve matching, image/hotspot, concepts, or other rich metadata. | Sometimes, as readable text. | [Classic text export](15-import-export-and-portability.md#use-quiz-text-files) |
| Quiz Library Reference `.txt` | Create a readable reference listing of the library. | No. | No. | No; it is a reference report rather than a transfer format. | Yes, for reading or printing. | [Reference and text exports](15-import-export-and-portability.md#download-the-full-library-reference) |
| Matching CSV | Import rows of left/right matching content. | Yes. | No. | It represents matching pairs, not a complete rich quiz. | No. | [Matching CSV](11-matching-terminology-and-image-based-content.md#import-a-matching-csv) |
| External AI structured JSON/text | Manually transfer generated choice or matching content back to DLMS. | Yes, through the matching External AI workflow. | No. | It preserves only the fields accepted by that workflow. | It is an exchange format with an external service. | [External AI Workflows](12-external-ai-workflows.md) |
| Legacy Anki TSV | Compatibility export for older tab-separated workflows. | Not through the current guided DLMS interface. | No. | No. | Yes, as an advanced compatibility format. | [Legacy compatibility exports](14-anki-decks-and-printable-cards.md#advanced-legacy-tsv-compatibility) |

Other downloadable text, such as a Law Case Review export or a parser's
cleaned working text, is useful for reading or a specific workflow. It is not a
complete DLMS backup or a universal import format.

## Input and creation limits

The following limits are part of the current DLMS 3.2.0 user-facing contract.
They protect a local application from unexpectedly large or malformed input.

| Workflow | Current limit or requirement |
| --- | --- |
| Short Quiz Builder | Start with 1–100 question blocks. Each choice question may contain 1–26 nonblank choices and must have at least one marked correct choice. |
| Exam timer | 1–1,440 minutes; new quizzes normally start at 90 minutes. |
| Matching question | At least two valid pairs. A configured pairs-per-round value may be 2–100; leaving it blank uses all available pairs. |
| Quiz text upload | UTF-8 text, up to 16 MiB. |
| Matching CSV upload | UTF-8 CSV, up to 16 MiB, with `term`/`definition` or `left`/`right` headers and at least two valid, nonconflicting pairs. |
| PDF import | One PDF up to 64 MiB and 2,000 pages. |
| Scanned/low-text PDF OCR | Up to 25 selected candidate pages per OCR run. |
| Screenshot question OCR | Up to 25 PNG, JPEG/JPG, or WebP images; 16 MiB per image and 64 MiB in total. Each image may be at most 12,000 pixels on either side and 40 million pixels. |
| Terminology OCR | Up to 25 images **or** one scanned PDF with up to 25 selected pages. Images and a PDF cannot be mixed in the same submission. |
| External AI choice request | 1–100 questions. Pasted structured response up to 1 MiB. |
| External AI matching request | 2–100 pairs. Pasted structured response up to 1 MiB. |
| Portable Quiz Bundle import | Archive up to 128 MiB; up to 100 quizzes and 10,000 questions in total. DLMS also enforces per-file, expanded-size, media, and archive-safety limits. |
| Content Pack import | Archive up to 256 MiB. DLMS also validates its expanded size, entries, paths, and supported content. |
| Backup restore upload | Backup ZIP up to 298 MiB. |
| Image Study uploads | Up to 12 PNG, JPEG/JPG, or WebP images; each image up to 32 MiB and 80 million pixels, with a 16,000-pixel side limit; total staged images up to 192 MiB. |
| Mixed Quiz | Select at least two source quizzes and at least two questions. |

DLMS may reject input below a headline size limit if it has unsafe paths,
unsupported structure, excessive expanded size, conflicting records, or other
validation failures. Do not split or alter an archive to bypass validation;
correct the source material instead.

## Study and review quick reference

| Option | Use it when | Selection level | Creates Generated Practice? |
| --- | --- | --- | --- |
| Today's Review | You want one recommended starting point based on current DLMS signals. | A planning surface that links to several existing actions. | No; the action you choose may create it. |
| Adaptive Study | You want DLMS to choose a balanced personalized session. | Questions across several learning signals and sources. | Yes. |
| Smart Review | You want broad practice from weak concepts. | Source questions associated with weak concepts. | Yes. |
| Concept Review | You want to choose one concept and study it directly. | One user-selected concept. | Yes. |
| Due Questions | You want to answer source questions due on their individual schedule. | Individual questions; batches of 10, 20, 30, or 50 on Review Schedule. | Yes. |
| Topic Retention Schedule | You want concept-level review based on topic mastery and evidence. | Concepts/topics rather than individual question schedules. | Yes. |
| Missed-question review | You want to retry misses from one completed attempt. | Incorrect answers from that attempt. | No Generated Practice category. |

See [Study and Review](07-study-and-review.md) for the distinctions, batch
behavior, and practical decision guide.

## Generated Practice categories

The Quiz Library labels these current generated-session types as **Generated
Practice**:

- Adaptive Study practice;
- Smart Review practice;
- Concept Review practice;
- Due Questions practice;
- Topic Retention practice.

These saved sessions can remain visible in the library; DLMS does not
automatically clean them up. A **Mixed Quiz** remains a separate, curated and
reusable category even though DLMS composed it from other quizzes. See
[Generated Practice](05-quiz-library-and-organization.md#recognize-generated-practice)
for the practical library behavior.

## Quiz Library Smart Views

Smart Views are dynamic filters, not storage folders.

| Smart View | Current membership rule |
| --- | --- |
| Needs Review | Quizzes with source questions that are currently due or overdue. |
| Recently Added | Quizzes with a reliable creation/import time in the last 30 days. |
| Low Score | Quizzes whose latest completed attempt is below 75%. |
| Unfinished | Quizzes with a recoverable checkpoint in **this browser**. |
| OCR Imported | Quizzes with explicit local OCR provenance. |
| Generated Practice | Saved Adaptive, Smart, Concept, Due Questions, and Topic Retention practice sessions. |

Membership can change when history, scheduling, local recovery, or quiz
metadata changes. Search can be combined with a Smart View. Full behavior is
covered in [Quiz Library and Organization](05-quiz-library-and-organization.md#use-smart-views-as-dynamic-filters).

## Data scope quick reference

| Information | Where it applies |
| --- | --- |
| Quiz content, folders, completed attempts, learning evidence, settings, and schedules | Persisted in the DLMS workspace and visible to clients of the same running installation after refresh. |
| Interrupted-session Resume checkpoint | Stored by the current browser profile and marked **This browser**. It is not synchronized to another client. |
| Generated Practice quiz | Saved in the Quiz Library until the user manages it; its answers can contribute learning evidence to source questions. |
| Portable Quiz Bundle | Carries selected content and supported media, not personal scores, attempts, history, or scheduling state. |
| Backup | Captures the persistent workspace for recovery, while excluding transient staging and temporary processing files. |
| OCR/import staging | Temporary working material used only long enough for its workflow; retention varies by workflow and is not a backup. |

For privacy implications, see [Privacy and Data Handling](appendix-privacy-and-data-handling.md).

## Native packages

DLMS 3.2.0 release tooling defines packages for these targets:

- Fedora 44 x86-64;
- Ubuntu 24.04 x86-64;
- Ubuntu 26.04 x86-64;
- Omarchy Quattro x86-64;
- Windows 11 x86-64;
- macOS Apple Silicon (arm64).

Use the package built for the named operating system and architecture. These
are packaging targets, not a promise that every unlisted operating-system
version is unsupported or compatible. Installation and runtime differences are
summarized in [Platform and Runtime Notes](appendix-platform-and-runtime-notes.md).
