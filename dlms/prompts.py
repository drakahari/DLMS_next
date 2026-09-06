"""Default AI prompt catalog for DLMS."""


DEFAULT_AI_FEEDBACK_PROMPT = """You are a technical tutor helping a student learn from mistakes.

        For each question:
        1. Explain why the correct answer is correct
        2. Explain why the selected answer is incorrect
        3. Give a short memory tip
        4. Keep explanations concise but clear
        5. Return your answer in clearly separated sections per question.

        ---

        {{questions}}
        """


DEFAULT_LAW_AI_PROMPT = r"""You are helping a first-year law student study a judicial opinion.

Case:
{{case_name}}

Course:
{{course}}

Please create a law-school study packet for this case.

Use only accurate information. Do not invent citations, quotations, facts, holdings, or procedural history. If you are uncertain, say so clearly.

Prefer public legal sources when available, such as official court sources, Cornell LII, Justia, Oyez, CourtListener, or other reliable public legal sources. If you cannot verify the case from a reliable source, clearly state that verification is needed. Include the source links used in the Sources Used section of the DLMS IMPORT BLOCK.

Create the following sections:

{{study_sections}}

Formatting requirements:
- Use clear headings.
- Keep explanations beginner-friendly but law-school appropriate.
- Avoid long block quotes.
- Do not invent citations, quotations, facts, holdings, or procedural history.
- Include a final warning outside the DLMS import block reminding the student to verify the case against the original opinion or an approved legal research source.

Return your response as one clearly marked, copyable fenced code block using plain text format.

The fenced code block must begin with this heading:

DLMS IMPORT BLOCK

Inside the DLMS IMPORT BLOCK:
- This entire block should be downloadable/copyable as a single plain-text block.
- Include a Sources Used section at the top of the block.
- In Sources Used, list the public legal sources used to verify the case, including source name and URL when available.
- Prefer official court sources, Cornell LII, Justia, Oyez, CourtListener, or other reliable public legal sources.
- Include only the requested study sections after Sources Used.
- Include only Sources Used and sections 1, 2, 2A, 3, and 4 when those sections were requested.
- Do not include extra commentary inside the DLMS IMPORT BLOCK.
- Do not include the verification warning inside the DLMS IMPORT BLOCK.
- Use clean plain-text headings so the block can be pasted into DLMS.

Do not provide a separate explanation before the fenced code block.
Do not provide a separate explanation after the fenced code block.

The response format should be:

```text
DLMS IMPORT BLOCK

Sources Used
- Source name: URL

1. Case Brief
...

2. Socratic Review
...

2A. Socratic Answer Key
...

3. IRAC Drill
...

4. Rule Flashcards
...
```
"""


DEFAULT_MEDICAL_CONTENT_PACK_PROMPT = r"""You are creating a self-contained DLMS Medical Study add-on content pack for educational study.

REQUESTED TOPIC
{{topic}}

CONTENT REQUEST
{{content_request}}

DIFFICULTY / DEPTH
{{difficulty}}

TARGET SIZE
{{size_guidance}}

NON-NEGOTIABLE ACCURACY AND SOURCE RULES
1. Research the requested topic before creating the pack. Do not rely on memory alone when authoritative sources can be checked.
2. Do not invent facts, definitions, citations, URLs, licenses, authors, image provenance, anatomical labels, or source claims.
3. If a fact or asset cannot be verified, OMIT it. Do not guess and do not fill gaps with plausible-sounding material.
4. Prefer authoritative educational and government sources with clear reuse rights, such as:
   - OpenStax material with an explicitly compatible open license
   - NIH, NLM, NCI, CDC, or other U.S. Government material when the individual asset is confirmed public domain or otherwise reusable
   - Wikimedia Commons ONLY when the exact file page clearly states a compatible license and provenance
   - Other reputable OER sources with explicit redistribution rights
5. For bundled images, use ONLY exact original files that are Public Domain, CC0, CC BY, or CC BY-SA, or another license that clearly permits redistribution in this pack.
6. Do NOT use copyrighted "all rights reserved" images, fair-use-only images, unclear-license images, stock imagery, watermarked imagery, or images copied from search-result thumbnails.
7. Do NOT use AI-generated or synthetic anatomy, histology, pathology, or microscopy images as authoritative medical study images.
8. Record image-level creator, source page, exact license, attribution, dimensions, and whether DLMS modified the image.
9. When an image license is share-alike, preserve all required share-alike obligations.
10. Do not claim physician review, faculty review, clinical validation, or peer review unless such review actually occurred and can be documented.
11. Label source-checked educational wording as "source-aligned" or "source-basis-verified", not "clinically validated".
12. This is foundational educational material, not clinical decision support, diagnosis, or treatment guidance.

STUDY QUALITY RULES
- Matching definitions must be concise enough to work well as matching choices.
- Avoid multiple definitions in the same dataset that are so similar that matching becomes arbitrary.
- Each term should have:
  - term
  - concise definition
  - category
  - a separate Study Mode explanation when a useful source-supported teaching point is available
  - verification metadata
- The explanation must add educational value rather than merely repeating the definition.
- Prefer an empty explanation over unsupported filler.
- Use standard medical terminology and preserve meaningful distinctions.
- If sources disagree, use the consensus/standard educational framing or omit the disputed item and document the issue.

DLMS PACK ARCHITECTURE
Create an independent Medical-domain Study Pack. Do not overwrite any existing installed Study Pack.

The root folder MUST be:
DLMS_Medical_<TOPIC_SLUG>/

The root manifest.json MUST include:
{
  "schema_version": 1,
  "id": "medical_<topic_slug>",
  "name": "DLMS Medical — <Readable Topic>",
  "version": "1.0.0",
  "requires_dlms": ">=3.0.0",
  "publisher": "User-generated DLMS study pack",
  "content_domain": "medical",
  "extends": "medical",
  "description": "...",
  "modules": ["terminology"],
  "datasets": [],
  "image_datasets": []
}

Use a lowercase unique id containing only letters, numbers, underscores, or hyphens.

MATCHING DATASET FORMAT
Each matching dataset is JSON and MUST use this structure:
{
  "schema_version": 1,
  "id": "unique_dataset_id",
  "title": "Readable title",
  "category": "Readable category",
  "type": "matching",
  "description": "What the student will study",
  "question_text": "Match each term with its best definition.",
  "source": {
    "organization": "...",
    "dataset": "...",
    "version": "...",
    "url": "https://...",
    "license": "...",
    "verification_status": "source-basis-verified"
  },
  "verification": {
    "status": "source-aligned",
    "verified_date": "YYYY-MM-DD",
    "method": "...",
    "sources": ["https://..."],
    "clinical_peer_reviewed": false
  },
  "terms": [
    {
      "term": "...",
      "definition": "...",
      "category": "...",
      "explanation": "...",
      "verification": {
        "status": "source-aligned",
        "verified_date": "YYYY-MM-DD",
        "reference_basis": "...",
        "source_urls": ["https://..."],
        "wording": "DLMS-authored concise wording; concept aligned to cited open reference",
        "clinical_peer_reviewed": false
      }
    }
  ]
}

IMAGE / HOTSPOT DATASET FORMAT
Only create an image dataset when you can legally bundle the exact source image in the output pack.

Each image dataset MUST use:
{
  "schema_version": 1,
  "id": "unique_image_dataset_id",
  "title": "Readable title",
  "category": "Anatomy, Histology, Cell Biology, etc.",
  "type": "hotspot",
  "description": "...",
  "source": {
    "organization": "...",
    "work": "...",
    "url": "exact source page URL",
    "license": "exact reusable license",
    "attribution": "required attribution"
  },
  "reference": {
    "organization": "...",
    "work": "...",
    "url": "https://...",
    "license": "..."
  },
  "images": [
    {
      "id": "stable_image_id",
      "file": "images/<category>/<filename>",
      "width": 0,
      "height": 0,
      "alt_text": "...",
      "source_url": "exact source page URL",
      "license": "...",
      "attribution": "...",
      "modified": false,
      "modification_note": "",
      "hotspots": [
        {
          "id": "stable_structure_id",
          "label": "Structure name",
          "prompt": "Identify the ...",
          "explanation": "Source-supported Study Mode teaching point.",
          "shape": {
            "type": "circle",
            "x": 0.5,
            "y": 0.5,
            "radius": 0.05
          },
          "calibration_status": "needs-dlms-editor-review",
          "verification": {
            "status": "source-aligned",
            "reference_basis": "...",
            "source_url": "https://...",
            "clinical_peer_reviewed": false
          }
        }
      ]
    }
  ]
}

IMPORTANT HOTSPOT RULE
Do NOT pretend guessed hotspot coordinates are final. If you cannot accurately calibrate against the exact bundled image, provide conservative starter regions and set:
"calibration_status": "needs-dlms-editor-review"
DLMS includes a Hotspot Calibration Editor for final circle/polygon calibration.

PACK FILE LAYOUT
At minimum:
DLMS_Medical_<TOPIC_SLUG>/
├── manifest.json
├── data/
│   ├── <matching datasets>.json
│   └── anatomy_or_images/
│       └── <image datasets>.json
├── images/
│   └── <exact legally reusable source image files>
├── LICENSES/
├── PROVENANCE.txt
├── SOURCE_POLICY.md
└── VALIDATION_REPORT.md

MANIFEST REGISTRATION
Every matching JSON file must be listed in manifest.json "datasets".
Every hotspot/image JSON file must be listed in manifest.json "image_datasets".
Do not declare an image dataset unless its referenced image file is actually included.

CRITICAL MANIFEST RULE:
"datasets" and "image_datasets" MUST be arrays of descriptor OBJECTS.
They MUST NOT be arrays of filename/path strings.

CORRECT:
"datasets": [
  {
    "id": "liver_histology_foundations",
    "title": "Liver Histology — Foundations",
    "type": "matching",
    "path": "data/liver_histology_foundations.json",
    "description": "..."
  }
]

WRONG — DO NOT DO THIS:
"datasets": [
  "data/liver_histology_foundations.json"
]

The same object-descriptor rule applies to "image_datasets".

VALIDATION REPORT
Before presenting the pack, verify and report:
- every JSON file parses
- every declared file exists
- no duplicate term within a dataset
- no duplicate definition within a dataset
- every term and definition is non-empty
- every dataset has source metadata
- every bundled image has exact provenance and a compatible redistribution license
- every image path resolves inside the pack
- every hotspot uses normalized coordinates from 0 to 1
- all uncertain hotspot geometry is explicitly marked for DLMS editor review
- clinical_peer_reviewed is false unless documented otherwise

DELIVERABLE
If your environment can create files:
1. Build the complete folder.
2. Include the exact legally reusable image files when image content was requested and verified.
3. ZIP the root folder.
4. Give the user ONE downloadable ZIP.
5. Also provide a concise source/license summary and validation result.

If your environment cannot create downloadable files:
- Output every required text file in clearly named fenced code blocks.
- Give exact source URLs for any omitted image assets.
- Clearly state that the pack is incomplete until those exact assets are legally obtained and placed at the declared paths.
- Do NOT claim the pack is installation-ready.

INSTALLATION TARGET
The completed add-on folder is placed directly under:
APP_DATA_DIR/content_packs/

Example:
content_packs/
└── DLMS_Medical_<TOPIC_SLUG>/

Medical Study Packs are optional and independently installable/removable. Do not assume a base Medical pack is present.

Do not nest the add-on folder inside another folder of the same name.

FINAL RESPONSE
Keep commentary short. Provide the finished pack first when possible, then the source/license summary, validation status, and any hotspot-calibration items that still require DLMS editor review.
"""


DEFAULT_STUDY_CONTENT_PACK_PROMPT = r"""You are creating a self-contained DLMS Study Pack for educational use.

SUBJECT / DOMAIN
{{domain}}

REQUESTED TOPIC
{{topic}}

CONTENT REQUEST
{{content_request}}

DIFFICULTY / DEPTH
{{difficulty}}

TARGET SIZE
{{size_guidance}}

IMAGE REQUEST
{{image_guidance}}

SOURCE AND ACCURACY RULES
1. Research the requested topic before creating the pack. Prefer authoritative primary documentation, reputable open educational resources, standards bodies, government sources, and official vendor/project documentation.
2. Do not invent facts, commands, quotations, citations, URLs, versions, licenses, authors, image provenance, labels, or source claims.
3. If a fact or asset cannot be verified, omit it rather than guessing.
4. Every dataset must include useful source metadata. Each Study Mode explanation must add supported teaching value rather than merely repeating the definition.
5. For redistributable images, use only exact files with a clearly compatible license such as Public Domain, CC0, CC BY, or CC BY-SA. Record creator, exact source page, exact license, attribution, dimensions, and modification status.
6. Never copy images from search-result thumbnails or from sources with unclear rights.
7. Real screenshots/photos must be legitimately redistributable. If a requested real image cannot be redistributed, omit it and document why.
8. Educational diagrams may be newly drawn when the domain permits it, but mark them clearly as "DLMS-created educational schematic" and never imply that a schematic is an authentic screenshot, specimen, photograph, or authoritative medical image.
9. For medical/anatomical/histology/pathology content, do NOT use synthetic or AI-generated images as authoritative identification material; use source-verified open images only.
10. The pack is study material, not professional, clinical, legal, financial, or operational decision support.

STUDY QUALITY RULES
- Add a question-level "concepts" field to every generated quiz question, matching dataset, and hotspot (or its image when shared by all of that image's hotspots). Use a small set of specific, reusable concepts per question, normally 1–3.
- Reuse identical spelling when questions assess the same skill. Prefer precise concepts such as "chmod", "octal-permissions", "symbolic-permissions", "special-permission-bits", "file-ownership", and "umask"; do not use broad metadata-only values such as "IT", "study", "question", "general", or "miscellaneous".
- "concepts" is the exact field name. Do not use "tags" in newly generated packs; DLMS accepts it only as a backwards-compatible alias.
- Matching terms must be unique within each dataset. Where matching records use IDs, every ID must also be unique within that dataset.
- Matching must use a one-to-one mapping: one term has exactly one answer, and one answer belongs to exactly one term.
- Definitions/answers must be concise, meaningfully distinct, and unambiguous when shuffled together in a matching round.
- Do not include duplicate or near-duplicate term/definition pairs, including superficial rewordings that test the same indistinguishable association.
- Repair every term, answer, pair, or ID collision before delivery. Do not claim that DLMS performs semantic-similarity enforcement; its installer performs deterministic normalized duplicate/conflict checks.
- Avoid padding a dataset with weak or duplicative terms.
- Each term should include a unique id when IDs are used, plus term, definition, category, explanation when source-supported, and verification/source metadata.
- For technical content, exact commands/configuration examples must be checked against the cited version/source.
- Image questions should identify visually meaningful regions; do not create arbitrary hotspots.

MULTI-IMAGE RULES
- A single image dataset may contain multiple images.
- Each image has its own hotspot list and source metadata.
- DLMS will turn hotspots across all images in the dataset into individual quiz questions, so multiple requested images are supported naturally.
- Use multiple datasets instead when the images represent substantially different subtopics.
- Do not combine unrelated diagrams into one giant composite image merely to reduce file count.

DLMS PACK ARCHITECTURE
Create an ADD-ON pack. Do not overwrite DLMS core or an existing pack.
Root folder: DLMS_Study_<TOPIC_SLUG>/

manifest.json MUST include descriptor OBJECTS, never path strings:
{
  "schema_version": 1,
  "id": "study_<topic_slug>",
  "name": "DLMS Study — <Readable Topic>",
  "version": "1.0.0",
  "requires_dlms": ">=3.0.0",
  "publisher": "User-generated DLMS study pack",
  "content_domain": "{{domain_slug}}",
  "description": "...",
  "datasets": [
    {"id":"dataset_id","title":"Readable title","type":"matching","path":"data/dataset.json","description":"..."}
  ],
  "image_datasets": [
    {"id":"image_dataset_id","title":"Readable title","type":"hotspot","path":"data/images/dataset.json","description":"..."}
  ],
  "quiz_datasets": [
    {"id":"mixed_dataset_id","title":"Readable title","type":"quiz","path":"data/questions/dataset.json","description":"..."}
  ]
}

MATCHING DATASET FORMAT
{
  "schema_version": 1,
  "id": "unique_dataset_id",
  "title": "Readable title",
  "category": "Readable category",
  "type": "matching",
  "description": "...",
  "question_text": "Match each item with its best answer.",
  "source": {"organization":"...","dataset":"...","version":"...","url":"https://...","license":"...","verification_status":"source-basis-verified"},
  "verification": {"status":"source-aligned","verified_date":"YYYY-MM-DD","method":"...","sources":["https://..."]},
  "terms": [
    {"id":"unique_record_id","term":"...","definition":"...","category":"...","explanation":"...","verification":{"status":"source-aligned","reference_basis":"...","source_urls":["https://..."]}}
  ]
}

For every matching dataset, verify that normalized IDs (where used), terms, definitions/answers, and complete pairs are unique; mappings are one-to-one; and every answer remains meaningfully distinguishable from every other answer after shuffling.

MIXED QUESTION / MULTIPLE-CHOICE FORMAT
Use a quiz_datasets descriptor with type "quiz" for choice, matching, and/or hotspot questions. For a DLMS multiple-choice question, use this exact single-select form:
{
  "type": "choice",
  "question": "Which permission mode lets the owner read and write?",
  "choices": [
    {"text":"600","is_correct":true},
    {"text":"644","is_correct":false},
    {"text":"640","is_correct":false},
    {"text":"755","is_correct":false}
  ],
  "explanation": "Mode 600 grants read and write permission to the owner only.",
  "concepts": ["octal-permissions"],
  "source": {"organization":"...","dataset":"...","version":"...","url":"https://...","license":"..."}
}

For every generated multiple-choice question:
- Use "type": "choice", a non-empty "question", and 2–26 choices. DLMS assigns A–Z labels in the supplied choice order; do not provide labels, "correct", "correct_answer", "correct_answers", or answer letters.
- Use an actual JSON boolean for every "is_correct" value. For AI-generated MCQs, exactly one choice must be true; all others must be false.
- Vary the supplied order of the correct choice across the question set so DLMS-assigned answer positions are not pathologically concentrated in A or any other position. Natural variation is sufficient; do not force a perfectly equal distribution.
- Do not invent factual answers. Mark an answer correct only when reliable source material supports it. If a valid supportable MCQ cannot be made, omit it instead of guessing.
- Distractors must be plausible but factually incorrect. Do not use duplicate answer text.
- Provide a concise explanation that supports the marked answer and does not contradict it. Do not fabricate distractor rationales, citations, URLs, or source claims.
- Include useful source metadata at the dataset level and at question level when the question uses a different source.

IMAGE / HOTSPOT DATASET FORMAT
{
  "schema_version": 1,
  "id": "unique_image_dataset_id",
  "title": "Readable title",
  "category": "Diagram / Hardware / Anatomy / Map / etc.",
  "type": "hotspot",
  "description": "...",
  "source": {"organization":"...","work":"...","url":"exact source page","license":"...","attribution":"..."},
  "images": [
    {
      "id":"stable_image_id",
      "file":"images/category/file.png",
      "width":0,"height":0,"alt_text":"...",
      "source_url":"...","license":"...","attribution":"...","modified":false,"modification_note":"",
      "edits": [],
      "hotspots":[
        {"id":"target_id","label":"Target name","prompt":"Identify ...","explanation":"...","shape":{"type":"circle","x":0.5,"y":0.5,"radius":0.05},"calibration_status":"needs-dlms-editor-review","verification":{"status":"source-aligned","reference_basis":"...","source_url":"https://..."}}
      ]
    }
  ]
}

IMAGE PREP
DLMS has an Image Study Editor that can non-destructively hide labels/text with blur/white/black masks, add simple text labels, and calibrate circle/polygon clickable regions. If exact hotspot geometry cannot be confidently calibrated, use conservative starter regions and set calibration_status to "needs-dlms-editor-review".

PACK FILE LAYOUT
DLMS_Study_<TOPIC_SLUG>/
├── manifest.json
├── data/
├── images/
├── LICENSES/
├── PROVENANCE.txt
├── SOURCE_POLICY.md
└── VALIDATION_REPORT.md

VALIDATION BEFORE DELIVERY
You MUST validate the finished pack after all files are created. Do not merely state that it should validate.
- every JSON file parses
- manifest.json uses schema_version 1
- datasets, image_datasets, and quiz_datasets (when used) contain descriptor OBJECTS, never path strings
- every descriptor has id, title, type, path, and the declared file exists
- every dataset file id matches its manifest descriptor id
- there are no duplicate normalized dataset IDs, image IDs, or matching record IDs where IDs are used
- matching terms are unique after Unicode and whitespace normalization; case-only term variants are reviewed intentionally because technical syntax may be case-sensitive
- matching definitions/answers are unique after case, Unicode, and whitespace normalization
- matching pairs form one-to-one mappings with no duplicate or near-duplicate pairs and remain semantically distinct and unambiguous when shuffled
- every matching collision discovered during review is repaired before delivery
- every term and definition is non-empty
- every choice question has a non-empty question, 2–26 distinct non-empty choices, real JSON boolean is_correct values, and exactly one correct choice
- correct-choice positions across each multiple-choice dataset have been reviewed for suspicious concentration; they need not be perfectly equal
- every dataset has source metadata
- every bundled image exists at its declared path
- every bundled image records exact provenance and redistribution/license metadata
- every hotspot uses valid normalized coordinates from 0 through 1
- uncertain hotspot geometry is marked needs-dlms-editor-review
- the ZIP contains exactly ONE top-level Study Pack folder
- the top-level Study Pack folder directly contains manifest.json
- no archive path is absolute, uses .. traversal, or escapes the Study Pack folder

REQUIRED MACHINE-READABLE VALIDATION FILE
Include PACK_VALIDATION.json at the root of the Study Pack. This is an AI self-check for the user and does NOT replace DLMS's independent installer validation.

Use this structure:
{
  "schema_version": 1,
  "validator": "AI self-validation",
  "pack_id": "<same id as manifest.json>",
  "validated_at": "YYYY-MM-DD",
  "overall_status": "PASS",
  "checks": [
    {"name":"Manifest schema","status":"PASS","detail":"schema_version 1"},
    {"name":"Dataset descriptors","status":"PASS","detail":"All descriptor entries are objects with id/title/type/path"},
    {"name":"Referenced files","status":"PASS","detail":"All declared dataset and image files exist"},
    {"name":"Matching uniqueness / IDs","status":"PASS","detail":"No normalized dataset/image/record ID collisions; matching terms and answers are unique, one-to-one, distinct, and unambiguous"},
    {"name":"Image licenses","status":"PASS","detail":"Every bundled image has verified redistribution/license metadata"},
    {"name":"JSON parse check","status":"PASS","detail":"Every JSON file parses successfully"},
    {"name":"Top-level folder","status":"PASS","detail":"Exactly one top-level DLMS Study Pack folder contains manifest.json"}
  ],
  "errors": [],
  "warnings": []
}

If ANY required check fails:
- set overall_status to "FAIL"
- identify the exact error in errors
- FIX the pack and rerun validation before delivery
- do not describe the ZIP as installation-ready while overall_status is FAIL

Also include the human-readable VALIDATION_REPORT.md, but PACK_VALIDATION.json is required for AI-generated packs.

FINAL RESPONSE VALIDATION SUMMARY
In the response that accompanies the ZIP, print this concise summary using the actual results from the completed pack:
PACK VALIDATION
Manifest schema: PASS
Dataset descriptors: PASS
Referenced files: PASS
Duplicate IDs: PASS
Image licenses: PASS
JSON parse check: PASS
Top-level folder: PASS

Do not print PASS for a check you did not actually perform.

DELIVERABLE
If file creation is available, build the complete folder, include the exact permitted assets, include PACK_VALIDATION.json, ZIP the single root folder, and provide ONE downloadable ZIP plus the concise validation/source summary. If file creation is unavailable, do not claim the result is installation-ready.

INSTALLATION
The ZIP must contain exactly one root folder named DLMS_Study_<TOPIC_SLUG>/ with manifest.json directly inside it. DLMS can then validate and install that ZIP from Content Packs. Never nest the same root folder inside itself.
"""


DEFAULT_MEDICAL_STUDY_PACK_AI_ADDENDUM = r"""MEDICAL-SPECIFIC SAFETY AND SOURCE REQUIREMENTS
- Treat this as educational medical study content only.
- Prefer authoritative medical/OER/government sources and exact source-verified terminology.
- Do not invent clinical facts, diagnostic claims, citations, licenses, structures, or image provenance.
- Do not use synthetic or AI-generated anatomy, histology, pathology, radiology, or microscopy images as authoritative identification material.
- Use only exact legally redistributable medical images with source/license/creator attribution documented at image level.
- Keep concise matching definitions separate from richer Study Mode explanations.
- Mark uncertain image hotspot geometry for DLMS Image Study Editor review rather than pretending it is calibrated."""

