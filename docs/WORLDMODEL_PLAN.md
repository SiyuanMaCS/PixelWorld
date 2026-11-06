# PixelWorld: current I2V world-model evaluation plan

Scope decision: 2026-11-06. The active study concerns image-conditioned world
continuation and interactive world evolution. Visual puzzle solving and video
reasoning leaderboards are outside the current experiment plan. Earlier T2V,
audio and reasoning explorations remain historical records.

The generation agent receives an initial RGB image and the official task text;
additional controls/history are supplied only as permitted by that benchmark.
It writes executable code that produces RGB frames, with autonomous inspection
and revision. The core harness and its two active capability Tracks remain
unchanged. Text is numerically conditioned I2V; Vision-Agent has visual access.
Legacy three-Track Physics-IQ runs continue under their frozen v1 protocol.

## Proposed primary suite

| Benchmark | Capability | Proposed scope | Existing evidence / next requirement |
| --- | --- | --- | --- |
| [Physics-IQ Verified](https://github.com/google-deepmind/physics-IQ-benchmark) | Physical continuation: falling, collision, support, material motion | Reuse the existing pinned 198-case experiment | GPT-5.6's three legacy groups have official scores; the larger matrix continues. No new generation is scheduled by this plan. |
| [WBench](https://github.com/meituan-longcat/WBench) | Camera/action control, scene consistency and multi-turn continuation | Fixed episodes, initially budgeted at about 40 generated turns | One complete four-turn generation smoke exists. Official Navi has 158 cases. Published HY-World 1.5 videos cover 158 and Kling 3.0 covers 289; choose shared cases and score with one frozen evaluator. |
| [RoboJudge shared-50](https://github.com/Sphere-AI-Lab/RoboJudge) | Embodied grasping, moving, placing and opening; physical adherence and instruction alignment | The original 50 generation tasks, or a fixed 20-task pilot first | The 50-input manifest and one generation smoke exist. Match actual generation-prompt variants and baseline coverage before comparison; run PA/IA judging separately from generation. |
| [WorldScore](https://github.com/haoyi-duan/WorldScore) | Spatial generation, parallax, disocclusion and new scene content | Fixed 10-case spatial subset, e.g. 8 single-transition and 2 three-transition cases | Current generation smoke covers only one easy push-in. Add translation/orbit and genuine new-scene transitions; preserve official last-frame handoff and boundary-frame removal. Baseline subset availability and official scoring still need verification. |

WBench is useful for a common scene under repeated controls. WorldScore adds
explicit next-scene generation beyond the first field of view. This distinction
should determine sample selection, rather than evaluating duplicate camera
tasks merely to increase the benchmark count.

## Reserve, not default expansion

| Benchmark | Added coverage | Reason to defer |
| --- | --- | --- |
| [WorldArena](https://github.com/tsinghua-fib-lab/WorldArena) | Robot-world video prediction | Overlaps RoboJudge and has a heavier pipeline. A text-driven validation-episode generation smoke exists; functional planning/policy success is not established by video quality. |
| [WorldModelBench](https://github.com/WorldModelBench-Team/WorldModelBench) | Broad I2V coverage across seven application domains, 350 cases | Useful if breadth remains insufficient, but adds substantial generation. One I2V generation smoke exists; official judging is not yet run. |
| MemoBench / iWorld-Bench | Hidden state persistence / further camera and memory controls | Verify released inputs, evaluator and matched baselines before choosing a small addition. |

MME-CoF-Pro, VBVR-Pro, TC-Bench visual-reasoning studies and new T2V/T2AV
experiments are not scheduled. Audio may be revisited only as an explicit future
scope decision.

## Cost and comparison policy

Use one predeclared primary model for the new suite. Count generated segments,
not only episodes: a four-turn WBench episode costs four generations. An example
allocation is 50 RoboJudge videos + 40 WBench turns + 14 WorldScore transitions,
about 104 new generations. A 20-task RoboJudge pilot reduces this to about 74.
These are proposals; exact manifests and real turn counts must be frozen first.

Reuse public baseline videos or per-case scores on identical cases wherever
possible. Official subsets with separately reported scores are useful, but a
subset score is never compared directly with a full-set aggregate. Baseline
generation, prompt variants, output conditions, evaluator versions and failed
case handling must be compatible with the claimed comparison.

Do not multiply every benchmark by the old ten-group matrix. Model/Track and
mechanism comparisons can use one smaller matched subset after the primary
suite is fixed. Budget/FPS/resolution experiments follow
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
