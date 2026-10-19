# DLMS Desktop Windows preview: third-party software

DLMS application/Desktop code is MIT; retain LICENSE
and ICON_PROVENANCE.md. Third-party software keeps its own terms. This is a
technical redistribution record, not legal certification. The exact Windows
input mapping is EXACT_INPUTS.json; SOURCE_MATERIALS.json binds companion files.

Qt/PySide/Shiboken 6.11.2 use the available LGPL route for retained runtime modules.
The seven unused GPL/commercial Qt families from the Linux review are excluded
with Windows DLL/QML names and retained PE-import checks. Qt Widgets/native
controls and fallback WebEngine support remain bundled; WebView2 renders the
Windows UI. Keep all Qt/PySide/Chromium licenses and corresponding source,
including optional upstream notices as a source superset. Do not infer that all
upstream modules named in notices are executable inputs. Official Qt/PySide
sources and Chromium patch-level metadata are reused from the verified Linux
preview, not Ubuntu binary inventories or its AppImage runtime.

Windows Tesseract5.5.3 is an independently usable command-line program invoked
through files/TSV, not an OCR library loaded into DLMS. Its conda-forge closure
includes Leptonica1.87.0 and the GPL-bearing libarchive build with static LZO2.10.
Convey this linked OCR combination under the GPLv3-compatible route, preserving
the Apache/BSD/LGPL/GPL component texts, producer recipes, patches and complete
indexed source inputs. This does not relicense the MIT application. The UTF-8
Tesseract manifest modification and original executable digest are disclosed in
the bundled OCR notices; no privilege/security manifest setting is removed.

The source kit uses the actual Windows producer archives/build strings. Its
OpenSSL3.6.5, ICU78.3, libxml2-16 2.15.4 and other Windows native versions differ
from Linux. No Ubuntu copyright/source mapping is substituted. The exact
English trained-data producer input is supplied. Recipe-local source files and
static LZO source are included even when no separate LZO DLL is shipped.

CPython 3.14.7 uses its PSF/third-party notices. Matching Windows PCbuild source
and official OpenSSL3.5.7, libffi3.4.4 and SQLite3.50.4.0 external tags are supplied;
these are distinct from the OCR libraries. Wheel-specific Pillow12.3.0 and
pypdfium2 5.14.0/PDFium notices are collected from the actual Windows wheels,
including comprehensive native BUILD_LICENSES. Sources/notices are technical
correspondence, not a claim of reproducible vendor wheels or an invented upstream
binary-core hash. Windows Pillow's optional shaping stack differs from Linux;
its runtime versions are recorded in the validation/build receipts. Permissive
native components retain their individual terms rather than an invented universal
corresponding-source obligation.

Microsoft WebView2 SDK1.0.4258.31 loader/.NET DLLs retain their included Microsoft
SDK license. System WebView2 Evergreen, .NET Framework and Windows itself are
prerequisites, not bundled software. Evergreen is independently serviced. The
Windows OCR UCRT/VC runtime redistributable DLLs retain their exact vendor license
texts/producer mappings. The preview's root OpenSSL3.6.5 and UCRT DLLs also come
directly from these same pinned Windows producer archives, never Git's PATH or
the build host's System32; CPython's distinct OpenSSL DLLs remain NuGet-input-bound.
The Microsoft runtime DLLs are
not represented as open-source components.
PyInstaller retains its bootloader exception. Build tools are distinguished from
runtime payload; no Inno compiler is installed with the application.

No additional restriction on modification, compatible library replacement or
reverse engineering to debug those modifications is imposed. Deliver **all**
SOURCE_MATERIALS.json companions alongside an approved binary release. Preparing
them locally is not public delivery. Keep LGPL/GPL texts and rebuild/replacement
instructions. The binary is unsigned; checksums do not establish publisher identity.

Artwork update: current source restores the owner-identified AI-generated round blue
icon. See desktop_assets/ICON_PROVENANCE.md for established provenance, owner redistribution permission and unknown
generation details; the former geometric badge MIT statement must not be applied
to the restored image. Existing published artifacts and their notices are unchanged.
