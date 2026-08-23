# DLMS Content Pack Framework v1

## What changed

DLMS now scans:

`APP_DATA_DIR/content_packs/`

for optional packs. Each pack is a directory containing a `manifest.json`.

The new `/content-packs` page displays the exact folder used by the running
DLMS installation.

When a valid pack with id `medical` is installed:

- **Medical Study** appears on the dashboard/navigation.
- `/medical` lists datasets declared by the pack.
- Matching datasets can create normal DLMS practice quizzes using the existing
  matching engine, random round selection, direction control, database/history,
  and Quiz Library.

## Manual installation for v1

1. Open **Content Packs** in DLMS.
2. Note the displayed Content Pack Folder.
3. Extract the `DLMS_Medical_Pack` folder into that folder.
4. Reload DLMS. No application rebuild is required for data-only pack updates.

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

## Intentional v1 limitations

- No in-app ZIP installer yet.
- No remote pack download/update service.
- Medical v0.1.0 contains terminology only; image directories are placeholders.
- Generated medical practice quizzes are normal DLMS quizzes and therefore
  appear in the Quiz Library/history.


## DLMS 3.0 generic Study Packs

DLMS can now use matching and image/hotspot datasets from any installed content pack through `/study-packs`. The AI Study Pack Builder generates schema-controlled prompts for arbitrary subjects, and the Image Study Editor supports non-destructive mask/text overlays plus hotspot calibration. Multiple images are supported in one image dataset; each image retains its own targets and source metadata.
