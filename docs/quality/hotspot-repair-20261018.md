# Hotspot preservation and marking — review candidate

Status: implemented and focused validation passed; independent Astra review and owner acceptance remain pending. No commit, push, release, installed replacement, historical recovery or migration is included.

Baseline: public `drakahari/DLMS_next` main `12c202920f45219cc13ae7c4cca940c938bd7aab`, verified before creating `fix/hotspot-preservation-marking-20261018`. This is an isolated task worktree; existing Desktop packaging changes and the original audit are preserved. Findings ledger: [workflow-findings-20261018.md](workflow-findings-20261018.md), [JSON](workflow-findings-20261018.json).

## Applicability and reproduction

**F1 and F2 are shared application defects**, not Qt-only behavior. Before editing, the original browser application on this public baseline was exercised through Flask's real HTTP routes with the same synthetic pack as the original audit. Fresh mark context returned409; Rebuild All changed the runtime hotspot objects into choice objects. Both assertions failed and their complete output was retained. The later Firefox workflow uses the real application server and UI with no Desktop host.

The committed synthetic fixture SHA-256 is `01c4ddf76452b95f17d244bba1a62098e3dec5d0a9ace1d966579052ce9f04ce`. It has one original geometric PNG, circle/polygon targets, fictional questions and no profile or history. Windows/Mac and original browser work can use these exact bytes without private evidence.

## Narrow implementation

1. `dlms/routes/study_packs.py`: newly generated image-practice quizzes persist the same media and explanation as their runtime in existing database fields, matching the established image-builder projection. No rows in existing quizzes are rewritten. The unchanged mark service now verifies fresh imported-pack sources; fingerprints, assessment revisions, immutable requests and genuine stale-source rejection remain active.
2. `app.py`, `dlms/services/hotspot_artifacts.py`: only Rebuild All selects the preservation path. It detects spatial runtime/surrogate content, validates question count/order and saved answer/media projection using the mark verifier, validates the existing supported geometry without normalizing it, resolves owned passive images and decodes each required image once. It stages the **exact original runtime bytes** and regenerates HTML. Regular edits retain their existing path; ordinary quizzes retain DB-derived rebuilds.
3. `dlms/services/quiz_mutations.py`: missing/inconsistent spatial content has an explicit item-level failure. Other eligible quizzes can finish; prior files for the refused item remain. Existing staging, registry/profile locks, database read transaction, pair-promotion rollback and cleanup are reused.

The marker is an existing storage convention, not a promise that an arbitrary record can be recovered. Missing, corrupt, media-empty historical, already degraded, unsupported or ambiguous states are refused conservatively. No target is inferred from a title, label or grading surrogate, and no source pack is substituted for the published quiz. Asset bytes and source-pack files are never edited by this repair.

## Focused validation

| Evidence | Result and boundary |
|---|---|
| Before repair, original application HTTP paths | Two new regressions failed: fresh mark409 and hotspot-to-choice conversion. Original audit evidence preserved separately. |
| Final source selection,16 files | **245 passed +90 subtests**, six existing cached_property deprecation warnings. Includes8 new tests, circle/polygon grading, new image-builder projection and ordinary multi-answer controls, exact runtime/DB/registry preservation, saved Study/Exam/marks, retry identity and stale geometry/surrogate rejection. |
| Refusal/failure cases | Missing JSON, invalid JSON/object, invalid/string coordinates, degraded choice payload, changed media, missing/corrupt image, runtime symlink, staging-write fault and second-file promotion fault. Refused items keep prior files; unrelated ordinary quiz rebuilds; publication failure restores the previous pair and leaves history unchanged. Simulated faults, not disk exhaustion/power loss. |
| Final Firefox, real browser application | **2 passed,379 deselected**: new actual pack-generation → correct spatial answers → marks → real confirmation → rebuild → reopen workflow; existing mixed-type mark/selection boundary control. Exact runtime and full DB dumps unchanged across rebuild. No whole-suite claim. |
| Final normal frozen Desktop, Fedora44/COSMIC Wayland | Native selected ZIP → validation/confirmation/install → generation → correct circle/polygon answers and marks → completed Study → rebuild → saved2/2 Exam → repeated rebuild → Dashboard shutdown/alert → separate-process reopen. Original Study/Exam/marks/answer identities and profile/origin exact; asset hashes and runtime bytes exact; correct and incorrect spatial grading after reopen. Application closed orderly. |
| Package provenance | Normal, non-instrumented one-folder payload from pinned Ubuntu24.04 build image. Embedded PYZ/source verified;183 modules,247 assets,8 OCR files; no test modules.458 ELF files,0 Ubuntu24 ABI blockers. This is a separate local candidate, not an updated public artifact. |
| Original evidence | All630 original audit evidence hashes and all audit-report before hashes pass. Published Preview1 AppImage remains SHA-256 `f1693fcc751685d8811c9067f29f25bc677de7676d6e9abf1050bbc3e049c579`. |

Normal-package GUI evidence uses app-local renderer input, exact-process native accessibility and WebEngine diagnostic screenshots. Enabling diagnostic connections causes Qt's diagnostic origin allowance; this does not establish vanilla hostile-content/security or physical keyboard acceptance. No instrumented package or shipped fault hook was used. Windows/Mac native behavior, native Ubuntu/Omarchy, physical input, power loss and real disk exhaustion remain untested in this batch. Full regression suites were not repeated: no shared UI/JS or platform host code changed, and this batch calls for focused regressions.

### Reproduction commands

With the existing supported test environment and disposable temporary directory:

```sh
python -m pytest -q -p no:cacheprovider \
  tests/test_hotspot_preservation.py tests/test_review_marks.py \
  tests/test_atomic_quiz_publication.py tests/test_rebuild_safe_diagnostics.py \
  tests/test_quiz_mutation_atomicity.py tests/test_study_sessions.py \
  tests/test_attempt_validation.py tests/test_medical_study_pack_concepts.py \
  tests/test_image_study_pack_staging.py tests/test_backup_semantic_validation.py \
  tests/test_backup_consistency.py tests/test_image_workflow.py \
  tests/test_publication_reconciliation.py tests/test_quiz_recovery_runtime.py \
  tests/settings/test_maintenance_transition_policy.py \
  tests/completion/test_maintenance_safety.py

DLMS_RUN_BROWSER_TESTS=1 python -m pytest -q -p no:cacheprovider \
  tests/browser/test_critical_workflows.py \
  -k 'imported_hotspot_marks_rebuild or marked_selection_type_counts_and_preview_retry'
```

The Firefox fixture explicitly leaves real confirmation dialogs open for acceptance. Earlier attempts auto-dismissed the rebuild confirmation; no mutation happened in those attempts. Other retained harness corrections: default sandbox refused loopback sockets (authorized run used scoped execution); an initial test omitted Study contract2; an import-cycle collection error was corrected with a deferred import; a normal-package controller referenced a nonexistent readiness variable; another initially mistook the first confirmation for the later shutdown alert. Assertions were preserved. Original logs remain in the private task evidence store, outside this portable handoff.

## Prevention, recovery and review boundary

The fix preserves new/imported hotspot content going forward. It does **not** reconstruct damaged assessments, migrate old records or establish identity-preserving recovery from a source pack. Old unsupported states retain their files and factual history. Draft temporary warning remains in the findings ledger for owner review; it has not been published.

F3 marked-question APKG export, F4 printable POST handling, the documentation corrections and the remaining audit workflows stay open. No other feature repair is included.

Independent reviewer priorities: exact runtime bytes and source/DB projection; genuine stale mark rejection; file/asset boundaries; per-item refusal and pair rollback; history identity; scope of packaged versus source evidence. Linux native evidence is not Windows/Mac acceptance. Those hosts can reuse the synthetic ZIP and source/browser tests, then perform the same new-pack generation/mark/rebuild/reopen steps in their own normal host without importing owner data.
