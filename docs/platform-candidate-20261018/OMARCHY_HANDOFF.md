# Omarchy: exact Linux safety candidate

This is a focused native qualification handoff, not permission to update an installed application. Use the **same AppImage qualified on Fedora**, release `linux-330-safety-20261018`. No rebuild, profile discovery, automatic adoption, host settings change or production-server connection is required. The AppImage remains a Linux x86_64 preview; native Omarchy acceptance for this exact file is pending until recorded.

## Pinned inputs and transfer

- Shared runtime: `bfdffb720f743e9d720cd07292ec7e1ec325e059` in `drakahari/DLMS_next`.
- Complete build source, including the four approved audit documents: `4b50e2b3fb39dd478d355bf785b319805579076c`, branch `docs/workflow-recovery-audit-20261018`.
- Separate preparation branch: `build/linux-safety-candidate-20261018`. Its handoff additions do not change that runtime. Its exact preparation commit is the Git commit containing this handoff; record `git rev-parse HEAD` after fetching it. The build-source commit above remains fixed.
- AppImage: `DLMS-Desktop-3.3.0-safety-20261018-linux-x86_64.AppImage`.
- SHA-256: **af46249a70520c2f5374419ccf7760aabee230887cc4eacaee2e02e74c12b9a5**.
- Producer artifact path: **/home/drak/Documents/dlms_desktop/.gate1/platform-freeze-20261018/artifacts/DLMS-Desktop-3.3.0-safety-20261018-linux-x86_64.AppImage**.
- Matching tar: `DLMS-Desktop-3.3.0-safety-20261018-linux-x86_64.tar.zst`; SHA-256 **0268dd5ab14e173449e5a36dcb5bdd7e1cc809c0187abceacb67842e85792cb6**.

Copy the AppImage and its SHA256SUMS from the producer through an owner-approved direct file transfer into Downloads. There is no published candidate release URL. Do not substitute Preview1 or an older similarly named file. The smallest transfer is the single exact AppImage; transfer the notice/source companions as well if passing the package to another recipient. Source, notices and provenance are described in the preparation summary. Checksums establish byte identity, not independent publisher authentication.

The Linux producer uses the pinned Ubuntu 24.04-compatible process in [linux-desktop-preview-build.md](../linux-desktop-preview-build.md), current locks, minimal exclusions and host Fontconfig/GBM handling. Both formats derive from one payload. FUSE is needed for normal AppImage mounting; `--appimage-extract-and-run` is a separate fallback and must not be reported as a normal FUSE launch pass. Keep Chromium sandboxing enabled. Do not add `--no-sandbox`, replace host libraries or suppress graphics/portal logs.

## Guarded first launch

Fetch only the handoff files/fixtures into a new ordinary Documents checkout. This command refuses an existing checkout and verifies that it contains the pinned build source. Record its fetched head for evidence. It does not check out or build a different runtime:

```sh
set -eu
handoff_checkout="$HOME/Documents/DLMS-safety-handoff-20261018"
test ! -e "$handoff_checkout"
git clone --single-branch --branch build/linux-safety-candidate-20261018 \
  https://github.com/drakahari/DLMS_next.git "$handoff_checkout"
git -C "$handoff_checkout" merge-base --is-ancestor 4b50e2b3fb39dd478d355bf785b319805579076c HEAD
git -C "$handoff_checkout" rev-parse HEAD
```

Then launch from your ordinary graphical terminal. The existing `XDG_RUNTIME_DIR`, display/session and D-Bus environment are inherited; **do not replace XDG_RUNTIME_DIR with an empty directory**. HOME/XDG data/config/cache are scoped only to this child and remain outside the AppImage. The selected profile and origin will survive moving or renaming the AppImage when reopened with these same settings.

```sh
set -eu
candidate="$HOME/Downloads/DLMS-Desktop-3.3.0-safety-20261018-linux-x86_64.AppImage"
printf '%s  %s\n' 'af46249a70520c2f5374419ccf7760aabee230887cc4eacaee2e02e74c12b9a5' "$candidate" | sha256sum -c -
test -n "${XDG_RUNTIME_DIR:-}"
test -d "$XDG_RUNTIME_DIR"
review="$HOME/Documents/DLMS safety 20261018 Omarchy"
test ! -e "$review"
umask 077
mkdir "$review"
mkdir "$review/home" "$review/data" "$review/config" "$review/cache" "$review/tmp" "$review/fixtures"
cp "$HOME/Documents/DLMS-safety-handoff-20261018/docs/platform-candidate-20261018/fixtures/"* "$review/fixtures/"
(cd "$review/fixtures" && sha256sum -c SHA256SUMS)
chmod u+x "$candidate"
env -u PYTHONPATH -u PYTHONHOME HOME="$review/home" XDG_DATA_HOME="$review/data" \
  XDG_CONFIG_HOME="$review/config" XDG_CACHE_HOME="$review/cache" TMPDIR="$review/tmp" \
  "$candidate" --profile safetyomarchy01
```

Complete later reopen command (does not recreate or clear data):

```sh
set -eu
candidate="$HOME/Downloads/DLMS-Desktop-3.3.0-safety-20261018-linux-x86_64.AppImage"
printf '%s  %s\n' 'af46249a70520c2f5374419ccf7760aabee230887cc4eacaee2e02e74c12b9a5' "$candidate" | sha256sum -c -
review="$HOME/Documents/DLMS safety 20261018 Omarchy"
test -d "$review/data/dlms-desktop-appimage-test"
test -n "${XDG_RUNTIME_DIR:-}"
test -d "$XDG_RUNTIME_DIR"
env -u PYTHONPATH -u PYTHONHOME HOME="$review/home" XDG_DATA_HOME="$review/data" \
  XDG_CONFIG_HOME="$review/config" XDG_CACHE_HOME="$review/cache" TMPDIR="$review/tmp" \
  "$candidate" --profile safetyomarchy01
```

Native choosers should use their visible navigation to the real Documents review folder; do not rely on Ctrl+L. Select only supplied fixtures or outputs created in this review. The app's scoped HOME means the chooser may initially show its empty test home. The original graphical terminal still has the normal HOME and session environment; the OpenURI portal should open the normal default browser without borrowing a browser profile.

## Compact native checklist

Use the existing Help/manual steps first. Record pass/fail and the exact artifact hash; a screenshot or success toast alone does not prove export content or persistence.

1. Import `neutral-quiz.txt`, save, Study all four correctly, make an Exam with the first two wrong, then close/reopen. Verify 4/4 Study, 2/4 Exam, exact retained answers and unchanged Local identity. Check About release/runtime identity and corrected Help guidance.
2. Import `synthetic-hotspot-pack.zip`; exercise circle/polygon grading, marking, Rebuild All and reopen. Verify images/targets still behave the same and saved history remains. Unsupported damaged historical content is out of scope; no recovery/migration claim.
3. Mark an ordinary question and use marked Anki export. Save, repeat, Cancel, inspect valid APKG. Exercise its offered fallback only when it is actually presented. In Exam History → Review This Attempt select only the second missed question; exported APKG must contain only that selected miss. Cancel/collision should preserve destination bytes and existing saved result.
4. Custom Anki Deck → Preview → Open Avery Print Layout: layout must load via intended POST, and return must retain selected cards/deck name. This tests rendered output, not physical printing/duplex alignment.
5. At narrow width, Quiz Bundles hamburger opens/closes, exposes links, updates state, and leaves selections unchanged. Check keyboard activation/focus, one light and one dark theme, and native 200% scaling. Physical observations are new native evidence; inherited geometry checks are not a substitute.
6. TXT export uses native Save As, repeats correctly and Cancel restores usable focus. Use an ordinary question's AI action with mouse and keyboard: normal default browser opens deliberately, clipboard is correct, nothing is automatically pasted/submitted. Report portal failures and their exact text; do not bypass them.
7. With a separately task-owned synthetic DLMS server running the **same pinned runtime**, configure its exact loopback origin with explicit private-HTTP consent. Keep Local and Server visibly distinct. Save one Study response and one Exam, close/reopen, verify Server history then return Local and verify its original records. Stop that synthetic server; confirm explicit outage without Local fallback. Never enter the owner's server. No new lost-ack/crash matrix is requested.

A platform agent can run `tests/browser/_server.py` with a fresh `QUIZAPP_DATA_DIR`, explicit `DLMS_BROWSER_TEST_BIND_HOST=127.0.0.1` and unused `DLMS_BROWSER_TEST_PORT`, using a pinned source environment. Its bind failure is a conflict to report, not authority to terminate another process. Preserve the service's launch/PID evidence and stop only the exact task child. Do not connect this candidate to a production endpoint to finish the checklist.

## Evidence boundaries and stopping point

The bounded Fedora audit is complete. Reuse [final safety report](../quality/workflow-final-safety-20261018.md), [follow-up](../quality/workflow-recovery-followup-20261018.md), [findings ledger](../quality/workflow-findings-20261018.md) and remaining-work list. Normal-package tests with diagnostic/fault injection, owner-operated menus, source-Qt tests and this ordinary native run are distinct layers. The earlier candidate had older Anki outcome wording/Help; this candidate's embedded correspondence must be checked against its new build manifest.

All six repairs are shared hotspot preservation/marking, Qt marked Anki transport, Qt Avery POST transport, Qt attempt Anki consent plus shared subset handling, and shared Quiz Bundles navigation. A remote deployment needs its own shared fixes for hotspot/subset/menu behavior; Desktop cannot repair old Server code. The frozen runtime contains those fixes; Preview1 downloads remain unchanged. Keep portal/VM graphics warnings, physical accessibility/printing, real power loss/disk exhaustion and public-distribution/signing limits explicit. A committed Exam with no post-interruption Resume was resolved by History; the disappearance mechanism is unresolved and that branch did not retry the same ID. Do not repeat that fault test here.

Return a short result with OS/session, hash, observed checks/failures and task cleanup. Leave installed applications and all existing profiles untouched. Manual update later means verified file replacement while closed; preserving an old executable cannot undo incompatible schema/data changes. Installation/release approval is separate.
