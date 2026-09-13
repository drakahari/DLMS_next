# Security Policy

## Supported versions

Security reports are accepted for the latest published DLMS release and the
current development branch. The latest stable release is currently 3.1.0.
Older releases do not routinely receive separate fixes; a correction may be
provided only in the next release.

| Version | Status |
| --- | --- |
| Latest published release (currently 3.1.0) | Supported |
| `develop/3.2.0` | Pre-release; reports accepted |
| Older releases | Not routinely supported |

This policy describes maintenance intent, not a response-time or security
guarantee.

## Reporting a vulnerability

Please do not disclose a suspected vulnerability, exploit, private user data,
or a sensitive reproduction in a public issue.

Use GitHub's private vulnerability-reporting form for this repository when it
is available:

<https://github.com/drakahari/DLMS_next/security/advisories/new>

If that form is unavailable, open a minimal public issue asking the maintainer
to establish a private contact channel. Do not include vulnerability details in
that issue. A useful private report includes the affected DLMS version and
platform, impact, reproducible steps, and a proposed mitigation if known. Use
synthetic data and remove credentials, personal study material, databases, and
private documents from logs or attachments.

Reports will be handled as sensitive while the issue is investigated and a
reasonable disclosure plan is coordinated. No fixed response or remediation
time is promised for this volunteer-maintained project.

## Security model and boundaries

DLMS is a local-first, single-user application. By default it binds its Flask
service to the loopback interface and opens a local browser UI. It does not
require a cloud account, telemetry service, or embedded AI-provider API.

The host operating-system account is the primary trust boundary. A person or
process that can read the DLMS application-data directory can generally read
the learner's quizzes, history, settings, and backups. Users should protect
that account and store exported backups appropriately.

LAN/server mode is an explicit advanced configuration for a trusted,
appropriately firewalled network. DLMS does not claim that LAN mode supplies
user authentication, authorization, or TLS. It must not be exposed directly to
the public internet or treated as a hardened multi-user service.

DLMS validates imported archives and structured content, but imported files
and external-AI output should still be treated as untrusted input. A dependency
audit reports known package advisories; it is not a source-code audit,
penetration test, certification, or guarantee that the application is secure.
