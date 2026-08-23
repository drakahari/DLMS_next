# DLMS Medical v0.5.0 — Heart Anatomy Hotspots

## Core files to replace

- `app.py`
- `static/script.js`
- `static/style.css`

## Medical Pack

Replace the installed `DLMS_Medical_Pack` folder with the v0.5.0 pack.

## What v0.5 adds

- safely serves image assets from installed content packs
- discovers `image_datasets` independently of terminology datasets
- Medical Study shows an Anatomy image-practice card
- creates hotspot quizzes using the normal DLMS quiz player shell
- Study Mode:
  - click a structure
  - immediate correct/incorrect feedback
  - wrong answers show the verified target location
  - explanation and source-check basis are shown
- Exam Mode:
  - records image clicks without revealing correctness
  - scores the click against normalized hotspot geometry
- image remains bundled inside the content pack; internet access is not required
  after installation

## First dataset

Heart Anatomy — External View

7 structures on an unlabeled NIAID/NIH BioArt image.

The first release intentionally uses only structures that are visually
distinguishable on this external view.
