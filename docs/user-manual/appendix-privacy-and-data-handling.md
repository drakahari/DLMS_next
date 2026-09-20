# Appendix: Privacy and Data Handling

DLMS is local-first: it is designed to keep the application and study
workspace on the computer that runs it. This appendix explains that practical
privacy boundary. It is not a legal privacy policy or a guarantee against every
security risk.

## Local by default

Ordinary local desktop use does not require a DLMS account or sign-in. The DLMS
process serves its interface to a browser on the same computer and stores the
persistent workspace in that computer's application-data location. Quizzes,
folders, settings, completed attempts, learning evidence, schedules, installed
packs, and related content remain part of that local workspace unless the user
deliberately exports, backs up, or shares them.

DLMS does not need a hosted DLMS service to perform ordinary quiz, review,
history, or Learning Intelligence work. A browser interface is used because it
is the application's desktop-style user interface; it does not by itself mean
that study data is uploaded to a website.

See [Platform and Runtime Notes](appendix-platform-and-runtime-notes.md#where-dlms-stores-data)
for default data locations.

## What is stored where

| Information | Storage scope | Practical consequence |
| --- | --- | --- |
| Quizzes, folders, settings, installed content, completed attempts, learning evidence, and schedules | Persistent DLMS workspace on the host computer | Available after restart and shared by browser clients of that same DLMS server. |
| Interrupted quiz checkpoint marked **This browser** | Current browser profile | Another browser or device does not receive that Resume card. |
| Generated Practice and Mixed Quizzes | Persistent Quiz Library data | They remain until the user manages them; they are not automatically discarded after use. |
| Import/OCR review drafts | Temporary workflow staging | They exist to support the active review workflow and should not be treated as durable storage. |
| Backups and exports | A file location chosen or handled by the user/browser | Once outside DLMS, the user controls where the file is stored, copied, or shared. |

Browser-local recovery is intended to protect an interrupted session, not to
be a second history system. Once a quiz is completed and its activity is safely
saved, the completed result belongs to the persistent workspace and the local
recovery checkpoint is cleared. For details, see
[Taking Quizzes](06-taking-quizzes.md#resume-an-interrupted-quiz).

## LAN/server use changes the exposure boundary

In LAN/server mode, the workspace still resides on the computer hosting DLMS,
but the interface and its data can be reached by other clients on the allowed
network. All clients use the same single-user workspace; DLMS does not create
separate accounts or personal areas for them.

LAN/server mode does not provide DLMS authentication or TLS encryption. Use it
only on a trusted, firewalled local network. Do not bind or forward it directly
to the public Internet. Anyone who can reach the server interface may be able
to view or change the shared DLMS data.

Persistent study activity is shared after refresh, while an interrupted Resume
checkpoint remains in the browser where it was created. See
[LAN/server mode](appendix-platform-and-runtime-notes.md#lanserver-mode) for
runtime and shutdown behavior.

## OCR and local document processing

DLMS performs supported OCR locally. It does not send a selected PDF,
screenshot, or scanned page to a cloud OCR service as part of the built-in OCR
workflow. Selectable-text PDF extraction is also local.

Source files and derived pages can be held temporarily while DLMS processes and
stages a workflow:

- screenshot question OCR retains its temporary source material only for the
  review workflow and removes it on the workflow's save, cancel, or expiry
  path;
- terminology/matching OCR removes the original uploaded images or rendered
  PDF pages after OCR processing has produced the staged candidate text and
  source labels for Review & Repair;
- other import drafts and previews are temporary working material and are not
  a substitute for keeping the user's original source file.

Published questions, pairs, banks, or quizzes follow their normal persistent
storage rules. DLMS does not promise that a temporary upload will remain
available as a source archive, so retain the original document separately when
it matters.

## External AI is a manual, optional boundary

The External AI workflows do not connect DLMS directly to ChatGPT, Gemini,
Claude, or another provider. DLMS creates a bounded prompt; the user manually
copies it to a chosen conversational AI service, then manually pastes or uploads
the returned structured content to DLMS. DLMS does not require an AI-provider
API key and does not automatically transmit the source or prompt.

The user's act of pasting material into a third-party service is a disclosure
to that provider. Before doing so:

- remove personal, confidential, licensed, or otherwise sensitive content that
  should not leave the computer;
- understand the provider's own account, retention, training, and privacy
  terms;
- review the returned content for correctness before publishing it in DLMS.

The same boundary applies to the AI Study Pack ZIP workflow: the archive is
created outside DLMS and returned manually for local validation. See
[External AI Workflows](12-external-ai-workflows.md) for the operating steps.

## Backups, bundles, packs, and exports

Any exported file can carry information beyond the local DLMS workspace. Store
and share it according to its contents.

- A **DLMS backup** is the broad recovery format and can contain personal study
  history, settings, and user-created material. Treat it as sensitive.
- A **Portable Quiz Bundle** carries selected quiz content, supported metadata,
  folders, and media, but deliberately excludes personal attempts, scores,
  learning history, and scheduling state.
- A **Content Pack / Study Pack archive** carries reusable study content, not
  the importing user's personal attempt history.
- An **Anki package**, printable card output, or text/reference export is meant
  for external use and can expose the question and answer material it contains.
- An **External AI exchange** is intended to cross the local boundary by a
  deliberate user action; it is not a backup.

The format comparison in
[Import, Export, and Portability](15-import-export-and-portability.md#choose-the-right-format)
helps identify the appropriate file for a task.

## Generated content and learning identity

Generated Practice is saved content, not temporary browser output. DLMS keeps
the relationship between a generated copy and its source question so that new
answers can contribute learning evidence to the source without turning the
copy into an independent source question. This relationship does not cause the
source quiz to be rewritten.

Generated Practice may remain visible in the Quiz Library. Deleting or managing
a quiz should therefore be treated as a normal data action, not as a privacy
cleanup mechanism. If a generated quiz contains sensitive source material, it
has the same local-storage considerations as other saved quiz content.

## User responsibilities

Local-first design reduces automatic data sharing; it does not remove the need
for ordinary data care. Users should:

1. make backups before upgrades or large changes;
2. protect the host account and application-data directory;
3. restrict LAN/server access to trusted networks and clients;
4. review files before sharing or uploading them;
5. keep original source documents when temporary import material may be
   removed;
6. use third-party AI services only with content they are permitted and willing
   to send.

For backup scope and restoration safety, see
[Maintenance, Backup, and Data Management](17-maintenance-backup-and-data-management.md).
