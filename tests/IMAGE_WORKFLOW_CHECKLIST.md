# DLMS Image Workflow Regression Checklist

Use this checklist before a release candidate when image-related code changes. The automated suite covers schema/loading/snapshot behavior; these checks cover browser rendering and interaction.

## Automated core checks

Run inside the DLMS virtual environment:

```bash
python -m unittest tests.test_content_pack_validation tests.test_image_workflow
```

Expected result: all tests pass.

## Manual browser checks

- [ ] PNG image renders in Study Mode and Exam Mode.
- [ ] JPEG image renders in Study Mode and Exam Mode.
- [ ] WEBP image renders in Study Mode and Exam Mode.
- [ ] Transparent PNG remains visually correct against the DLMS background.
- [ ] Portrait image scales without clipping or horizontal overflow.
- [ ] Very wide diagram scales without clipping or horizontal overflow.
- [ ] Large image remains usable and does not distort the quiz layout.
- [ ] Multiple images in one dataset produce questions for the correct image.
- [ ] Circle hotspot accepts clicks inside the target and rejects clear misses.
- [ ] Polygon hotspot accepts clicks inside the polygon and rejects clear misses.
- [ ] Hotspot near an image edge remains clickable and visible.
- [ ] Non-destructive image edits (blur/white/black mask/text label) render in the quiz.
- [ ] Choice question with an image displays the expected image.
- [ ] Multi-select question with an image displays the expected image.
- [ ] Matching question with an image displays the expected image.
- [ ] Attempt Review displays the image and missed hotspot response correctly.
- [ ] Generated quiz image still works after deleting its source Study Pack.
- [ ] Exported Study Pack retains its image files and image dataset references.
- [ ] Re-imported exported Study Pack validates successfully when its pack ID is not already installed.

## Failure rule

Any failed item should be treated as an RC blocker when the failure affects data integrity, pack portability, quiz playability, or saved-attempt review.
