UNPUBLISHED FEDORA MAINTENANCE CANDIDATE — 3.3.2 RC1

DLMS 3.3.2 RC1
==========

DLMS is a local-first learning, quiz, study, analytics, and content-import
application. It runs on your computer and opens its interface in your web
browser.

RELEASE STATUS

Original DLMS 3.3.2 RC1 and DLMS Desktop 3.3.2 Preview 1 are unpublished
maintenance candidates. This task builds and qualifies Fedora 44 only; no new
Ubuntu, Windows or macOS package is promised by the filename examples below.
Use the matching candidate SHA256SUMS and source/notices companions. Do not
replace an installed application or point a candidate at live data for testing.
The source identity and focused acceptance are recorded with each candidate.
Public stable downloads remain Original 3.3.1 and Desktop 3.3.1 Preview 1.

CHOOSE THE PACKAGE FOR YOUR SYSTEM

- Fedora 44: DLMS-3.3.2-RC1-fedora44-x86_64.tar.gz
- Ubuntu 24.04: DLMS-3.3.2-RC1-ubuntu24.04-x86_64.tar.gz
- Ubuntu 26.04: DLMS-3.3.2-RC1-ubuntu26.04-x86_64.tar.gz
- Windows 11: DLMS-3.3.2-RC1-windows11-x86_64.zip
- macOS Apple Silicon: DLMS-3.3.2-RC1-macos-arm64.zip

The Linux packages are built and tested separately for the named operating
system. Do not assume that one Linux build is universal across distributions.

PACKAGE CONTENTS

Original packages, when built for a target, contain the DLMS application for their named platform, this
README.txt, and sample_quiz.txt. In the macOS ZIP, DLMS.app, README.txt, and
sample_quiz.txt are all directly at the archive root, with no wrapper folder.

STARTING DLMS

Linux

1. Extract the .tar.gz package.
2. Open a terminal in the extracted package folder.
3. Run the executable, for example:

   ./DLMS-3.3.2-RC1-fedora44-x86_64

The executable permission is preserved by the archive. If another transfer
method removed it, restore it with:

   chmod +x DLMS-3.3.2-RC1-<platform>-x86_64

Windows 11

1. Extract the ZIP package.
2. Open the extracted package folder.
3. Double-click DLMS-3.3.2-RC1-windows11-x86_64.exe.

Windows may display Microsoft Defender SmartScreen for an unsigned download.
Verify the candidate SHA-256 checksum and that the file came from the official
DLMS release before choosing More info and Run anyway.

macOS Apple Silicon

1. Extract the ZIP package.
2. Confirm DLMS.app appears directly in the extraction location, then drag it
   to Applications.
3. Open DLMS.app from Finder or Applications.

DLMS 3.3.2 RC1 is not notarized, so macOS may require approval in System Settings >
Privacy & Security. Use Open Anyway only when macOS offers it for this app,
after verifying the candidate SHA-256 checksum and the official download source.
Follow the displayed confirmation. Stop for malware, damage, unavailable approval,
or managed-policy blocks. Do not remove quarantine or disable Gatekeeper.

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

CURRENT WORKFLOWS

Study History contains durable Study sessions; Exam History also keeps clearly
labeled legacy Study results. Finish Review requires saved coverage, not correct
answers. Keep a pending-save tab and its recovery record until saves succeed.

Use Settings > Layout & navigation for independent dashboard/sidebar choices,
certification feature visibility and card counts. Choose any of 26 manual themes
in the sidebar or Appearance settings. Omarchy is not required.

My Certifications records earned achievements and reusable training. Learning
time, estimated credit and user-recorded accepted credit are different. AI
matching copies only reviewed material for manual paste; it does not renew records.

Restore replaces the workspace with the backup, losing subsequent changes.
Schema 12 cannot be rolled back by replacing the binary. Keep a verified
pre-upgrade backup and the compatible older application in a separate profile.
Clear Saved Results and permanent data removal have no automatic safety backup.
Permanent removal deletes backups inside the data folder, not the executable.
See Help > System Tools & Data Management before destructive actions.
