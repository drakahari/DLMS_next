# DLMS Study/Content Pack Framework

## What changed

DLMS now scans:

`APP_DATA_DIR/content_packs/`

for optional packs. Each pack is a directory containing a `manifest.json`.

The new `/content-packs` page displays the exact folder used by the running
DLMS installation.

Valid installed packs are available through **Study Packs**. Domain-specific
content also appears in the appropriate built-in study workspace, such as
Medical Study or IT Study.

Matching, mixed choice-question, and image/hotspot datasets create normal DLMS
quizzes using the existing quiz engine, database/history, and Quiz Library.

## Installing a Study Pack ZIP

1. Open **Content Packs** in DLMS.
2. Choose a DLMS Study Pack ZIP and select **Validate ZIP**.
3. Review the independent validation report. Blocking errors must be corrected;
   warning-only packs require explicit confirmation.
4. Install the validated pack. DLMS verifies that the installed pack is
   discoverable before reporting success.

The AI Study Pack Builder uses this same validation and installation pipeline.
Manual folder installation remains available for trusted, locally prepared
packs: place one complete pack directory directly under the displayed Content
Pack Folder, then reload DLMS.

The directory should look like:

```
content_packs/
└── DLMS_Medical_Pack/
    ├── manifest.json
    ├── data/
    │   └── foundations.json
    ├── images/
    │   ├── anatomy/
    │   ├── histology/
    │   └── pathology/
    ├── LICENSES/
    └── PROVENANCE.txt
```

## Pack schema v1

The pack manifest declares:
- id/name/version
- compatible DLMS version
- modules
- datasets and their relative paths

Dataset files are JSON. The framework rejects path traversal and skips malformed
packs instead of preventing DLMS from starting.

## Current limitations

- No remote pack download/update service.
- DLMS validates structure, declared sources, provenance, and supported metadata,
  but it cannot independently prove every factual claim in imported study content.


## DLMS 3.0 generic Study Packs

DLMS can now use matching and image/hotspot datasets from any installed content pack through `/study-packs`. The AI Study Pack Builder generates schema-controlled prompts for arbitrary subjects, and the Image Study Editor supports non-destructive mask/text overlays plus hotspot calibration. Multiple images are supported in one image dataset; each image retains its own targets and source metadata.
