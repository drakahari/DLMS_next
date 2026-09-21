# DLMS-149 — Backup/restore capacity policy

## Recovered history and decision

| Boundary | Origin / rationale | Classification | Final decision |
| --- | --- | --- | --- |
| 298 MiB uploaded ZIP | `26ec547` explicitly reserved 2 MiB framing beneath the existing general 300 MiB request limit. No backup workload measurement was recorded. | HTTP constraint / conservative default | **1 GiB ZIP**, with 2 MiB multipart allowance on the two restore POST routes only. |
| 2 GiB expanded content | `74212a6` introduced the value with the initial backup/reset implementation, without a quantitative rationale. Later `d42dfdc` enforced it before CRC decompression. | Resource safeguard, now part of ZIP security | Retain: limits decompression work and several simultaneous staging/recovery copies. |
| 768 MiB individual member | `74212a6`; no measured rationale recovered. Restored JSON and pack metadata can be parsed into memory, unlike streaming archive copies. | Resource / memory safeguard | Retain; increasing it is not justified by streaming media benchmarks. Includes `results.db`. |
| 20,000 ZIP entries | `74212a6`; `d42dfdc` extended checks to directory entries before decompression. | Metadata / filesystem-work safeguard | Retain, including the manifest and directory entries. Many small generated quizzes can reach it before byte ceilings. |
| 2 GiB compressed member sum | `d42dfdc`, separate from expanded size. | Resource/security boundary | Retain independently; HTTP ZIP cap also counts headers/central directory. |
| 1000:1 ratio at 16 MiB | `d42dfdc` added per-member and whole-archive checks before `testzip()`. | ZIP-bomb protection | Unchanged. Even locally created unusually compressible data must pass. |

`77aeff0` (DLMS-147) made creation use the restore validator and upload cap before
publishing. That contract remains: there is no trusted-local bypass. Validation
still rejects unsafe paths, links/special files, duplicates, root collisions,
invalid manifests and CRC failures. No application/database quota was added.

## Representative measurements

Fedora development host, Python virtual environment, 2026-09-21. Three sequential
temporary workloads used a fixed-seed random 1 MiB block, repeated in files no
larger than 512 MiB. DEFLATE cannot exploit repeats outside its window, giving
media-like, poorly compressible data. Each case used the existing backup creator
(with candidate 1 GiB allowance), actual restore ZIP validator and extraction
helper. No real user data was used. Inputs and outputs were deleted after each
case. These are archive-path measurements, not full semantic restore benchmarks
or browser upload/network timings; synthetic binary assets were not presented
as validated study content.

| Source MiB | ZIP bytes | Creation including validation (s) | Revalidation (s) | Extraction (s) | Process peak RSS KiB | Source + ZIP + extracted bytes |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 300 | 314669392 | 3.541 | 0.131 | 0.082 | 54436 | 943814992 |
| 500 | 524448597 | 5.920 | 0.214 | 0.148 | 54436 | 1573024597 |
| 1023 | 1073021361 | 12.198 | 0.472 | 0.308 | 54436 | 3218407857 |

RSS is the process high-water mark including application import, not a per-stage
allocation trace. The cached local filesystem makes these timings optimistic
for slower drives. The largest case uses 1023 MiB source to leave ZIP overhead
below 1 GiB. No multi-gigabyte fixture is needed to verify rejection boundaries:
tests use scaled limits and declared request sizes, while retaining the actual
validator and multipart parser.

## Growth and resource implications

Image-heavy packs and accumulated quiz assets are most likely to hit the old
298 MiB cap first. Repeated backups are excluded from new ZIPs, though they reduce
free space. Temporary uploads/OCR staging are excluded; persistent source banks
and drafts count. Study Packs reuse Content Pack datasets. Many generated quiz
files can hit the entry ceiling; long history can eventually hit the database's
768 MiB single-member ceiling. Those limits remain visible through the DLMS-147
failure path rather than producing an incompatible backup.

The 1 GiB upload cap remains fixed regardless of drive capacity. Flask 3.1's
request-local ceiling is set **before CSRF/form parsing**, including for streamed
requests without Content-Length. Existing form-memory/part-count restrictions,
bounded file copying and unrelated route limits remain unchanged. Both current
and legacy restore routes share `BACKUP_UPLOAD_MAX_BYTES`; the global 300 MiB
ceiling is not raised. Reverse proxies may have smaller limits/timeouts.

DLMS-146 free-space preflight is unchanged. Staging may temporarily hold the
multipart spool, saved ZIP and expanded semantic-check copy; confirmation also
needs the safety backup, incoming files and rollback working room. A 1 GiB ZIP
expanding to 2 GiB can therefore require several GiB of additional free space.
The backup/temp-drive and restore checks retain 256 MiB headroom and can reject
an operation even below the fixed limits. They are estimates, not reservations;
initial HTTP spooling precedes restore preflight and concurrent writers can still
consume space. Unknown free-space information retains normal failure/recovery
handling. No new dynamic sizing or automatic cleanup was introduced.

## Remaining limits

Full semantic validation may allocate substantially more memory than raw file
size for JSON or decoded images. Workspaces beyond the retained expanded,
individual-file or entry bounds need a separately reviewed streaming/chunked
backup design, not simply higher constants. Validation and restore remain
synchronous. Proxy/network timeout qualification and native low-memory testing
remain deployment-specific; this audit does not claim those benchmarks.
