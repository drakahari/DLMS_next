# DLMS-146 — Storage growth and capacity audit

The data-root definitions are in `app.py`; schema ownership is in
`dlms/persistence/database.py`. Storage health is an explicit, read-only action
in Settings → Backup & Restore. No formats, quotas, retention or cleanup policy
changed.

| Store | Growth and existing management |
| --- | --- |
| `results.db`, journals/WAL | Canonical quizzes/questions/choices/matching, attempts/answers/missed questions, concepts and learning events. Continued study and creation can grow indefinitely. Quiz deletion, Clear History and scoped resets delete relevant records; no automatic history retention or file-shrinking VACUUM. |
| `config/`, `data/`, `quizzes/` | Settings/registry and generated playable JSON/HTML. New and Generated Practice quizzes accumulate. Finish Review is presentation state, not deletion (`generated_practice_lifecycle.py`). Quiz deletion and scoped resets provide cleanup. |
| `content_packs/`, `quiz_assets/`, `static/`, `law/` | Installed pack datasets, study images, custom artwork and Law content. User-driven imports/creation can accumulate; uninstall/delete/source reset have deliberately different scopes. Study Packs use installed Content Pack datasets, not a second full store. |
| PDF question/terminology banks, image/PDF drafts | Persistent source banks and review drafts can accumulate. Import workflows clean selected completed work; source-content reset exists, but there is no general size/age retention manager for these persistent stores. |
| `external_ai_drafts/` | Bounded stale cleanup uses a 24-hour cutoff in `external_ai_drafts.py`. |
| `uploads/`, `content_pack_staging/` | Request-owned import/install scratch data has success/failure cleanup. OCR screenshot and PDF services have seven-day stale-task cleanup. Cleanup is workflow-triggered, not a continuously running guarantee. |
| `backups/` | Every manual/safety backup retains another ZIP. Older backups/uploads are excluded from snapshots, preventing recursive backup growth. No pruning/deletion manager; UI lists only five newest. Browser downloads may duplicate ZIPs outside the data root. |
| `backups/restore_staging/`, `.restore_operations/`, publication work | Restore cancel/completion cleanup, 24-hour owned validated-stage cleanup, journal-guided startup reconciliation. Incomplete recovery resources are deliberately retained. Do not treat them as disposable clutter. |

The largest practical risks are repeated full backups and media-heavy imports:
ZIP creation, SQLite snapshots in the OS temp directory, PDF rasterization, pack
extraction and restore safety/staging copies require space beyond final data
size. Ordinary SQLite writes can also fail when any other process fills the disk.
Backups and restore are the targeted preflight boundaries in this change; imports
and pack installation retain existing transactional/error behavior.

A separate pre-existing capacity concern: backup creation does not impose the
restore upload/validation limits. Restore currently accepts at most 298 MiB
uploaded ZIP, 2 GiB expanded data, 768 MiB per file and 20,000 files (`app.py`).
A sufficiently large locally created backup can exceed these restore limits.
These are security boundaries, not SQLite limits; they were not weakened in
DLMS-146. **Resolved by DLMS-147:** creation now checks the finished ZIP against
the upload cap and the actual restore validator before publishing it. Larger
workspaces remain usable, but cannot produce a supported full backup until the
snapshot fits. A future large-workspace backup format/path would need its own
resource/security review. DLMS-149 subsequently raised only the restore ZIP
upload allowance to 1 GiB; see [the capacity audit](DLMS-149-backup-capacity.md).

SQLite's size ceiling is not a realistic single-user DLMS constraint. Current
SQLite permits up to 4,294,967,294 pages (about 17.6 TB at 4 KiB pages, up to
281 TB at 64 KiB); build/version limits can differ. Disk capacity and working
space become relevant far earlier. No database scan, count, pragma mutation or
VACUUM was added. Source: [SQLite limits](https://www.sqlite.org/limits.html).

## Guardrails and limits

- Explicit size scan: 50,000 entries / 0.5 seconds, no followed symlinks, partial
  results labeled. Logical lengths count hard-link names separately; concurrent
  writes, filesystem blocking calls and mounted subdirectories limit precision.
- Free space: data-root filesystem, with unavailable status on OS errors. Low
  below 2 GiB, or below 5% and 10 GiB; critical below 512 MiB. Healthy large disks
  are not warned merely for having a low free percentage.
- Backup: estimate uncompressed inventory plus two database sizes (including WAL)
  and 2% overhead on the backup drive; independently check OS temp for the DB
  snapshot. A shared-volume estimate includes both simultaneous outputs.
- Restore: after upload validation, check twice the archive's validated expanded
  size before extraction. Repeat at confirmation. After making the safety ZIP,
  before live mutation, check incoming bytes plus twice the safety snapshot for
  publication/recovery working room. Recovery/rollback itself has no new gate.
- Each preflight leaves 256 MiB headroom. Estimates are conservative, not space
  reservations. Unknown free space fails open to existing safe failure handling.
  Restore upload spooling occurs before these checks. No automatic data deletion.

Potential follow-up: a deliberate backup inventory/removal workflow with sizes,
dates and protection for active recovery resources. Also consider applying
validated expanded-size estimates at pack/install and OCR boundaries. Neither is
implemented as implicit destructive cleanup here.
