# PixelWorld evaluation roadmap

**Current scope (2026-11-06): I2V world continuation and interactive world
evolution only.** See [the current world-model plan](WORLDMODEL_PLAN.md) for the
primary suite, reserve benchmarks and full-official evaluation policy. Formal
scores use complete chosen official settings and published baselines; no
self-selected subsets or baseline reruns are planned. Use the officially
accepted single-run option where available; no four-run expansion is scheduled.
Visual-reasoning,
T2V and audio directions below are historical/reserve context, not scheduled
experiments. Existing run artifacts and the Physics-IQ v1 queue are preserved.

Research framing: [PixelWorld: Coding Agents as Omni Pixel World Models](RESEARCH_DESIGN.md).
This roadmap is the benchmark and protocol inventory supporting that framing.
Budget, latency, cost, FPS and resolution experiments are specified in
[EFFICIENCY_PROTOCOL.md](EFFICIENCY_PROTOCOL.md).

This is a research scope proposal, not a declaration that all adapters are
implemented or that the experiments have run. Physics-IQ has an existing
adapter; every additional benchmark needs an input and evaluator smoke test.
No new generation is launched by this document.

## Research question

How well can a general coding agent generate future visual world states by
writing executable programs that produce explicit RGB frames? Local analytic
geometry, image operations and mathematical dynamics are allowed. Generation
does not call learned image/video/audio generators or external physics engines.
An optional audio extension emits explicit PCM samples alongside RGB frames.

## Core evaluation suite

| Benchmark | Role | Conditioning and scope | Metrics / readiness |
| --- | --- | --- | --- |
| [Physics-IQ Verified](https://github.com/google-deepmind/physics-IQ-benchmark) | Physical evolution | Existing pinned 198-case I2V suite | Existing official evaluator adapter; preserve current pins |
| [RoboJudge generation evaluation](https://arxiv.org/abs/2610.27782) | Embodied manipulation | The exact shared 50-prompt set in Section 5.6, with its original conditioning images and actual prompt versions | RoboJudge-9B PA, IA and their mean; original common_set_50 input manifest located; smoke uses an explicitly selected official prefix |
| [WBench](https://github.com/meituan-longcat/WBench) | Interactive world evolution | 289 cases / 1,058 interaction turns; navigation, subject action, event editing and perspective switch | Quality, setting, interaction, consistency and physical dimensions; preserve the official multi-turn protocol |
| [WorldScore](https://github.com/haoyi-duan/WorldScore) | Scene complexity and spatial generation | 3,000 examples; initial scene and camera/layout instructions, including sequences of next-scene generation | Controllability, quality and dynamics; new adapter and smoke required |
| [WorldArena](https://github.com/tsinghua-fib-lab/WorldArena) | Embodied world prediction | Start with its video-generation evaluation; preserve each selected conditioning mode, including actions where required | Its released video metrics / EWMScore; do not claim downstream functionality from video quality alone |

RoboJudge's shared 50-prompt generation experiment is distinct from its
800-video judge-agreement benchmark. Do not substitute a random 50-item sample
of the 800-video benchmark. `code/evaluate.py` measures agreement with human
ratings; new generated videos instead need PA/IA judging and aggregation.
Seventeen published generator baselines are available in the paper, but direct
comparisons require matching the input set, prompt variants and generation
settings.

See [the concrete smoke contracts](BENCHMARK_SMOKE.md) for WorldModelBench (350),
TC-Bench (150 T2V / 120 I2V), the shared-50 provenance and the current real-model smoke scope.

## Optional audio extension

| Benchmark | Role | Scope / readiness |
| --- | --- | --- |
| [HelixBench](https://huggingface.co/datasets/NoizAI/Helixbench) | Audio-visual and spatial sound | Released 1,015 first frames and AV captions, evaluator and frozen reference features. Report KL, FAD, DeSync, ImageBind, CLAP and Spatial separately. Follow the release's v3 all-150 Spatial protocol. No combined score. |
| [AVGen-Bench](https://github.com/microsoft/AVGen-Bench) | General text-to-audio-video generation | 235 prompts in 11 categories; current smoke covers one physical-experiment T2AV prompt with RGB plus PCM. Newer audio extension, not a classical core benchmark. |

Start with event synchronization and spatial sound rather than adding a speech
or music synthesis module to the core pixel-video study.

## Diagnostic and reserve candidates

| Benchmark | Additional capability | Decision |
| --- | --- | --- |
| [MemoBench](https://arxiv.org/abs/2606.27537) | A target undergoes a physical process, leaves view, and returns in an updated state; 360 reference clips | Strong diagnostic for state persistence and hidden evolution. Verify its conditioning and released evaluator before selecting a split. |
| [WorldBench](https://world-bench.github.io/) | Isolated motion, permanence, support, perspective, and quantitative physical constants | Relevant diagnostic. Project page currently says code is coming soon; data is linked, but evaluator availability is not assumed. This is distinct from WBench. |
| [iWorld-Bench](https://github.com/EmbodiedCity/iWorld-Bench) | Camera control, trajectory following and memory | Public metadata, first frames, camera resources and evaluator are present. Substantial overlap with WBench/WorldScore; reserve for additional camera-control validation. |
| [WorldModelBench](https://github.com/WorldModelBench-Team/WorldModelBench) | Broad application coverage: robotics, driving, industry, human activities, gaming, animation and nature | 350 text-plus-first-frame prompts. Useful broad generalization test, but secondary to the more diagnostic core suite. |

## Capability coverage

- Physical dynamics: Physics-IQ; optional WorldBench diagnosis.
- Spatial perspective and newly revealed pixels: WorldScore and WBench.
- Scene and appearance complexity: WorldScore; optional WorldModelBench.
- Instruction and interaction control: WBench.
- Temporal state persistence: WBench; optional MemoBench.
- Embodied manipulation: RoboJudge's shared 50 and WorldArena.
- Audio-visual synchronization and spatial acoustics: optional HelixBench.

## Rollout order

1. Preserve the existing Physics-IQ experiment. Locate and hash the exact
   RoboJudge shared-50 inputs and prompt variants.
2. Smoke WBench navigation and interaction cases, including an actual
   multi-turn sequence; smoke RoboJudge with one manipulation case.
3. Smoke WorldScore camera motion and WorldArena video prediction. Check whether
   each official evaluator accepts the generated RGB outputs and their media
   wrappers, and document any protocol deviation.
4. After smoke, freeze benchmark versions and run the core suite. Do not expand
   every benchmark to the full model/Track matrix before this gate passes.
5. Add MemoBench diagnosis or HelixBench audio as targeted extensions after the
   core capability results are understood.

## Common protocol

- New experiments default to Text and Vision-Agent, with autonomous review.
  Preserve Vision-Input boundaries and results for explicit historical
  configurations; do not modify the ongoing v1 three-Track matrix.
- Single-case worlds are isolated. Multi-turn state/history is handled exactly
  as required by that benchmark, with no cross-case context.
- Inputs and generation context contain no reference continuations, test
  answers, masks, evaluator feedback or baseline outputs unless the official
  task explicitly requires a conditioning asset.
- Use each benchmark's own duration, temporal sampling, resolution and action
  contract. A shared 256-pixel / 4-or-5-fps setting is a custom comparison track
  unless validated against that benchmark's published submission protocol.
- RGB tensors and PCM waveforms are primary artifacts. Media wrapping is for
  evaluator compatibility; verify wrapping does not silently alter the data.
- Freeze outputs before evaluation. Preserve weak but valid outputs, distinct
  code/pixel candidates and observable tool traces.
- Record model/version, harness version, allowed tools, compute/token cost,
  wall time and actual review activity. Review remains autonomous; do not force
  a fixed visual-review prompt or round count.
- Compare coding agents and video/world generators on matched inputs. Report
  native outputs separately if output protocols cannot be matched.
- Report benchmark scores separately; do not average unrelated scales into a
  fabricated universal world-model score.

## Evidence checked

This proposal was checked against the RoboJudge paper (Section 5.6 and its
generator table), WBench and WorldScore project pages, the WorldArena paper,
the iWorld-Bench repository README, the WorldModelBench project page, the
WorldBench project page, the MemoBench paper, and the released HelixBench
dataset card. Package availability and exact media contracts still require
runtime validation before full experiments.
