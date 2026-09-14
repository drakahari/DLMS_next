# 11. Matching, Terminology, and Image-Based Content

Matching and image-based material add forms of practice that ordinary text
choice questions cannot provide. Matching asks you to connect corresponding
items. Image questions place visual context beside a choice or matching task,
or ask you to identify a region directly on an image.

These formats use several distinct authoring and import paths. Choose the path
that fits your source instead of looking for one universal matching or image
builder.

## Choose a matching or image workflow

| If you want to… | Use… | Result |
| --- | --- | --- |
| Type a matching question yourself | **Create a short quiz** | A normal quiz containing your matching question |
| Import a spreadsheet of term/definition pairs | **Import matching pairs** | A normal matching quiz |
| Reuse terms from a selectable PDF | **PDF & Image Import** | A persistent Terminology Bank that can generate matching or choice practice |
| Recover terms from screenshots or a scanned PDF | **Import Terminology Images or Scanned PDF** | An OCR draft, then one normal matching quiz |
| Use structured matching content from a conversational AI | **External AI Quiz Builder** | A reviewed normal matching quiz |
| Build questions around your own images | **Build from image(s)** | An image Study Pack and a playable quiz |
| Repair an installed pack's images or targets | **Image Study Editor** | Updated derived image-prep or clickable-region data |

The direct Short Quiz Builder and matching CSV procedure are introduced in
[Creating and Importing Content](04-creating-and-importing-content.md). This
chapter concentrates on how the content behaves and on the specialized OCR and
image workflows.

## Understand matching questions

A matching question contains one set of saved pairs. Each pair has a left side
and a right side—commonly a term and its definition, though the same format can
represent any unambiguous one-to-one relationship.

The direction controls what the learner sees as the prompt side:

- **Term → Definition** starts with terms;
- **Definition → Term** starts with definitions; and
- **Random Each Attempt** lets the direction vary between attempts.

**Pairs Per Round** limits how many of the saved pairs appear in an attempt.
Leaving that value blank in the direct builder uses every pair. Other workflows
provide a bounded numeric control and reduce the round to the number of pairs
actually available when necessary.

A valid matching question needs at least two complete pairs. The left values
must remain distinct, the right values must remain distinct, and one left value
cannot map to several conflicting answers. DLMS may warn about differences that
are only capitalization, because those can still be hard to distinguish during
practice.

Matching is not multiple choice. The saved pairs define correctness; there are
no correct-answer checkboxes. During a quiz, use drag and drop or the accessible
selection controls described in [Taking Quizzes](06-taking-quizzes.md#matching).

## Create or import matching material

### Type a matching question

In **Build Quiz → Create a short quiz**, set a question's type to **Matching**,
enter the instructions, and complete at least two pair rows. Choose the direction
and optional round size, then create the quiz. Blank rows are ignored, but a row
with only one completed side must be finished or removed.

You can mix matching and choice questions in one directly authored quiz. The
quiz editor lets you adjust matching instructions, direction, round size, and
pairs after publication.

### Import a matching CSV

Use **Build Quiz → Import matching pairs** for a UTF-8 CSV whose headers are
`term,definition`. The alternate headers `left,right` also work. Supply a quiz
title, choose a direction, set the pairs shown per round, and optionally record
source information.

Rows missing either side are skipped. DLMS rejects an unreadable file, missing
required columns, fewer than two usable pairs, duplicate sides, or conflicting
mappings. A successful CSV import creates the quiz directly and opens its
editor; it does not use the separate Review & Repair staging screen.

### Generate practice from a Terminology Bank

A selectable glossary PDF can become a Terminology Bank after Review & Repair.
The bank remains the source collection, while each generated quiz is a separate
practice result. You can choose random, unused, sequential, range-based, or all
active terms and generate matching or multiple-choice practice.

See [PDF, Smart PDF, and OCR](10-pdf-smart-pdf-and-ocr.md#save-and-use-a-source-bank)
for the complete bank workflow.

## Import matching material with OCR

Use **PDF & Image Import → Import Terminology Images or Scanned PDF** when the
terms are visible in screenshots, photographs, or scanned pages rather than
available as selectable text.

You may select:

- up to 25 PNG, JPG/JPEG, or WebP images, processed in submitted order; or
- one scanned PDF containing no more than 25 pages.

Do not select images and a PDF in the same submission. Enter the quiz title,
matching prompt, and direction, confirm your right to use the material, then
choose **Extract Terminology Pairs**.

Terminology image uploads use the same safeguards as quiz screenshots: at most
16 MiB per image and 64 MiB for the batch, with a 12,000-pixel side limit and a
40-million-pixel total limit per image. The scanned PDF is limited to 64 MiB in
addition to the 25-page workflow limit.

DLMS recognizes conservative patterns such as:

- `Term — Definition` or `Term - Definition`;
- `Term: Definition`;
- clearly labeled **Term** and **Definition** lines; and
- two-column rows only when the alignment and OCR confidence are consistent
  enough to support the relationship.

A large gap on one line or nearby words on a page are not enough by themselves.
Ambiguous text stays unassigned, and a labeled term or definition with a missing
partner remains incomplete rather than being paired with a guess.

The processing page handles one source at a time. A source that cannot be read
does not discard useful results from the others. When extraction finishes, DLMS
moves the candidate text and source names into the shared matching Review &
Repair draft, then removes the original temporary images or rendered PDF pages.
Use the retained source labels and unassigned text to compare against your own
original files while repairing the result.

<!-- Screenshot: UM-18 — OCR matching Review & Repair -->

### Review and publish OCR matching

Review & Repair presents one matching question assembled from the ordered
sources. You can:

- edit the matching prompt and direction;
- choose the number of pairs per attempt;
- edit, add, delete, and reorder pairs;
- add an optional category or explanation to a pair;
- inspect extraction diagnostics and unassigned text;
- exclude the matching question if it cannot be repaired; and
- confirm that you reviewed every final pairing.

The first draft uses up to 10 pairs per attempt, or fewer when fewer pairs were
found. You can change that value from 2 up to the number of valid pairs, with an
overall limit of 100.

Duplicate, incomplete, or conflicting mappings block publication until you fix
them. DLMS revalidates all edited content when you choose **Publish Reviewed
Quiz**. The result is a normal matching quiz in the Quiz Library, not a
Terminology Bank.

## Create image-based study material

Use **Build Quiz → Build from image(s)** when an image is part of the question,
not merely a source from which OCR should extract text. This workflow can create:

- a single-answer or multi-select choice question shown with an image;
- a matching question shown with an image; or
- a hotspot question answered by identifying a circle or polygon region.

### Upload and describe the images

1. Choose one or more PNG, JPG/JPEG, or WebP files. One batch can contain up to
   12 images.
2. Choose **Upload & Continue**.
3. Enter the **Study Pack / Quiz Title**, subject/domain, and Exam Mode timer.
   Add a description and source/credit note when useful.
4. Review or improve the accessible description shown for each image.
5. Confirm that you have permission to use the images.

Images are validated as real raster files rather than trusted by filename alone.
An individual upload is bounded to 32 MiB, the batch to 192 MiB, and an image to
80 million pixels. If an image is rejected, use a valid supported format and a
practical resolution rather than merely renaming the file.

### Add questions

Choose **Add Question**, select the image, and choose the question type. The
same uploaded image can support more than one question.

For choice questions, enter at least two nonblank choices and mark one or more
as correct. One marked choice creates single-answer behavior; several create
multi-select behavior. For matching, enter at least two complete pairs.

For a hotspot, enter a target label and choose **Circle** or **Polygon**:

- A circle needs one center point and a radius.
- A polygon needs at least three points around the intended boundary.

Use a pointer to place points, or focus the hotspot stage with the keyboard.
The arrow keys move the blue cursor, **Enter** or **Space** places a point, and
holding **Shift** while using an arrow key makes a finer movement. **Clear
Region** starts that target again.

Choose **Create Study Pack & Quiz** after every question is valid. DLMS validates
and installs the user-supplied image Study Pack, creates its quiz through the
normal publication path, and opens the playable result. The Study Pack remains
available as the installed source material.

## Refine images and clickable regions

The **Image Study Editor** is a specialized maintenance tool for an installed
Content Pack that declares an image dataset or image-backed question set. Open
it from System Tools or an available image-study link, select the installed
dataset, and choose one of two modes.

### Clickable Regions

Use **Clickable Regions** to repair or calibrate an existing hotspot target.
Select the image and target, choose polygon or circle, then:

1. choose **Load Existing** to begin from its saved region;
2. place or adjust the region with a pointer or keyboard;
3. use **Undo Point** or **Clear Shape** when needed;
4. choose **Test Shape** and select points inside and outside the proposed
   target; and
5. choose **Save Region** and confirm the replacement.

The keyboard stage uses the same arrow-key and Enter/Space controls as hotspot
creation. Status messages announce placement, tests, saves, and errors without
relying only on color.

<!-- Screenshot: UM-19 — Image Study Editor Clickable Regions mode -->

### Image Prep

Use **Image Prep** to add non-destructive overlays to a study image. You can
cover an area with blur, white, or black; or add a light or dark text label with
a selected size. Use **Undo Last Edit**, **Clear Image Edits**, and **Save Image
Prep** to manage the current image's overlays.

Image Prep is not a general photo editor. It stores overlay instructions while
leaving the original source image unchanged. Likewise, saving a clickable region
changes the derived region data; it does not overwrite the source image.

## Troubleshoot matching and image content

### A pair will not publish

Check for a blank side, a repeated term, a repeated definition, or one value
mapped to conflicting answers. Correct the relationship rather than changing
capitalization merely to bypass a duplicate warning.

### OCR paired the wrong lines

Remove or correct the candidate in Review & Repair. Use your original source to
reconstruct ambiguous text because the temporary terminology image or rendered
page is removed after extraction completes.

### A hotspot will not save

Make sure a circle has a center and usable radius, or a polygon has at least
three valid points. Test the region before saving. If no clickable targets are
defined in the selected dataset, the editor makes only Image Prep available.

### An image cannot be opened or used

Confirm that it is a valid PNG, JPG/JPEG, or WebP within the upload limits. DLMS
does not serve active or executable content disguised as an image.
