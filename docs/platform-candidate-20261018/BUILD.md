# Reproduce the pinned candidate

Build source is exactly `4b50e2b3fb39dd478d355bf785b319805579076c`, runtime `bfdffb720f743e9d720cd07292ec7e1ec325e059`. Only the four approved quality reports differ. Use `git archive` of the full source commit or the matching application-source companion; no private history/build cache is required as source input. The handoff branch adds later documentation and fixtures only and is not a moving build baseline.

Use [the existing public Ubuntu build recipe](../linux-desktop-preview-build.md) and its explicit source/native/Qt/Python/AppImage companions. For this candidate **omit the historical Preview1 overlay step**: it is already in the pinned source. Choose `linux-330-safety-20261018` instead of the example release name and pass the full 40-character source commit above. Keep all lock files unchanged. Verify companions against this folder's SHA256SUMS/SOURCE_MATERIALS.json; use the corrected BUILD_AND_REPLACEMENT.md in this folder rather than old producer instructions.

Actual producer: rootless network-disabled Ubuntu image `sha256:0cbc551e1b75bcd723ebd97289691eac0cf5ee8bd858f129c53cc912ec01ed27`, previously qualified pinned Python/Qt/native environment. It already exists locally; the public Containerfile/base digest/native inputs describe reconstruction, not a promise that this producer image is downloadable. The cached image's PDFium 5.13.0 was replaced **only** with the existing active-lock 5.14.0 wheel, SHA `11f281613fa22313d9c7ab89947665e84eccf8ebe40e1198a84a88352305648d`; no dependency pin changed. Actual resolved inventory and pip check/release preflight passed.

Inside a fresh `/work` populated only with the exact source and verified OCR/notices/distribution inputs, run:

```sh
set -eu
cd /work
python -m pip check
python -B tools/check_release_dependencies.py
export DLMS_DESKTOP_PREVIEW_SUPPORT='Private Linux safety candidate; Fedora qualification recorded separately; native Omarchy/Ubuntu/Windows/Mac pending.'
sh package_linux/freeze_ubuntu.sh linux-330-safety-20261018 4b50e2b3fb39dd478d355bf785b319805579076c
```

The normal entry point,184 modules/247 assets and native ABI floor are verified by freeze_ubuntu.sh. Keep failed outputs. The first package's reused notice instructions still referenced the historical source/overlay; independent review required correcting only REDISTRIBUTION.md and BUILD_AND_REPLACEMENT.md and their manifest. Final payload executable/code/assets remained identical. A new final distribution was assembled/finalized without overwriting the first output; final hashes are in PROVENANCE.json. No repeated freezer or dependency rebuild was needed.

Generate both formats from the **same final payload**, using a fresh AppDir/output and verified tool/runtime files from package_appimage/inputs.json. The existing public recipe supplies the exact tar and `python -m package_appimage.build` commands. Final filenames are those in SHA256SUMS. AppImage runtime commit 8f39b89 and appimagetool 854e19e remain unchanged; no auto-update metadata/signing or host desktop integration. FUSE launch is separate from extraction fallback. Use glibc2.39-compatible host, working graphics/Fontconfig/GBM and sandbox prerequisites. Native Ubuntu/Omarchy acceptance remains pending.

Current inventories bind actual bytes, not a bit-reproducibility promise for different compilers/contemporary apt mirrors. Dependency source companions retain their old verified names because they are unchanged. New application source and notices are separately named. Keep notices and corresponding sources available with any onward conveyance, preserve LGPL replacement/relinking rights and do not mistake checksums for authenticated publisher signatures.
