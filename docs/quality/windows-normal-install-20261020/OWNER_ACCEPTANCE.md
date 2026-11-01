# Windows installer owner acceptance

The owner reports that the installer with SHA-256
`5ff8f93f4321301fb337f8f6dd8eb244bc4b20037e91905b1817007144818c80`
installed successfully, launched and reopened from Windows Start, and worked in
Local and Server modes during their testing. This records the owner's bounded
acceptance; it does not imply testing every account, upgrade or recovery case.

The subsequent change is limited to installer presentation:

- **Create a Start menu shortcut** is checked by default. Both menu entries and
  their existing validation use that positive selection.
- The desktop shortcut remains optional and unchecked.
- The normal summary omits internal profile names and technical fallback wording.
- Application payload, printing, data selection, persistence and security
  validation remain unchanged. Exceptional conflicting-data handling is retained.

The presentation delta was checked against the exact accepted installer source:
only the task label/polarity, corresponding menu conditions, summary text,
comment and obsolete fallback sentence differ.

Five focused source assertions and three compiled inert-fixture cases passed:
default menu on/desktop off; menu unchecked; and menu plus optional desktop.
Actual shortcut targets, working directories and arguments were verified.
These are task-mapping checks, not physical checkbox-click acceptance.

The presentation installer is delivered under a distinct Desktop filename for
owner review. It is not launched, installed or published by the agent. Previous
artifacts and the working installation are preserved. Exact artifact hashes and
original application provenance are retained in the local build/delivery receipts.
