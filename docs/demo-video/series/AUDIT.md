# DLMS-138 source and design audit

The repository was clean on `main` at the start of this task. No branch was
switched. AGENTS.md governs the work. This pass adds documentation/tooling only;
it does not change the application, APP_VERSION, release metadata or overview.

## Infrastructure reused

| Source | Existing contract used by the series |
|---|---|
| `tools/build_demo_video.py` | Stable scene IDs, ffprobe/PCM validation, whole-frame timelines, SRT, loudness normalization, lossless static rendering, safe temporary intermediates, selectable captions |
| `tools/generate_demo_narration.py` | Local-only Kokoro HTTP adapter, synthesis-only pronunciation, validated WAV publication, text/voice/speed/hash sidecars |
| `tools/capture_demo_video_screenshots.py` | Firefox capture lifecycle, scene recipes, original fixtures, focus/ready checks, Purple & Gold 1080p device scale 1 |
| `tools/demo_video_fixture.py` | Original quizzes, deliberate duplicates, question evidence, scope exclusion, generated-review lifecycle, pack data and original service diagram |
| `tools/capture_user_manual_screenshots.py` | Shared browser/server cleanup and viewport infrastructure; manual assets remain separate |
| Overview narration and three capture manifests | Protected original scene/image identity; the series reuses images without changing the overview script |
| Overview README, final-candidate and delivery records | No chapter fades, no geometric resampling, lossless review master distinct from CRF 18 delivery |
| Overview publishing documents | Real hosted overview and publishing handoff; no automatic upload |
| Existing video/narration/capture tests | Main/long/audition compatibility, pronunciation, WAV contract, static-frame equality and fixture boundaries |

The only shared renderer API extension is an optional `known_scene_labels` set
for `audio_inputs`. Its default remains the overview's exact original label set.
The series passes its own per-video labels; it does not relax the overview's
unknown-audio rejection. Capture adds a separate opt-in recipe tuple and flag.

## Editorial source checks

The manual table of contents, feature inventory, screenshot inventory, terminology
and relevant chapters were inspected. Particular decisions were checked against
these current application boundaries:

| Subject | Implementation inspected | Consequence for the script |
|---|---|---|
| PDF and OCR | `dlms/routes/pdf_import.py`, PDF bank persistence, review and generator templates | OCR returns drafts; missing answers require verification; saving a bank precedes generating a quiz |
| Study/Exam/Pause | `static/script.js`, `dlms/rendering/quiz_artifacts.py`, quiz editor | Study is untimed; Exam suppresses immediate feedback; Pause covers the assessment and stops countdown progress |
| Question types | Quiz runtime and matching/hotspot fixture recipes; manual chapter 6 | Matching supports alternative controls; hotspot answers select image regions; no claim of choice-only AI tools on those types |
| Daily review | Learning routes, `daily_review.py`, `learning_scope.py`, `question_review.py`, runtime Finish Review handling | Recommendations depend on evidence and active scope; generated copies credit sources; explicit completion is not deletion |
| Library | Library template/routes, duplicate services, manual chapter 5 | Folder placement, visibility, Smart Views and learning eligibility are distinct; duplicate suggestions do not authorize automatic deletion |
| Packs | Content Pack routes, Study Pack generation routes, catalog template | Management and learner catalog use the same installed sources; structural validation is not subject-matter verification |
| Portability | Bundle routes/service, restore service, manual chapters 15/17 | Preview before publish, rename instead of overwrite; bundles exclude personal learning history and interactive hotspots |
| External study | Manual chapters 12/14 and overview assets | Provider handoff and paper layout need their own future capture work; do not pretend current overview frames teach those entire workflows |

## Why six videos

The viewer leaves each candidate able to make a decision or finish a task. The
import tutorial ends at reusable bank generation; Study/Exam contrasts the same
questions under different feedback rules; daily review reaches acknowledged
completion; organization separates four easily confused controls; Packs connects
source data to an activity; portability shows the last safe preview before import.

Static scenes deliberately remain on screen for an explanation. Repeated frames
in the Packs and portability scripts hold the relevant controls while a second
decision is explained; they are not filler transitions. No cursor animation,
zoom, pan, native print dialog or live browser recording is required.

The four new captures are produced through real isolated application flows.
The repaired Question Bank uses an author-supplied answer to synthetic material;
no OCR accuracy claim is made. The bundle preview comes from a real exported
synthetic quiz and staged import, leaving publication unconfirmed. No user data,
commercial question bank, certification branding or external image is used.

## Maintenance boundaries

Definitions include both manual and implementation references. They describe
which videos should be reviewed after a feature change; the metadata does not
claim to detect every semantic change automatically. Hash checking catches
changed accepted screenshots and stale audio, not an unrecorded UI change.

No production UI adjustments were made for capture. Existing overview captures
stay historical and protected. New UI revisions can receive series-specific
capture IDs without invalidating the published overview.

No framework, model dependency, cloud TTS, background service manager or publishing
API was introduced. Local services remain explicitly started by the operator.
