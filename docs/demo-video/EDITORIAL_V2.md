# V2 editorial audit and pronunciation review

This targeted revision follows the first complete Heart viewing. [NARRATION.md](NARRATION.md)
owns the revised text, sequence and timing. The existing 6:37.200 MP4, source WAVs,
SRT and audition sets are V1 reference assets and were preserved. This pass does
not record or render V2.

## What the current product supports

| Capability | Implementation and current UI | Overview decision / limits |
| --- | --- | --- |
| Structured text questions | Build Quiz → text upload; Paste questions → cleanup, parsing preview, publish. [Authoring routes](../../dlms/routes/quiz/authoring.py), [upload hub](../../templates/quiz/upload.html), [creation guide](../user-manual/04-creating-and-importing-content.md). | 006 explains reuse instead of manual re-entry. A formatted TXT file is supported; arbitrary prose is not automatically made into questions. Paste cleanup is a separate path. |
| CSV terminology | Import matching pairs reads UTF-8 term/definition columns (also supported left/right aliases), validates pairs and publishes matching practice. [Authoring routes](../../dlms/routes/quiz/authoring.py), `matching_bank_import`. | 006 now names CSV and its useful outcome. Do not imply a general spreadsheet-to-choice-question converter. |
| Selectable-text PDF | PDF & Image Import extracts pages, suppresses repeated margins, parses question banks or glossaries, and offers recovery/review when structure is uncertain. [PDF routes](../../dlms/routes/pdf_import.py), `pdf_import_analyze`. | 007 separates direct extraction from OCR. It describes available processing; the pictured form has not run. No arbitrary textbook/chapter interpretation. |
| Saved PDF banks → practice | Reviewed Question Banks generate quizzes; reviewed terminology can generate matching or multiple-choice practice. [PDF routes](../../dlms/routes/pdf_import.py), `pdf_question_bank_generate`, `pdf_terminology_bank_generate`, `_pdf_terms_matching_questions`, `_pdf_terms_mc_questions`. | 007 names the reusable outcome. Matching needs at least two complete terms; multiple choice needs four active terms. No invented distractors from unrelated material are promised. |
| Scanned question PDFs | Local OCR can process explicitly selected eligible low-text question-bank pages; direct text and OCR are distinct extraction paths. [PDF routes](../../dlms/routes/pdf_import.py), `pdf_import_ocr_start`, [PDF/OCR guide](../user-manual/10-pdf-smart-pdf-and-ocr.md). | 008 says selected scanned question-bank pages, not unrestricted document understanding. OCR availability depends on the local runtime. |
| Question screenshots/images | Local OCR extracts draft questions from supported PNG/JPEG/WebP sources. Uploaded order is retained. Review & Repair is required; a highlighted answer is not trusted as proof. [PDF routes](../../dlms/routes/pdf_import.py), screenshot handlers, [import UI](../../templates/pdf_import/index.html). | 008 establishes draft status; 009–010 demonstrate verification and uncertainty. No claim that OCR understands arbitrary diagrams or infers missing correct answers. |
| OCR terminology | Terminology images or one scanned PDF can yield conservative term/definition candidates; ambiguous material remains available for repair. [Matching OCR routes](../../dlms/routes/pdf_import.py), [import UI](../../templates/pdf_import/index.html). | The lower half of existing 008 already shows this capability. Narration now includes terminology pairs and scanned glossaries. |
| Review & Repair | Editable question/term drafts, warnings, answer confirmation and exclusion before saving/publishing. [PDF routes](../../dlms/routes/pdf_import.py), [matching OCR routes](../../dlms/routes/pdf_import.py). | 009–010 retain the trust step. 009 is a separate seeded example, not the extraction result of the selected file in 008. 011 is another already published quiz. |
| Images as study content | Build from image(s) / Image Study Editor can create image-supported choice or matching questions and editable hotspot regions. [Study Pack routes](../../dlms/routes/study_packs.py), `image_quiz_builder`, `image_quiz_builder_save`, [image-content guide](../user-manual/11-matching-terminology-and-image-based-content.md). | Distinct from extracting text with OCR. Reusable image activities are mentioned with packs in 028. Detailed authoring deserves its own video; the bottom of 006 only partly shows the image-builder entry. |
| External structured content | External AI Quiz Builder makes a prompt, accepts manually returned structured JSON, validates/reviews, then publishes. [External AI guide](../user-manual/12-external-ai-workflows.md), [AI routes](../../dlms/routes/external_ai.py). | 033 stays in the main cut. Optional provider-neutral manual handoff, no required direct provider API, no background transmission. This is not the local PDF parser. |
| Portable quiz bundles | Validated import/preview and export of eligible source quizzes with supported media. [Bundle routes](../../dlms/routes/quiz/bundles.py), [bundle service](../../dlms/services/portable_quiz_bundles.py). | 028 retains ordinary content portability, excluding learning history. These bundles are distinct from Study Pack packages and full workspace backups. |
| Study Packs / Content Packs | Study Packs browses usable installed datasets and creates matching, image/hotspot, or prepared-question quizzes. Content Packs validates/imports, inspects, exports and removes the packages supplying that material. [Study Pack routes](../../dlms/routes/study_packs.py), [Content Pack routes](../../dlms/routes/content_packs.py), [pack guide](../user-manual/13-study-packs-and-content-packs.md). | Both terms are current user-facing workspace names, not competing old/new names. Sources remain installed when a playable quiz is created. 028 explains that reusable-source benefit. Supported pack ZIP structure is required; an arbitrary ZIP is not accepted. |
| Physical printed flash cards | Anki Tools → Custom Deck & Printable Cards → select questions/misses → Avery 5388, long/short-edge duplex option → Open Avery Print Layout → browser Print Cards. [Anki routes](../../dlms/routes/anki.py), `anki_printable_flashcards`, [selector](../../templates/anki/custom.html), [print layout](../../templates/anki/printable.html). | 032 introduces physical output separately from 031's Anki deck export. Text fronts/backs, three 3×5-inch cards per US Letter sheet, alternating front/back pages. Browser/printer settings and a test sheet are still needed. No embedded hotspot interaction, automatic pair expansion, or direct printer control is implied. |

## Capture and pacing decisions

All six contact sheets were inspected, covering all 36 final frames. Full-size
inspection of 006, 008, 028 and 032 confirmed the key existing visual anchors.
The frame-by-frame/group redundancy table in NARRATION.md still covers the
entire set. No capture defect or changed UI requires recapturing an asset.

- **006–010:** Existing Build Quiz, PDF form, both OCR panels, review overview
  and unresolved-answer detail support the stronger source → extraction → review
  sequence. The OCR forms clearly distinguish questions from terminology.
- **028:** The visible “Not a Study Pack?” callout and both navigation entries
  support a brief distinction between bundles and reusable packs. The catalog
  itself is not shown. Keep the full frame static; do not fabricate a catalog
  interaction or installed-pack example.
- **031–032:** Existing export panels, card selection and “Custom Deck & Printable
  Cards” label support awareness of the shared output workflow. The print layout
  is below the captured viewport and is not shown. No pan can reveal uncaptured
  pixels. A dedicated print-layout capture would be useful for a tutorial, but
  adds little to this short availability statement.
- **014–016:** Keep the evidence → trend → model progression but shorten each
  explanation. Also tighten 005, 019, 024 and 027 to fund import/output coverage.
- **017 / 035:** Still CUT. **020:** still long-version only. **033:** still KEEP.
  No new frames, cuts, replacements or reordering; main 33, long 34.

Dedicated pack and printing screenshots are therefore **not required for V2**.
This is an overview-level coverage decision, not a claim that the current images
demonstrate every step. Focused follow-ups should show the catalog, print layout
and real synthetic import/review results directly.

## Timing method

V2 has **790 whitespace-counted narration words** and **390 seconds** of minimum
scene targets. Reference rates of 138–148 WPM yield 331.6 seconds (5:32); the
135–150 WPM envelope is 316.0–351.1 seconds. These written-word estimates
undercount the time for acronym letter names and longer pauses.

For a voice-specific planning estimate, scale each V1 scene's measured Heart
duration by its revised/original speech-token count, expanding DLMS, AI, OCR,
API, CSV and PDF letter names consistently (PDFs counts as three tokens).
Feed those **estimates**, not old recordings, through the existing timeline
calculation: max(target, estimated speech + 0.6-second tail + incoming fade),
rounded up to 30-fps frames. This gives **358.3 seconds speech, 403.6 seconds
complete video (about 6:44)**. Allow 6:30–7:00 until V2 recordings exist.
The phoneme changes may affect cadence, so these are not final subtitle timings.
The generated local audit inputs are under `build/demo-video/v2-editorial/`.

## Pronunciation correction

V1 metadata for 013 and 033 records literal `A I` in both source and synthesis
text. The old transform only matched unspaced `AI` and replaced it with spaces;
it never enforced the English letter names. This explains the lack of a
deterministic pronunciation instruction, though tooling cannot establish exactly
how the listener heard the model's output. Anki had no override at all.

The optional Kokoro adapter now supplies Misaki phoneme overrides, which bypass
ordinary spelling interpretation for these terms. This is supported by the
[Misaki English usage example](https://github.com/hexgrad/misaki#english-usage)
and [phoneme inventory](https://github.com/hexgrad/misaki/blob/main/EN_PHONES.md).
The upstream [Kokoro API implementation](https://github.com/hangry-labs/kokoroTTS/blob/main/kokorotts/app.py)
passes synthesis text into the pipeline. No model/library dependency is added
to DLMS. A deployed server must retain that compatible text pipeline.

| Written term | Synthesis-only override | Intended sound |
| --- | --- | --- |
| DLMS | `[DLMS](/dˈi ˈɛl ˈɛm ˈɛs/)` | dee el em ess |
| AI | `[AI](/ˈA ˈI/)` | ay eye |
| OCR | `[OCR](/ˈO sˈi ˈɑɹ/)` | oh see ar |
| API | `[API](/ˈA pˈi ˈI/)` | ay pee eye |
| Anki | `[Anki](/ˈɑnki/)` | AHN-kee |

The same rule handles compact and legacy space-separated acronyms. Matching is
case-sensitive and bounded by non-word characters, so RAID, RAPID, APIs, Anking,
and other unrelated words are unchanged. Existing overrides survive a second
pass unchanged. Normal spelling stays in narration, text exports and subtitles.
PDF/CSV remain normal synthesis spelling; check them by ear rather than assuming
a failure. FFmpeg, SQLite, JSON, ZIP and LAN do not occur in the main spoken text.

Prepare the exact tiny-test payload without a server or any audio generation:

```sh
python tools/generate_demo_narration.py --pronunciation-test --voice af_heart --dry-run
```

When local Kokoro is running, generate **only this isolated short test**:

```sh
python tools/generate_demo_narration.py --pronunciation-test --voice af_heart
```

Output: `build/demo-video/pronunciation-test/pronunciation.wav`, with the usual
generation metadata, WAV validation and overwrite protection. Use `--force`
only to replace this test intentionally. It does not read/export production
scenes, modify auditions, or render video. Listen for distinct letters and
AHN-kee without an unnatural pause. If markup is spoken aloud, the deployed
pipeline is incompatible; do not generate a full set with it.

The local service was not reachable during this pass. The phoneme mapping and
request logic are tested offline; the new sound still needs human confirmation.
First listening checkpoints in V2: **001 DLMS**, **006 CSV**, **007 PDFs/DLMS**,
**008 OCR**, **013 Anki/AI**, **031 Anki**, **033 AI/API**.

## Future focused videos

1. **Importing PDFs, scans, images and CSV:** one synthetic source through each
   applicable path, showing what becomes a bank, matching quiz or image activity.
2. **OCR and Review & Repair:** ambiguous extraction, answer confirmation,
   conservative terminology pairing, and publish versus exclude decisions.
3. **Learning Intelligence:** distinguish evidence, accuracy, trends, mastery
   and provisional conclusions without treating one score as mastery.
4. **Generated Practice:** source provenance, due questions, Adaptive Study and
   the explicit Finish Review / retained-completion lifecycle.
5. **Study Packs and Content Packs:** validate/install a synthetic package,
   generate different practice sessions, then export the reusable sources.
6. **Anki and printable physical flash cards:** use the same selection for an
   Anki deck and Avery front/back layout, including a duplex test sheet.
7. **Building/importing quizzes:** formatted TXT, paste cleanup, CSV terminology,
   manual authoring, image-supported content and optional external JSON handoff.
8. **Learning Scope:** focus current recommendations while retaining older
   content, evidence and schedules; distinguish Hide from exclusion.

## V2 handoff validation

- **98 focused tests passed**, one expensive render smoke test deselected:
  `test_demo_narration.py`, `test_demo_video_build.py`, `test_demo_video_capture.py`
  and `test_manual_screenshot_capture.py`. HTTP is mocked; no real speech is used.
- Tests cover exact source/export mapping, main/long and audition counts,
  phoneme payloads, legacy spaced acronyms, word boundaries, idempotence,
  isolated pronunciation-test output, dry-run behavior and overwrite refusal.
- The current `<br>` narration formatting exposed a pre-existing builder parse
  failure. The field parser now ignores a trailing HTML line break; regression
  cases cover plain fields and `<br>`, `<br/>`, `<br />` without weakening
  editorial-status, image, timing or word-count validation.
- Production setup validation passes: all 36 capture hashes/dimensions, main 33,
  long 34, 790 main words, 390-second minimum main timeline, exact plain-text
  agreement. No V1 WAVs were used to claim a V2 recording validation.
- A baseline hash comparison preserves **116 existing screenshot, WAV, MP4 and
  production audio-metadata files**, including every audition and the V1 build.
- `git diff --check` passes. Changes are confined to demo-video documentation,
  optional narration/build tooling and focused tests. No production application,
  version or release files changed; nothing was committed or pushed.
