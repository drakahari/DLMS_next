# Appendix: Platform and Runtime Notes

This appendix collects the platform and runtime differences that affect an
ordinary DLMS user. For the complete setup procedure, see
[Installation and First Launch](02-installation-and-first-launch.md). Native
build and release-production instructions are intentionally outside the user
manual.

## Current native package targets

The DLMS 3.2.2 release process defines user packages for:

| Platform | Architecture | Canonical package name |
| --- | --- | --- |
| Fedora 44 | x86-64 | `DLMS-3.2.2-fedora44-x86_64.tar.gz` |
| Ubuntu 24.04 | x86-64 | `DLMS-3.2.2-ubuntu24.04-x86_64.tar.gz` |
| Ubuntu 26.04 | x86-64 | `DLMS-3.2.2-ubuntu26.04-x86_64.tar.gz` |
| Omarchy Quattro | x86-64 | `DLMS-3.2.2-omarchy-quattro-x86_64.tar.gz` |
| Windows 11 | x86-64 | `DLMS-3.2.2-windows11-x86_64.zip` |
| macOS Apple Silicon | arm64 | `DLMS-3.2.2-macos-arm64.zip` |

Choose the package that matches the computer that will run DLMS. A package
target identifies the environment in which the release is built and verified;
it does not establish compatibility with every similar or later operating
system.

## Packaged DLMS and source runtime

For ordinary use, prefer a verified packaged release. It includes the DLMS
application and the local components needed by that package, so the user does
not need to install Python or assemble an OCR environment.

Running from source is an alternative for contributors and technically
experienced users. It requires the repository's Python environment and
dependencies. OCR also depends on the required local OCR components being
available to that source environment. The browser interface and persistent
workspace are conceptually the same, but setup and dependency troubleshooting
belong to the source environment rather than the packaged application.

If an optional capability is unavailable, DLMS should leave the rest of the
application usable and explain the missing capability. For OCR-specific
guidance, see [PDF, Smart PDF, and OCR](10-pdf-smart-pdf-and-ocr.md#when-ocr-is-unavailable).

## Platform notes

### Windows

Extract the release ZIP before running DLMS. Windows may show a Microsoft
Defender SmartScreen warning because the application is distributed without a
commercial code-signing reputation. Confirm that the package came from the
expected DLMS release and that its checksum matches the published checksum
before choosing the operating system's option to run it.

Keep the files supplied together in the extracted release folder. Do not run
the executable from inside the ZIP viewer.

### macOS

The macOS ZIP contains `DLMS.app`, `README.txt`, and `sample_quiz.txt` at its
root. Drag `DLMS.app` to **Applications**, then start it from there. macOS may
show a Gatekeeper warning because the application is not signed and notarized
through Apple's commercial distribution process. Verify the download and use
the operating system's supported override only when you trust the source.

The current native target is Apple Silicon (`arm64`).

### Linux

Use the archive for the named distribution. Extract it while preserving file
permissions, then run the included executable from its extracted release
directory. If the executable bit was lost during transfer or extraction,
restore it only after verifying that the file and checksum are the expected
DLMS release.

The current Linux native targets are x86-64. Desktop security policy, firewall
configuration, and browser selection can vary by distribution.

## Where DLMS stores data

Packaged DLMS keeps its writable workspace outside the application bundle or
executable. The default application-data locations are:

| Platform | Default data location |
| --- | --- |
| Linux | `$XDG_DATA_HOME/DLMS` when `XDG_DATA_HOME` is set; otherwise `~/.local/share/DLMS` |
| Windows | `%APPDATA%\DLMS` |
| macOS | `~/Library/Application Support/DLMS` |

This separation allows an application update to replace program files without
requiring the user to replace the study workspace. It also means that copying
only the executable is not a backup. Use **Backup & Restore** when protecting
or moving the whole DLMS workspace; see
[Maintenance, Backup, and Data Management](17-maintenance-backup-and-data-management.md).

Source-runtime or explicitly configured launches can use a different data
location. If you start DLMS through a custom command, service, or launcher,
record the location chosen by that setup.

## Local desktop mode

Normal desktop use binds DLMS to the loopback interface, ordinarily at
`127.0.0.1:9001`. The DLMS process runs on the computer and serves the interface
to a local browser. This browser-based interface does not make DLMS a cloud
service.

The packaged application normally opens the interface automatically. If it
does not, keep the DLMS process running and open the local address shown by the
application. Browser auto-launch can also be deliberately disabled.

In local desktop mode:

- **Shutdown DLMS** stops the application immediately through the interface;
- optional browser-presence shutdown may stop an eligible run after the last
  DLMS page has been closed for about five minutes;
- closing one browser tab is not the same as choosing **Shutdown DLMS**, and
  immediate termination should not be assumed.

The browser-presence option is a convenience, not a substitute for checking
that the application has stopped when shutdown matters.

## LAN/server mode

LAN/server mode is an explicit non-loopback configuration that makes one DLMS
process reachable from other computers on a trusted local network. A host may
bind to an address such as `0.0.0.0`, but that wildcard bind address is not the
address clients type into a browser; clients use the host computer's reachable
LAN address and port.

DLMS remains a single-user application in this mode. All connected clients use
the same server workspace. It does not add user accounts, per-person libraries,
authentication, or encrypted HTTPS transport. Use it only on a trusted,
firewalled network and do not expose it directly to the public Internet.

In LAN/server mode:

- in-app and API shutdown are unavailable;
- automatic browser-presence shutdown is unavailable;
- closing client browser windows does not stop the server;
- the user must stop the DLMS process or service from the host computer—for
  example, from the terminal, service manager, or process manager that started
  it.

This rule follows the configured runtime/bind mode. It does not change based on
which client address happens to make a request.

## Shared and browser-local state

Clients connected to one LAN/server instance share persistent server data,
including quizzes, folders, completed attempts, saved learning activity,
settings, and scheduling results. After refresh, clients should see the same
server-derived due counts and completed history.

An interrupted quiz checkpoint is different. Resume state marked **This
browser** belongs to that browser profile. Another client can therefore show a
different unfinished session—or none—while still sharing completed activity.
This is expected and is not an account-synchronization feature.

For the practical recovery behavior, see
[Unfinished sessions and Resume](06-taking-quizzes.md#resume-an-interrupted-quiz).

## First-launch warnings and verification

Windows and macOS warnings described above are operating-system trust checks,
not DLMS error messages. Before overriding one:

1. obtain the package from the expected project release;
2. compare its SHA-256 checksum with the published release checksum;
3. confirm that its filename matches the intended platform and architecture;
4. extract or install it using the platform procedure.

If the package cannot start after those checks, see
[Troubleshooting](18-troubleshooting.md#dlms-did-not-open-a-browser).
