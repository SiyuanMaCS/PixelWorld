# Main output specifications and controlled ablations

Plan 2026-11-09. This document separates official-score experiments from capability diagnostics. No FPS/resolution sweep has been run by this plan. Published comparison rows and protocol evidence are in [FRONTIER_BASELINE_AUDIT.md](FRONTIER_BASELINE_AUDIT.md).

## Main benchmark runs

| Benchmark | Proposed primary output | Complete official workload | Boundary |
|---|---|---|---|
| Physics-IQ Verified | Keep existing **256×144, 4 fps, 20 frames / 5 s** for missing-model generation | 198 cases per model/Track, one accepted run | Reuse completed old-protocol results. Export/normalize with the pinned official evaluator; label actual native/output and evaluation FPS. No four-run expansion or SOTA variance claim. |
| RoboJudge shared-50 | Begin with existing **width 256, aspect ratio preserved, 4 fps, 20 frames / 5 s** | 50 original tasks per model/Track | The paper specifies judge inputs at 4 fps with at most 32 frames, not one common generator duration. Freeze prefix construction and disclose native baseline output differences. Smoke can test 512-wide if 256 output is visually inadequate; do not silently change a completed cohort. |
| WorldArena Track 1, text-driven | **640×480, 24 fps, 121 frames / 5.0417 s** | Complete March6 submission: **1,000 originals +2,000 official instruction variants =3,000 videos/configuration**. | Dataset card explicitly requires variants. One original TEST episode completed; its RGB format success is not scoring success. The public board averages15 fields, while full local pipeline adds Action Following. Published rows do not disclose test/GT coverage, and the input archive lacks GT videos; reconcile these before claiming a comparable official Total. |
| VBench-I2V | Working smoke: **256×144, 16 fps, 81 frames / 5.0625 s**, official 16:9 crop. Proposed primary default: the same, pending scoring smoke | 1,118 pairs × 5 samples = 5,590 videos per configuration | Its protocol allows model default/best resolution, but requires the official image suite and five samples. Upstream explicitly permits each model’s default/best resolution. These values are PixelWorld’s declared defaults, not a claim that all baselines were rendered at 256 pixels or 16 fps. Preserve official timing/decoding and report each baseline’s native configuration where public. Five outputs cannot be copies of one result presented as independent samples. |
| WBench Full | Provisional **width256, original aspect, 4 fps, 20frames /5s per turn**; freeze only after an original-judge smoke | 289 cases / 1,058 turns | Current first-turn input is256×143. Each next turn receives the preceding generated last frame. Match original judge and naming/export pipeline. Published Full comparison is blocked on original judge availability. |
| WorldScore | Smoke: **256×144, 10 fps, 50 frames/segment** with the exact official crop and controls | Static: 2,000 cases / 2,800 segments. Dynamic overall: Static + 1,000 motion cases = 3,800 segments | One-segment output occupies5s. Three-segment output drops repeated anchors and contains148frames /14.8s; index80 generation/export are complete. Scoring is still pending resources. Full Dynamic includes Static dimensions, not just motion metrics. Frontier-row native specs/full-scope provenance remain unconfirmed. |
| PVBench I2V | Paper specifies **720p, 24 fps, ~240 frames / 10 s** | 600 groups | Blocked until complete resource/protocol bundle is established. Do not substitute 256-wide/4-fps/5-s outputs and call them the paper's controlled specification. |

For each exported result record input dimensions, native generated dimensions/FPS/frame count/duration, any encoding/resampling, evaluator revision, and judged case/sample count. Generate explicit RGB first; MP4 is an evaluation/export container. The saved program remains runnable. Keep all weak-but-valid outputs and candidate history.

## Minimal resolution/FPS diagnostic design

Use **GPT-6.1-Sol** first, one fixed protocol and 50k cumulative output-token budget. This is a diagnostic cohort, not a sampled official leaderboard. Do not run every model and benchmark across the grid.

1. Start with three specifications: **256×144 / 4 fps**, **512×288 / 4 fps**, **256×144 / 8 fps**, all 5 seconds. Use a small predeclared set of scenes with solids/contact, optical detail and fluid/material change.
2. If those are informative, vary FPS at fixed resolution: **2, 4, 8, 16 fps**, giving **10, 20, 40, 80 frames** over 5 seconds.
3. Vary resolution at fixed 4 fps: **128×72, 256×144, 512×288, 1024×576**, always 20 frames. Treat the last setting as a limit probe; no blanket assertion that it succeeds.
4. Across all points keep source image, task semantics, model, tool/harness settings, token budget and autonomous review policy fixed. Freeze selection before inspecting scores; store input hashes and task versions. Existing v1 scores remain reusable main results, but do not attribute a v1/TRAE → v2/Codex change to FPS/resolution alone.

The three-point smoke precedes any larger cohort. A possible first expansion is 6 scenes × 3 points = 18 runs on one Track. A later Text/Vision comparison should use the same selected scenes, rather than automatically multiplying all benchmarks by both Tracks and four models. These analysis runs are not yet scheduled.

The expanded one-factor design has **seven unique points**:128/256/512/1024-wide at4FPS, plus256-wide at2/8/16FPS. The256-wide/4FPS anchor is counted once. Six scenes × seven points × two tracks = **84 independent videos**, including the initial18 if their frozen protocol matches. No full resolution×FPS factorial sweep is proposed. Report paired per-scene changes, with scene as the statistical unit; this diagnostic cohort does not replace the complete official198-case main benchmark.

## Avoid confounding output resolution with input perception

In ordinary I2V, `first_frame.png` has the target output size to satisfy the exact-first-frame rule. Changing resolution therefore changes both observed image detail and rendering demand. Call the main grid **end-to-end resolution sensitivity**, not a pure output-only causal effect.

A separate diagnostic can freeze a high-resolution conditioning image across all points and require output frame 0 to equal its declared deterministic resize. That needs a clearly named analysis input contract; it is not silently applied to official runs. It can separate input-detail effects from output-grid effects after the minimal grid shows a signal.

## Measurements and interpretation

- Delivery: valid/runnable result rate, actual frame count, interruptions and retained output at budget cutoff.
- Generation: visible geometry/material/texture, newly exposed regions, contacts/occlusion, event order and text/control adherence.
- Physics: official per-case/component scores with their stated preprocessing; score changes are not automatically evidence of better physical understanding.
- Appearance: per-video/per-candidate image quality; distribution metrics need the same complete cohort and reference distribution.
- Refinement: saved candidate count, code vs RGB changes, observed visual-tool use, first/final quality and tokens spent after first valid output. Do not infer review counts from snapshot counts.
- Efficiency: reported input/output/reasoning details, inference request ledger, generation execution count and CPU rendering time. Wall-clock latency remains supplementary because API queueing/rate limits vary.

Do not infer a universal resolution limit from one failed run. An executable program can expand many pixels with little additional model text. Distinguish (1) delivering the requested shape within budget, (2) execution memory/time at that shape, and (3) achieving additional visual or physical detail. The operational limit is the tested quality/cost boundary under this frozen model, task and budget, not a maximum number of RGB values the language model can write.

For diagnostic temporal comparisons additionally sample outputs on predeclared common physical timestamps using a deterministic non-learned rule. State whether frame hold/nearest selection was used; it does not recover absent motion. Keep official-score preprocessing and diagnostic resampling separate. Check for static/duplicated-frame metrics that reward low motion rather than correct event completion.

## Observations motivating the grid (current smoke, not aggregate conclusions)

- RoboJudge robot-toaster case: 6.1 Sol and 5.6 Sol both represent grasp, transport and insertion, but the synthesized bread/arm appearance differs from the input photograph. More pixels alone may not fix this representation choice. The paired resolution diagnostic must also record whether source pixels are copied/warped or appearance is redrawn.
- VBench animal case 872 has a descriptive prompt (a bear in water with a fish), rather than a required large action. The first saved outputs mostly preserve the scene with small motion. High subject similarity therefore needs to be read alongside dynamic degree and actual motion, rather than treated as action success.
- Physics-IQ case 0008 with Flash completed and scored through the official per-view functions. Its weighted spatial IoUs are about 0.276/0.297, while the time-aligned overlap falls to zero after early frames. This is one view, not a Verified score; it illustrates why spatial appearance and event timing must be separated.

The native self-review policy and 50k cumulative output-token ceiling remain fixed at every analysis point. The above observations were made by the external researcher and are not sent back to generation agents.

## Report frame timing without ambiguity

The current RGB player uses frame hold: N frames at F fps occupy N/F seconds, with sample timestamps 0 through (N−1)/F. Thus Physics-IQ 20/4 occupies 5 seconds but its last sample is at 4.75 seconds. VBench 81/16 occupies 5.0625 seconds and ends with a 5-second sample; WorldArena 121/24 occupies 5.0417 seconds and ends with a 5-second sample. Do not silently call all three “exactly five seconds” in exports. Follow each official loader’s interval semantics and preserve native FPS/frame count in manifests.

## Feasible main-table selection before full dispatch

- **Physics-IQ Verified** is the primary quantitative anchor: identified full198 input/evaluation setting, direct published frontier comparison and substantial reusable PixelWorld results.
- **RoboJudge shared-50** is the compact semantic/embodied complement, after exact-checkpoint scoring smoke and published common50 averaging provenance are resolved. Keep PA and IA separate.
- **VBench-I2V** is operational, but its full requirement is5,590 videos per configuration (44,720 for fourmodels/twotracks). Its metric functions may also be used on Physics-IQ for labeled appearance/consistency analysis, which is not a VBench-I2V leaderboard score. Do not silently turn a diagnostic subset into a full benchmark.
- **WorldArena** full local protocol requires3,000 videos/configuration plus its metric stack and export reconciliation; retain the current one-episode demonstration while those gates remain open.
- **WBench/WorldScore** are protocol-audited candidates with complete-case diagnostic adapters and explicit resource/provenance gates. PVBench is blocked on full release. Do not launch expensive full generation merely because a public baseline number exists.

For multi-turn tasks, the current clean Codex unit is one generation segment. Each segment has a50k cumulative output-token ceiling across requests/recovery; a multi-segment case therefore has the sum of its segment budgets and usages. Report both per-segment and per-case totals. This must be declared before formal comparison; never describe a three-segment case as capped at50k total under the current implementation.

## Exact Physics-IQ temporal evaluation path

The pinned official runner calls `get_video_fps(input_folder)`, then `ensure_real_videos_at_fps(fps, ...)`, deriving reference clips from the official30FPS originals when required. `process_videos` considers the first `5*fps` frames. It does not impose one universal evaluation FPS across generators. Our current native4FPS outputs are evaluated on the corresponding4FPS reference grid; this is the official adaptive-FPS procedure. Keep this fact in the main table caption when comparing published native-model rows.

For the FPS diagnostic, report both (a) that native official path and (b) a declared common30FPS evaluation grid, obtained by deterministic frame hold from each PixelWorld candidate. The latter is a diagnostic to separate sampling-grid changes from generated-dynamics changes; it is not extra baseline generation/scoring and does not recreate absent intermediate motion. Both paths retain the same GT/evaluator pins.

WorldArena has an additional scope distinction still to finalize: the public board computes15 base fields and omits Action Following, whereas the local16-indicator full pipeline adds two instruction-variant generations. Do not assert that3,000 videos are mandatory for the published15-field score until that submission requirement is established. Record1,000 original videos and the2,000 Action Following variant videos separately.

The March6 dataset card has now been verified to require all3,000 for its complete submission. Its association with the published15-field baseline rows remains unverified; older paper experiments use500test episodes, and the pinned1,000-episode input archive contains no GT videos. This gate concerns matching published results, not whether original-only inputs can technically feed15metric functions.

## Delivery failures under the fixed budget

Keep failed cases, their complete exposed traces and consumed tokens. A50k after-request ceiling can overshoot by the final returned request; it is not a wall-clock deadline. A case that never saves a verifiable candidate is a delivery failure, not a zero-quality video. A preserved valid candidate is eligible under the existing final-submission validation, without choosing it by evaluator score. Never reset an exhausted case's budget to manufacture a passing smoke.

Report valid-delivery counts for the complete requested scope. If the official evaluator requires all198 or all1,118×5valid videos, missing outputs prevent a complete official score. Do not omit failed cases, duplicate another video, or invent a placeholder/zero-score policy. Any later change in failure handling requires a separately declared protocol; existing experiments and their budget failures remain intact.
