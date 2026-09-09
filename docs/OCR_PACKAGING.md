# DLMS OCR runtime packaging contract

DLMS-119 uses Tesseract 5 through the bounded service in `dlms/services/ocr.py`.
Question-layout inference and OCR product routes are intentionally outside that
service.

Source/development mode feature-detects a configured Tesseract executable and
English tessdata, with `PATH` discovery allowed as a convenience. A frozen DLMS
runtime never falls back to `PATH`: it accepts OCR only when the executable and
`eng.traineddata` are bundled below `ocr/tesseract/` in the frozen resource root.

Native builders prepare a platform-specific directory and set
`DLMS_TESSERACT_BUNDLE_ROOT`. Its required layout is:

```text
bin/tesseract[.exe]
bin/[platform-native dependent libraries, when not resolved by the build host]
tessdata/eng.traineddata
tessdata/configs/tsv
licenses/tesseract-LICENSE.txt
licenses/tessdata-LICENSE.txt
licenses/leptonica-LICENSE.txt
```

`DLMS.spec` includes this runtime when the variable is set. The stricter
`DLMS-OCR-Probe.spec` requires it and produces a small frozen executable that
performs OCR against the repository-created probe fixture. Each release target
must supply and validate its own native executable, dependent libraries,
language data, and licenses; validation on one operating system does not prove
the other targets.

Smart PDF question banks now save list-capable `correct_answers` values. At
load/conversion boundaries, legacy scalar `correct` values remain supported and
are normalized in memory without rewriting existing user files.
