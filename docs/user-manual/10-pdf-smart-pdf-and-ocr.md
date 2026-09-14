# 10. PDF, Smart PDF, and OCR

DLMS can turn structured PDFs, scanned pages, and quiz screenshots into material
you can review and reuse. The right path depends on whether the source already
contains selectable text and whether it contains choice questions or
term/definition pairs.

All of these tools are available from **Build Quiz → PDF & Image Import**. Smart
PDF is the structured analysis performed inside that screen; it is not a
separate button or a general-purpose reader for arbitrary books.

## Choose the right source workflow

| Your source | Start with | What DLMS produces |
| --- | --- | --- |
| A PDF question bank with selectable text | **Analyze PDF** with Question bank or Auto-detect | A reviewed, reusable Question Bank |
| A selectable glossary or terminology PDF | **Analyze PDF** with Glossary / terminology or Auto-detect | A reviewed, reusable Terminology Bank |
| A mixed or scanned question-bank PDF | **Analyze PDF** first | Selectable text plus an optional local OCR offer for eligible low-text pages |
| One or more quiz screenshots | **Import Quiz Screenshots** | OCR question drafts, then a reusable Question Bank |
| Images or a scanned PDF containing terms and definitions | **Import Terminology Images or Scanned PDF** | One reviewed matching quiz |

Start with normal PDF analysis whenever a PDF contains selectable text. It is
faster and more reliable than optical character recognition (OCR), and DLMS
always treats that embedded text as the primary source. OCR is for text that is
present only as pixels, such as a scan or screenshot.

<!-- Screenshot: UM-15 — PDF & Image Import start screen -->

## Import a selectable-text PDF

Use this workflow for a structured question bank or glossary whose text you can
select in a PDF reader.

1. Open **Build Quiz**, then choose **Import PDF & image study content**.
2. Under **PDF file**, choose the document.
3. Enter a **Source bank title**, or leave it blank to begin with the PDF's
   filename. You can change the title during review.
4. Leave **Content type** on **Auto-detect**, or choose **Question bank** or
   **Glossary / terminology** when you already know the document's structure.
5. Set the default Exam timer for practice generated from the bank.
6. Confirm that you have permission to use the document for your own study,
   then choose **Analyze PDF**.

PDF imports are limited to 64 MiB and 2,000 pages. Encrypted, malformed, very
large, or unsupported documents can be rejected before review.

### What Smart PDF recognizes

For question banks, Smart PDF looks for repeated question structure: numbered
question headings, A–Z answer choices, explicit answer information,
explanations, and continuations across pages. It supports single-answer and
multiple-answer choice questions with 2–26 choices.

For terminology sources, it looks for a consistent relationship between a term
and its definition. When the PDF preserves useful layout or text styling, DLMS
can use that structure; otherwise it applies a conservative text-based
fallback.

Smart PDF does not treat formatting, a colored answer, a check mark, or a
visually selected option as proof of correctness. It also does not invent a
missing answer, definition, label, explanation, citation, or relationship.
Material that cannot be mapped safely is kept as incomplete or unassigned text
for you to inspect.

Structured question-bank and glossary layouts work best. An ordinary textbook
chapter, narrative article, or visually complex worksheet is not automatically
converted into a trustworthy quiz merely because it is a PDF.

## Review and repair a PDF import

Analysis opens **Review & Repair**. This is a staging step: nothing on the page
is yet a playable quiz or saved source bank.

The summary and filters separate records into **Complete**, **Needs Review**,
and **Incomplete** states. For a question bank, compare each record with the
source and:

- correct the question text;
- add, remove, reorder, or edit answer choices;
- choose single-answer or multiple-answer mode;
- mark the complete correct-answer set;
- correct or add the Study Mode explanation and choice-specific feedback; and
- exclude a record that cannot be repaired safely.

When DLMS asks you to confirm correctness, do so only after comparing the
question with the source. Editing a confirmed OCR draft resets that confirmation
so the changed answer can be checked again.

For a terminology import, correct the term and definition or exclude an
unusable record. A kept term needs both sides. Unassigned document text is there
to help diagnose the parse; it is not silently added to the saved content.

Bulk actions apply to records you select. **Select All Visible** uses the
current filter, while **Clear Selection** clears selections across all filters.
Exclusion or deletion marks are not committed until you save the reviewed bank.

<!-- Screenshot: UM-16 — PDF question-bank Review & Repair -->

## Save and use a source bank

Choose **Save Reviewed Question Bank** or **Save Reviewed Terminology Bank**
after every included record is valid. Excluded source records remain represented
in the bank but are not used for generated practice.

A saved bank is different from a quiz in the Quiz Library. It preserves the
reviewed source collection so you can create several practice quizzes without
analyzing the PDF again.

From a Question Bank, you can create practice using:

- random active questions;
- random questions not used in an earlier generated quiz;
- a sequential set beginning at a chosen question number;
- a specific question-number range; or
- all active questions.

From a Terminology Bank, you can select terms in the same general ways and
create either matching or multiple-choice practice. Choose the direction when
the practice type supports it. Multiple-choice terminology practice requires at
least four active terms so DLMS can supply distinct alternatives.

Name the practice quiz and set its Exam timer before generating it. The result
is a normal playable quiz and appears in the Quiz Library; the source bank
remains intact. Deleting a source bank later does not automatically delete
quizzes that were already generated from it.

## Use OCR with a scanned or mixed PDF

When a question-bank PDF has pages with little or no useful selectable text,
DLMS can offer those pages for local OCR. It does not send the document to a
cloud service.

The offer lists eligible pages and lets you:

- select up to 25 pages and choose **OCR Selected Pages**;
- choose **Continue Without OCR** and keep only material recovered from
  selectable text; or
- cancel the import.

For a mixed PDF, normal pages continue to use their embedded text. Only the
selected low-text pages are rendered and read with OCR, and the results return
in original page order. If one selected page fails, DLMS continues with the
others and shows the failure in the review summary.

Smart PDF can also detect substantive raster-only content inside the bounded
area of a known selectable-text question. When local OCR is available, DLMS can
use that region to fill missing question content without reparsing the entire
page or creating a duplicate question. You still review every OCR-added choice
against its temporary preview.

<!-- Screenshot: UM-17 — Scanned-PDF OCR page selection -->

## Import quiz screenshots

Use **Import Quiz Screenshots** for clear screenshots of structured choice
questions.

1. Select up to 25 PNG, JPG/JPEG, or WebP images. Multiple images are processed
   in the order you submit them.
2. Enter a source-bank title and Exam timer.
3. Confirm that you may use the screenshots, then choose **Import Quiz
   Screenshots**.
4. Wait while DLMS processes each image. If processing pauses, reload the page
   to continue the remaining screenshots.
5. Open **Review Successful Questions**, compare every draft with its source
   preview, repair it, and confirm the full correct-answer set.
6. Save the reviewed Question Bank, then generate practice from it.

Each image may be at most 16 MiB; the batch may be at most 64 MiB. An image may
also be rejected if it exceeds 12,000 pixels on either side or 40 million total
pixels. These limits help prevent an unexpectedly large image from consuming
excessive local resources.

OCR can recover A–Z choice labels, multiline answer text, and multiple correct
answers when the source structure provides reliable evidence. A highlighted,
checked, red, or green choice is never accepted by itself as proof that the
choice is correct.

Individual failures do not discard successful images. An exact duplicate image
is retained and identified rather than silently removed, leaving the final
decision to you. The original screenshots are temporary: they support review
and are removed after you save the bank, cancel the workflow, or the abandoned
staging data expires.

## Use OCR for terminology

Terminology OCR is a separate path because it looks for term/definition
relationships rather than choice-question structure. The complete procedure is
in [Matching, Terminology, and Image-Based Content](11-matching-terminology-and-image-based-content.md).

In brief, you can submit either up to 25 ordered images or one scanned PDF with
up to 25 pages. You cannot mix images and a PDF in one submission. DLMS
recognizes only conservative layouts, keeps ambiguous text for review, and
publishes the repaired result as a normal matching quiz.

## When OCR is unavailable

The PDF & Image Import page shows whether a validated local OCR runtime is
available. If it is unavailable, the screenshot, scanned-page, and terminology
OCR controls are disabled, but ordinary selectable-text PDF analysis continues
to work.

Official native packages are intended to contain their validated OCR resources.
If OCR is unavailable in a packaged release, use the troubleshooting guidance
for that release rather than trying to make the application use an unrelated
system installation. When DLMS is run from source, OCR requires additional
local components; see [Installation and First Launch](02-installation-and-first-launch.md#running-from-source)
for the user-level distinction.

## Troubleshoot PDF and OCR imports

### The PDF was rejected before review

Confirm that it is a genuine, readable PDF within the size and page limits. An
encrypted or malformed document may need to be opened and exported as a new PDF
with a tool you trust. Do not rename another file type to `.pdf`.

### Auto-detect chose the wrong kind of content

Return to PDF & Image Import and explicitly choose **Question bank** or
**Glossary / terminology**. Manual selection changes which conservative parser
is used; it does not make an unsupported layout reliable.

### Questions are incomplete or source text is unassigned

Use the retained text and source preview to repair only what the source supports.
Exclude a record you cannot verify. If the source is narrative material rather
than a structured bank, another authoring method may be more appropriate.

### OCR found only part of a batch

Review the per-source status. Continue with successful records if they are
useful, or cancel and retry with clearer, upright, higher-resolution images.
Never fill a missing answer by guessing from visual emphasis.

### A temporary review session expired

Staged imports are intentionally temporary. Return to PDF & Image Import and
start the source workflow again. Saved Question Banks, Terminology Banks, and
published quizzes are persistent; an unfinished staging draft is not.
