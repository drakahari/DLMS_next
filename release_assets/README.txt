DLMS 3.1.0
==========

DLMS is a local-first learning, quiz, study, analytics, and content-import
application. It runs on your computer and opens its interface in your web
browser.

CHOOSE THE PACKAGE FOR YOUR SYSTEM

- Fedora 44: DLMS-3.1.0-fedora44-x86_64.tar.gz
- Ubuntu 24.04: DLMS-3.1.0-ubuntu24.04-x86_64.tar.gz
- Ubuntu 26.04: DLMS-3.1.0-ubuntu26.04-x86_64.tar.gz
- Windows 11: DLMS-3.1.0-windows11-x86_64.zip
- macOS Apple Silicon: DLMS-3.1.0-macos-arm64.zip
- Omarchy Quattro: DLMS-3.1.0-omarchy-quattro-x86_64.tar.gz

The Linux packages are built and tested separately for the named operating
system. Do not assume that one Linux build is universal across distributions.

PACKAGE CONTENTS

All six packages contain the DLMS application for their named platform, this
README.txt, and sample_quiz.txt. In the macOS ZIP, DLMS.app, README.txt, and
sample_quiz.txt are all directly at the archive root, with no wrapper folder.

STARTING DLMS

Linux

1. Extract the .tar.gz package.
2. Open a terminal in the extracted package folder.
3. Run the executable, for example:

   ./DLMS-3.1.0-fedora44-x86_64

The executable permission is preserved by the archive. If another transfer
method removed it, restore it with:

   chmod +x DLMS-3.1.0-<platform>-x86_64

Windows 11

1. Extract the ZIP package.
2. Open the extracted package folder.
3. Double-click DLMS-3.1.0-windows11-x86_64.exe.

Windows may display Microsoft Defender SmartScreen for an unsigned download.
Verify the published SHA-256 checksum and that the file came from the official
DLMS release before choosing More info and Run anyway.

macOS Apple Silicon

1. Extract the ZIP package.
2. Confirm DLMS.app appears directly in the extraction location, then drag it
   to Applications.
3. Control-click DLMS.app, choose Open, and then choose Open again.

DLMS 3.1.0 is not notarized, so macOS may require approval in System Settings >
Privacy & Security. Use Open Anyway only after verifying the published SHA-256
checksum and the download source.

USING DLMS

DLMS opens a local address in your default browser. Use Shutdown DLMS in the
application for an immediate, explicit stop when you are finished. When the
optional browser-presence shutdown feature is enabled for a loopback-only
desktop session, closing the final DLMS browser window or tab may stop DLMS
automatically after its grace period. Do not rely on automatic shutdown when
that feature is disabled or when DLMS is running in LAN/server mode.

Screenshot OCR and selected scanned-PDF OCR use Tesseract and PDFium bundled
inside the native DLMS package. Users of an OCR-enabled frozen package do not
need to install system Tesseract. If either OCR workflow is unavailable in a
packaged build, report the package/target rather than installing Tesseract as a
workaround.

To try the included sample:

1. Open Build Quiz > Quiz Builder > Create from Pasted Text.
2. Copy and paste the contents of sample_quiz.txt.
3. Enter a quiz title, preview the questions, and build the quiz.

YOUR DATA

DLMS stores your quizzes, results, settings, and other user-created data outside
the application package:

- Linux: $XDG_DATA_HOME/DLMS, or ~/.local/share/DLMS when XDG_DATA_HOME is unset
- Windows: %APPDATA%\DLMS
- macOS: ~/Library/Application Support/DLMS

Application updates or moving the downloaded package do not replace that data.
Use Settings > Backup & Restore to create a portable backup before moving to a
new computer or performing a reset.

For full usage, troubleshooting, backup, and import guidance, open the Help
Center inside DLMS.
