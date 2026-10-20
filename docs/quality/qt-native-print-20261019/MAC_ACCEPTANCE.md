# Standard Avery printing — bounded Mac acceptance

Reviewed source commit: `acf00838973037f25721f9a13961e76e1916f947`, parent `2107e5cffc787705dfbbb495995655ebd504dedd`.
The literal complete reviewed overlay is `449182ad6507af54989a70ea22ba616513e8b74f52c73f293ee0b3b1835ae449`.
See [commit/artifact binding](COMMIT_ARTIFACT_ACCEPTANCE.md) and the
[focused Fedora/Omarchy handoff](FEDORA_HANDOFF.md).

## Accepted behavior and attribution

Print Cards uses the standard print dialog for physical printers and its native
PDF option. There is no separate Save Avery PDF action and no required
save-and-open step. The system owns destination choice and ordinary overwrite
confirmation. Opening the dialog does not automatically confirm Print/Save.
Other exports retain their existing protections. Mac copies selected-card PDF
bytes into immutable NSData/PDFKit; Linux retains QPrintDialog/QPrinter printing,
not a new renderer. Native failure reports unconfirmed completion rather than
claiming no destination changed after the operation began.

The agent prepared only disposable ALPHA/CHARLIE/BRAVO cards in isolated synthetic
Local storage and a matching task-owned loopback Server. ALPHA/CHARLIE were
selected; BRAVO was excluded. Source setup/readback used the existing QtChecks
helper. The owner clicked Print Cards and operated actual standard print/PDF,
filename, Save, Cancel and system Replace controls; those responses were not
simulated. Agent checks below are not relabeled as owner observations.

| Check | Result and scope |
| --- | --- |
| Source native PDF saving, Local | PASS: owner used standard dialog PDF/Save As and reported saved; agent read actual two-page Letter PDF and verified selected questions/answers, BRAVO absent |
| Source native PDF saving, synthetic Server | PASS: same owner actions; agent verified actual saved selected-only two-page Letter PDF |
| Source cancellation, Local | PASS: owner canceled Save As, observed return to print dialog and canceled that too; agent verified not_completed feedback, original saved PDF unchanged, canceled output absent and selected layout unchanged |
| Source system overwrite, Local | PASS: a new blank synthetic PDF was the only existing target. Owner declined native Replace first; agent verified identical original bytes. Owner then explicitly approved Replace; agent verified selected-card PDF and first saved PDF unchanged |
| Return, Local and synthetic Server | PASS: agent used existing QtChecks input/readback and verified exact selected IDs, deck name and short-edge setting retained |
| New packaged smoke, Local | PASS: real frozen app, fresh explicit synthetic root/profile, loopback diagnostics for setup and trusted Print Cards input/readback. Actual standard native dialog and PDF option present; one AX Cancel succeeded; selected private snapshot verified; normal Quit and recorded child cleanup completed |
| Packaged PDF Save As / overwrite / Server | REUSED SOURCE EVIDENCE: not repeated in the package. Exact frozen/source correspondence verified; do not call this a second packaged native-save acceptance |
| Task cleanup | PASS: source app and synthetic Server stopped; package app/recorded children stopped, loopback diagnostic port closed, synthetic writer locks free |

Focused source validation retained: **87 tests and 59 subtests** for printing,
output boundaries and Mac packaging. The source GUI journey covered selected
content, refusals, simulated cancel/overwrite, Return and Local/Server staging
separation; its dialog responses remain explicitly simulated. A separate legacy
Server button without an ID/status node worked. Earlier focused source Local
printer/settings selection plus Cancel is reused; it does not prove paper output.
Independent prebuild source and final artifact/packet reviews passed. No broad
workflow audit or completed owner walkthrough was repeated to commit this work.

## Remaining limits

- No physical Print job was requested. Physical paper output, feeding, alignment,
  duplex alignment and paper type remain **unqualified**. Success/completion or
  PDF output cannot establish them.
- Real cancellation and overwrite above are Local observations, not separate
  Server-native cancellation/overwrite passes. Both modes' actual native PDF
  saves and agent Return checks passed.
- New package smoke is Local dialog/PDF-option/Cancel, with diagnostic synthetic
  setup; it does not newly qualify cold Finder/default-profile or browser-downloaded/
  quarantined opening. Signing is ad hoc, without Developer ID/notarization;
  no Gatekeeper bypass or quarantine removal was performed.
- Fedora/Omarchy native printer/PDF and packaged qualification remain separate.
  Mac evidence and portable CI do not establish Linux native acceptance.
  Windows uses WebView2 and is not changed to Qt printing.
- File-consent/origin/path/descriptor/content safeguards are retained. A malicious
  native process already running as the same user remains outside the Mac
  immutable-flag snapshot guarantee; no Linux-equivalent sealing is claimed.

Raw UI trees, system-generated PDF metadata, process identities/nonces, profiles,
databases, backups and operational logs remain local and are excluded from Git.
Only these sanitized summaries and hashes are committed. The installed app,
personal profiles and production server were untouched. No rebuild, installation,
merge, release/tag changes or publication is part of this commit/push task.
