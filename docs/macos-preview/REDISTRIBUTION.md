# DLMS Desktop Mac preview: third-party software

The application code is MIT. Retain LICENSE and
desktop_assets/ICON_PROVENANCE.md. Third-party terms remain applicable. This is
a technical correspondence record, not legal certification or a claim that
vendor binaries can be reproduced bit for bit.

Deliver the DMG with **all** SOURCE_MATERIALS companion archives and notices.
EXACT_INPUTS.json binds the actual Apple Silicon wheels and native producers;
MANIFEST.json binds the notice kit. Do not substitute Linux ELF/Ubuntu/AppImage
or Windows PE/conda/Microsoft binary mappings for this Mac payload.

Qt/PySide/Shiboken 6.11.2 use the available LGPL route for retained runtime
modules. Seven unused GPL/commercial Qt families are excluded using Mac
framework/dylib/binding/QML names, with retained load-command dependency checks.
Quick/QML/WebEngine support remains. The complete official Qt/PySide source
companions, Qt license texts and Chromium third-party notices are supplied.
Source/notice supersets do not imply that every named upstream module is shipped.
The wheel also supplies standalone shared FFmpeg7.1.5 libraries under LGPL2.1 or
later. Their separate official source archive and actual arm64 configure options
are indexed in the Mac wheel-native companion; Chromium's FFmpeg subtree is not
substituted for those libraries. Retain its license text and source/download
reference wherever the binary preview is offered.

Homebrew Python3.14.7, Tesseract5.5.3, Leptonica1.87.0 and their native closure
have their own exact formula-pinned archives, sanitized producer receipts,
formula texts, licenses and build patches in the Mac native source companion.
The English traineddata input is supplied byte for byte. System macOS libraries
are prerequisites, not bundled software. Actual libarchive producer features
disable LZO/nettle; the Windows static-LZO/GPL mapping does not apply here.
The native index distinguishes its Python input superset from the final bundle.

Mac-wheel-native Pillow and PDFium components retain their exact wheel notices,
native build licenses and producer metadata/SBOMs. Permissive components keep
their individual terms; no universal corresponding-source obligation is invented.
Pillow's SBOM may describe optional components absent from this actual wheel.
PyInstaller retains its bootloader exception. Build tools are distinguished from
the runtime. Matching Python package source companions are also supplied.

There is no restriction on modification, compatible library replacement or
reverse engineering to debug those modifications. See BUILD_AND_REPLACEMENT.md.
No publisher private key is required to rebuild or ad hoc sign a separate copy.
This preview is ad hoc signed only, without Developer ID or notarization.
Checksums bind files but do not independently establish publisher identity.

Preparing this kit does not authorize a merge, release tag, upload or publication.

Artwork update: current source restores the owner-identified AI-generated round blue
icon. See desktop_assets/ICON_PROVENANCE.md for established provenance, owner redistribution permission and unknown
generation details; the former geometric badge MIT statement must not be applied
to the restored image. Existing published artifacts and their notices are unchanged.
