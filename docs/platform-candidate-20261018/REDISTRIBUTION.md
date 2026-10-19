# DLMS Desktop Linux preview: third-party software

Shared runtime baseline: bfdffb720f743e9d720cd07292ec7e1ec325e059 (DLMS 3.3.0).
Exact source: 4b50e2b3fb39dd478d355bf785b319805579076c; four documentation additions only.
The application, Desktop additions and independently authored badge are MIT;
Copyright (c) 2026 Mike Buchanan for the owner-authorized Desktop portions.
Third-party copyrights and licenses are preserved, not replaced by MIT.
This is a technical redistribution record, not legal certification.

## Included materials and selected license paths

- Qt/PySide/Shiboken 6.11.2: use the available LGPL route for retained runtime
  modules. The seven previously identified unused GPL/commercial Qt families
  and optional Readline remain excluded. Keep LGPLv3 and GPLv3 texts, Qt notices,
  Chromium attributions, and the source/rebuild/replacement materials alongside
  the application. Source-superset notices identify optional upstream code too;
  inclusion of a notice does not mean its executable code is bundled.
- The complete official Qt 6.11.2 and PySide source archives are supplied. Qt's
  CHROMIUM_VERSION records security patches through 151.0.7922.71, matching the
  wheel's reported patch level; its Chromium chrome/VERSION records
  140.0.7339.225, matching the wheel's reported core. This is source/version and
  patch-level correspondence, not a claim of bit-reproducible vendor binaries.
- The separate Tesseract 5.5.3 command-line program uses Apache-2.0 code,
  Leptonica 1.87.0 BSD code, and native libraries including JBIG 2.1 GPL-2.0-or-later.
  Preserve all component notices. Convey the GPL-bearing OCR linked combination
  under the GPLv3-compatible path, with complete relevant source/build materials;
  the later-version election avoids an Apache-2.0/GPLv2-only incompatibility.
  This does not relicense the MIT Desktop application. It invokes the independently
  usable OCR executable via command-line files and ordinary TSV output, not by
  loading GPL OCR library code into the application's address space.
- Ubuntu native libraries: exact binary/version/source-package mappings,
  copyright texts and original source plus Ubuntu patches are supplied. The
  copyright files cover whole source packages; their GPL references may describe
  unshipped tools/tests. LGPL libraries retain their replacement rights; GCC
  runtime libraries retain the GCC Runtime Library Exception. Other alternative
  licenses (such as Zstandard BSD and FreeType FTL) retain their original terms.
- PDFium 156.0.8076.0 / pypdfium2 5.14.0: wrapper and exact wheel-provided
  BUILD_LICENSES are included, separately from Qt's embedded PDFium. Preserve
  BSD/Apache/CC-BY and individual native notices. Unknown producer core hashes
  are not represented as proven; permissive components are not assigned an
  invented universal corresponding-source requirement.
- Pillow 12.3.0: preserve its comprehensive native copyright/license text.
  Runtime files, rather than optional build-SBOM entries, determine inclusions.
- CPython 3.14.7, frozen Python packages, PyInstaller bootloader/exception,
  English OCR data and all included fonts/web assets retain their own notices.
- The AppImage runtime is MIT with statically linked third-party code. Its
  libfuse 3.15.0 LGPLv2.1 source, upstream mount patch, squashfuse 0.5.2 source,
  musl 1.2.5-r11, Zstandard 1.5.6-r2, zlib 1.3.2-r0, mimalloc 2.1.7-r0 and
  pinned build recipes are supplied. Tooling is distinct from bundled runtime
  code; no AppImage license is applied to the application as a whole.

No additional restriction on modification, compatible library replacement or
reverse engineering for debugging those modifications is imposed. Source and
replacement instructions are in BUILD_AND_REPLACEMENT.md. The accompanying
SOURCE_MATERIALS.json binds source-companion names and SHA-256 values. A final
public delivery must make those companions available beside the binaries; local
preparation alone is not public source delivery or a fulfilled source offer.

Authoritative references (checked 2026-10-17):
https://doc.qt.io/qt-6.11/qtwebengine-licensing.html
https://doc.qt.io/qtforpython-6.11/licenses.html
https://www.gnu.org/licenses/lgpl-3.0.html
https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html
https://www.gnu.org/licenses/gpl-faq.en.html#MereAggregation
https://www.gnu.org/licenses/license-list.html#apache2
https://www.gnu.org/licenses/gcc-exception-3.1.html

Host-provided graphics, Fontconfig and GBM are not represented as bundled code.
Their libraries/configuration remain host requirements. Do not infer a public
qualification of every Linux distribution from the Ubuntu-compatible ABI floor.
