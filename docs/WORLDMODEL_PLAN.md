# PixelWorld: current I2V world-model evaluation plan

Scope decision: updated 2026-11-09. The active study concerns image-conditioned world
continuation and interactive world evolution. Visual puzzle solving and video
reasoning leaderboards are outside the current experiment plan. Earlier T2V,
audio and reasoning explorations remain historical records.

Current capability map:

| Group | Benchmarks | What the generation should demonstrate |
| --- | --- | --- |
| Spatial scene evolution and control | WorldScore; WBench | WorldScore emphasizes camera motion, parallax, new scene content and disocclusion. WBench emphasizes action-conditioned navigation and consistency across interaction turns. |
| Embodied prediction | WorldArena; RoboJudge shared-50 | Robot-world continuation and manipulation/action outcomes, respectively. |
| Physical continuation and state evolution | Physics-IQ Verified; PVBench | Reference-experiment spatiotemporal agreement and physical/geometric/state dimensions, respectively. Physics-IQ remains the quantitative anchor. |
| Visual quality and camera adherence | VBench-I2V (`vbench2_beta_i2v`, part of VBench++) | Subject/background fidelity, camera control and six video-quality dimensions. Its I2V leaderboard is distinct from VBench-2.0 physics scores. |

PVBench is a supplemental candidate, not a completed smoke run. Principia is
excluded from subsequent experiments by the user's 2026-11-09 decision.
PVBench's complete official inputs and evaluation resources remain unconfirmed
in the existing resource audit. The matching public suite is VBench-I2V;
no official VBench-2.0 I2V physics-score setting was established.
MORPHEUS remains a reserve candidate for motion equations/invariants. See
[PHYSICS_BENCHMARK_CANDIDATES.md](PHYSICS_BENCHMARK_CANDIDATES.md).

AVGen-Bench is excluded from subsequent experiments by the user's 2026-11-09
decision. WorldModelBench is also excluded following the earlier decision about
evaluation reliability. Preserve their old smoke videos and records. This map
organizes capability coverage; it does not launch every benchmark or expand the
old ten-group matrix. Future generation uses the Codex harness with the custom
TRAE model routes; the orchestration migration is separate from this selection.

Formal comparisons run the complete selected official evaluation setting and
reuse its published baseline scores. No self-selected case subsets or baseline
reruns are scheduled. Generation and scoring smoke may use a few cases solely
to validate the pipeline; those are not formal benchmark results.

## Mandatory admission criterion: published frontier-model scores

The user reiterated this requirement on 2026-11-09: a benchmark enters the
formal suite only after we find traceable, already published scores for relevant
frontier video/world models under the matching official I2V or interaction
setting. The existence of an evaluator, old model rows, or our successful
generation smoke is insufficient.

Before new benchmark generation, prepare a baseline evidence table containing:

- Exact baseline model name/version, reported score and metric.
- Public source URL: leaderboard, paper/table or a documented published evaluation.
- Complete evaluated case set, input setting, prompt version and evaluator/judge version.
- Aggregation and trial count, plus output settings and any protocol-permitted differences.

We run and score PixelWorld only. Do not generate baseline videos, rerun baseline
models, rescore public baseline videos, or train a substitute baseline. If a
matching frontier-model score cannot be established, omit that benchmark from
the formal comparison; do not resolve the gap by spending resources on baseline
reproduction. All benchmark names in the capability map are conditional
candidates until this evidence gate and resource/protocol checks pass.

**Sampling policy: follow each official setting.** Physics-IQ cases are
submitted once per model/Track configuration. No Physics-IQ four-run aggregation
is scheduled. Physics-IQ Verified explicitly accepts single-run results in its
[official aggregation section](https://github.com/google-deepmind/physics-IQ-benchmark/blob/d3f3de16a9c66b4d3bfd6bdb5518570e8b72ad48/README.md#g-aggregate-leaderboard-scores);
four independent runs are recommended rather than mandatory. Report our score
as `single run`, without inventing a across-run standard deviation. Keep the
published baseline's reported mean/std and repetition count clearly labelled.
VBench-I2V instead mandates **five independent samples for each of1,118pairs**;
its prepared full configuration retains that requirement. Those samples are
not code revisions or infrastructure retries. Do not reduce them to one sample
or copy an output five times. Other settings retain their own declared sampling
and aggregation requirements; unresolved published scope stays a comparison gate.

Autonomous program revisions within one case remain allowed; they are not
independent benchmark runs. Save candidate history and submit the final valid
output, without evaluator-driven best-of-N selection. Infrastructure recovery
attempts remain separately recorded under the existing attempt policy.

The generation agent receives an initial RGB image and the official task text;
additional controls/history are supplied only as permitted by that benchmark.
It writes executable code that produces RGB frames, with autonomous inspection
and revision. The core harness and its two active capability Tracks remain
unchanged. Text is numerically conditioned I2V; Vision-Agent has visual access.
Legacy three-Track Physics-IQ runs continue under their frozen v1 protocol.

## Proposed primary suite

| Benchmark | Capability | Proposed scope | Existing evidence / next requirement |
| --- | --- | --- | --- |
| [Physics-IQ Verified](https://github.com/google-deepmind/physics-IQ-benchmark) | Physical continuation: falling, collision, support, material motion | Reuse one complete 198-case run per selected configuration | GPT-5.6's three legacy groups have official single-run scores; the larger matrix continues. No four-run expansion is scheduled. |
| [RoboJudge shared-50](https://github.com/Sphere-AI-Lab/RoboJudge) | Embodied grasping, moving, placing and opening; physical adherence and instruction alignment | All 50 original generation tasks | The 50-input manifest and one generation smoke exist. Verify the original generation-prompt versions, published score scope and PA/IA judging recipe before comparison. |
| [WBench](https://github.com/meituan-longcat/WBench) | Camera/action control, scene consistency and multi-turn continuation | Official Full: 289 cases / 1,058 interaction turns, if selected | One complete four-turn generation smoke exists. Compare only with published Full scores under the correct judge/protocol. Navi 158 is a separate official setting and must not silently replace Full. |

WBench supplies intervention and repeated-control coverage. Physics-IQ and
RoboJudge cover physical continuation and manipulation. Select whole benchmarks according to the claims and budget;
do not reduce a formal benchmark to hand-picked easy or attractive examples.

## Reserve, not default expansion

| Benchmark | Added coverage | Reason to defer |
| --- | --- | --- |
| [WorldScore](https://github.com/haoyi-duan/WorldScore) | New scene content, camera motion, parallax and disocclusion | Full suite has 3,000 cases; the 400 three-transition cases increase generation work. If selected, run the whole chosen official setting and compare its matching published score; no custom 10-case result. |
| [WorldArena](https://github.com/tsinghua-fib-lab/WorldArena) | Robot-world video prediction | Confirm the complete official text-driven test manifest and video-quality scoring scope first. A validation-episode smoke is not a leaderboard result. The 5-policy × 500-episode recipe is a separate functional policy evaluation, not automatically the I2V video-quality workload. |
| MemoBench / iWorld-Bench | Hidden state persistence / further camera and memory controls | Consider only after confirming a manageable complete official setting, released scorer and matching reported baseline scores. |

MME-CoF-Pro, VBVR-Pro, TC-Bench visual-reasoning studies, WorldModelBench,
AVGen-Bench and new T2V/T2AV experiments are not scheduled. Audio may be
revisited only as an explicit future scope decision.

## Cost and comparison policy

Use one predeclared primary model for the new suite. Count generated segments,
not only episodes: a four-turn WBench episode costs four generations. Control
cost by choosing smaller complete benchmarks, reducing the number of coding
agents/Tracks, or deferring an entire large benchmark. The previous ~100-segment
custom-subset allocation is withdrawn.

Reuse already published scores from traceable evaluations using the official
protocol; relevant frontier-model comparison rows are mandatory. Do not schedule baseline generation
or rescoring. For every reference row, record dataset revision, complete case
set, I2V setting, prompt/generation recipe, evaluator and judge version,
aggregation, and failure handling. If that row cannot be matched, leave it out
of the direct comparison rather than claiming official comparability.

Use the output conditions permitted by the official protocol. Native model
outputs need not be identical in every detail when the benchmark explicitly
allows different settings. A custom duration, crop, low-FPS recipe or different
judge is not made official simply by passing the evaluator's input parser.
Report actual output resolution, FPS, duration and trials with each result.

Do not automatically multiply every benchmark by the old ten-group matrix.
Any formal model/Track comparison also uses the complete chosen setting.
Budget/FPS/resolution experiments remain a separate future decision; no
sampled sweep is scheduled by this plan. Their methodology is described in
[EFFICIENCY_PROTOCOL.md](EFFICIENCY_PROTOCOL.md); hard token-budget enforcement
and refinement-effect measurements are not claimed as implemented.

Generation smoke is not official metric validation. Complete each new
benchmark's scoring smoke and output-wrapper checks before claiming formal
scores. Data, masks, reference continuations and scores remain outside the
generation workspace. Preserve valid weak outputs and all recorded candidates.

## Research purpose

The study should test whether a coding agent can infer and continue unfamiliar
visual worlds, retain appearance and spatial structure under control, and
produce coherent physical and embodied dynamics. Existing program-generated
visual-reasoning results are related work, not the main claim of this suite.
Neither additional benchmark names nor RGB storage formats alone establish a
new algorithmic contribution.
