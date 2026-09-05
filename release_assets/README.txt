DLMS 3.0.2
==========

DLMS is a local-first learning, quiz, study, analytics, and content-import
application. It runs on your computer and opens its interface in your web
browser.

CHOOSE THE PACKAGE FOR YOUR SYSTEM

- Fedora 44: DLMS-3.0.2-fedora44-x86_64.tar.gz
- Ubuntu 24.04: DLMS-3.0.2-ubuntu24.04-x86_64.tar.gz
- Ubuntu 26.04: DLMS-3.0.2-ubuntu26.04-x86_64.tar.gz
- Windows 11: DLMS-3.0.2-windows11-x86_64.zip
- macOS Apple Silicon: DLMS-3.0.2-macos-arm64.zip
- Omarchy Quattro: DLMS-3.0.2-omarchy-quattro-x86_64.tar.gz

The Linux packages are built and tested separately for the named operating
system. Do not assume that one Linux build is universal across distributions.

PACKAGE CONTENTS

Each package contains the DLMS application for its named platform, this
README.txt, and sample_quiz.txt.

STARTING DLMS

Linux

1. Extract the .tar.gz package.
2. Open a terminal in the extracted package folder.
3. Run the executable, for example:

   ./DLMS-3.0.2-fedora44-x86_64

The executable permission is preserved by the archive. If another transfer
method removed it, restore it with:

   chmod +x DLMS-3.0.2-<platform>-x86_64

Windows 11

1. Extract the ZIP package.
2. Open the extracted package folder.
3. Double-click DLMS-3.0.2-windows11-x86_64.exe.

Windows may display Microsoft Defender SmartScreen for an unsigned download.
Verify the published SHA-256 checksum and that the file came from the official
DLMS release before choosing More info and Run anyway.

macOS Apple Silicon

1. Extract the ZIP package.
2. Drag DLMS.app to Applications.
3. Control-click DLMS.app, choose Open, and then choose Open again.

DLMS 3.0.2 is not notarized, so macOS may require approval in System Settings >
Privacy & Security. Use Open Anyway only after verifying the published SHA-256
checksum and the download source.

USING DLMS

DLMS opens a local address in your default browser. Keep the DLMS application
running while using that browser page. Closing the browser tab or window does
not stop DLMS; use Shutdown DLMS in the application when you are finished.

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
