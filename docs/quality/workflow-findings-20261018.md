# Workflow findings ledger — 2026-10-18

This portable ledger retains the four confirmed Fedora Desktop 3.3.0 Preview 1 findings and documentation gaps. The original audit and reproductions remain unchanged in the owner's private evidence store. This file contains no profiles, quiz history, credentials or private operational logs. Machine-readable counterpart: [workflow-findings-20261018.json](workflow-findings-20261018.json).

Observed artifact: `DLMS-Desktop-3.3.0-preview1-linux-x86_64.AppImage`, SHA-256 `f1693fcc751685d8811c9067f29f25bc677de7676d6e9abf1050bbc3e049c579`; application source `86b04e4d5a0658a7dd39ce6c7e2d9a0582ee32fd` plus reviewed packaging overlay. Repair baseline: public main `12c202920f45219cc13ae7c4cca940c938bd7aab`.

| ID | Component and scope | Reproduction and impact | Repair status / remaining coverage |
|---|---|---|---|
| F2 — High | Shared application: `quiz_mutations`, image-pack generator, runtime artifacts | Generate circle/polygon image practice; Rebuild All reports success but replaces the spatial assessment with its DB choice surrogate. Runtime JSON/HTML change; database, saved history and image bytes remain. New wrong grading was not demonstrated. | Current batch: preserve validated authoritative runtime bytes during rebuild; refuse missing/inconsistent hotspots per item. Source/browser/frozen results recorded in hotspot repair report. Historical recovery and old-state compatibility are out of scope. Windows/Mac native checks remain pending. |
| F1 — Medium | Shared application: `study_packs`, review-mark source verification | Fresh unchanged imported-pack hotspots refuse Mark for review with a source-change error. Existing marks and Study answers survive. Image-builder control worked. | Current batch: new image-practice publication persists the same media and explanation as its runtime. Genuine fingerprint/assessment conflicts remain enforced. Existing media-empty surrogates are not rewritten or adopted. |
| F3 — Medium | Qt Desktop download gate + review-mark blob export | Select eligible ordinary text mark; Export Anki and fallback link are blocked before Save As while web says exported. Whole-quiz/custom APKG paths worked. | OPEN, no repair in this batch. Validate blob ownership/document/origin and truthful publication status in a separate change. Original browser applicability unconfirmed; Windows/Mac hosts require their own evidence. |
| F4 — Medium | Qt Desktop new-window handling + custom print POST | Preview cards, choose duplex, Open Avery Print Layout: HTTP405. Source indicates URL-only forwarding loses POST; exact method trace still needed. | OPEN, no repair in this batch. Preserve original validated request; qualify printable content before physical printing. Original browser applicability unconfirmed. |

## Documentation gaps — all open

| ID | Affected instructions | Correction needed |
|---|---|---|
| DG01 | Getting Started / reconnect | Distinguish dedicated Desktop window and stable selected-profile origin from a guessed fixed localhost URL. Preserve valid browser-edition guidance. |
| DG02 | Data locations | Identify browser, standalone Desktop and installed Desktop roots separately. |
| DG03 | Server use | Distinguish hosting DLMS from connecting Desktop; server data belongs to that deployment, with no automatic Local synchronization. |
| DG04 | Lifecycle | Distinguish browser-presence shutdown from Desktop close/pending-save guards; explicitly disposition the visible Application Lifecycle settings page. |
| DG05 | Backup creation | Document native Save Backup As, collision refusal, publication completion and Open containing folder. |
| DG06 | Backup adoption | Document native selection, private validation, destination/digest confirmation and transactional outcome, rather than legacy web controls. |
| DG07 | Removal | Do not promise Desktop will silently recreate an intentionally removed profile on relaunch. |
| DG08 | Server file access | Explain explicit native file consent, staging and Local/Server boundaries. |
| DG09 | Download/version labels | Replace stale version/private-candidate statements with edition-specific availability and qualification. |
| DG10 | Feature/format reference, matching CSV | Summary claims review before publication, while detailed instructions and captured implementation create the quiz directly and open editing. Correct the summary; no new workflow authorized. |

## Coverage retained as open

The audit's 129 parent rows comprise 4 passed, 4 failed, 5 blocked, 112 incomplete and 4 not applicable. Of the112 incomplete rows,93 have successful main-path observations. Those counts are not a feature-failure count. Server GUI, accepted-pending shutdown, operation-specific failures, physical keyboard/scaling and external applications remain separate evidence gaps. The first repair batch does not close unrelated rows or relabel old evidence.

## Prevention and recovery

This repair prevents new/imported hotspot assessments being downgraded by Rebuild All. It retains their runtime bytes, IDs, target geometry, references, marks and factual history. It is not a recovery tool. If authoritative content is absent, corrupt, already degraded or inconsistent with saved records, the item is refused without replacing its files. Source-pack regeneration is not represented as identity-preserving recovery. No historical data is deleted or migrated.

Draft temporary warning (owner review required; not published):

> Avoid Rebuild All Quiz Pages for libraries containing Study Pack image/hotspot quizzes until the preservation fix is available in your build. If you already used it, preserve current data, original packs and pre-rebuild backups. Assess recovery in a disposable copy before changing affected quizzes. A newly created backup may already contain the altered assessment.
