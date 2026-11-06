# PixelWorld: Coding Agents as Omni Pixel World Models

**Active scope (2026-11-06): image-conditioned world continuation and
interactive evolution.** The current selection and cost policy is in
[WORLDMODEL_PLAN.md](WORLDMODEL_PLAN.md). World creation, audio and visual puzzle
reasoning discussed in earlier planning are outside the active experiment
suite; their existing demos remain historical evidence.

## Central question

Can the same general-purpose coding agent generate coherent pixel worlds across
scene domains, prediction tasks and control modes, by writing and executing
programs that emit explicit RGB video frames?

The intended claim is broad world-generation competence demonstrated through
generated pixels. Performance, advantages and limits must be established by
experiments; a self-authored scene demo alone is not evidence of generalization.

"Omni" refers to breadth across world domains and task interfaces. It does not
mean question answering about videos. Audio is a possible extension, not a
requirement for the core visual claim.

## Definition of the evaluated agent

The evaluated system is a fixed foundation model inside a common coding-agent
harness. It receives legal task conditions, writes or revises executable code,
executes that code, and optionally inspects its generated images. Its output is
an explicit RGB tensor. There is no required scene graph, event graph, renderer
template, learned video decoder or task-specific hand-authored motion helper.

Local Python image operations, analytic geometry, shading, copying, warping and
mathematical dynamics are allowed. Agent-written procedural modeling is part
of the method. It must be described as programmatic RGB generation, not as
literal token-by-token emission of every pixel or as generation without modeling.
External image/video generation models, learned renderers and physics engines
are excluded from the core generation path.

For the optional audio study, the same agent additionally produces PCM samples
without an external audio-generation model. RGB and PCM share a time axis.

## Three task families

| Family | Conditions | Required output / behavior | Research purpose |
| --- | --- | --- | --- |
| World creation | Text-only world and event description | Construct the initial scene and its evolving RGB frames | Can the agent create diverse, detailed worlds from scratch? |
| World prediction | Given first frame and instruction; additional conditions only where officially required | Continue the given world into future RGB frames | Can it infer appearance, geometry and dynamics from an unfamiliar scene? |
| Interactive world evolution | Initial world plus a sequence of controls or instructions | Continue the same world over multiple segments under intervention | Can it follow controls while retaining and updating world state? |

These families are separate from the three existing capability Tracks. The
current Text Track is not automatically text-to-video: it has no image
attachment but can still analyze the provided first-frame file numerically.
A genuine text-only world-creation task provides no first-frame file. Do not
silently rename the current Text Track or compare it as an unconditional T2V
condition.

## Capability matrix

| Capability | Observable generation tasks | Principal evidence |
| --- | --- | --- |
| Appearance and scene breadth | Rich rooms, outdoor scenes, robots, people, nature, animation; preserve object details | WorldScore; cross-domain coverage from WorldModelBench if needed |
| Spatial geometry | Camera motion, rotation, depth-dependent size, disocclusion and newly visible surfaces | WorldScore; WBench navigation and perspective switches |
| Physical dynamics | Falling, collision, rolling, support, deformation and settling | Physics-IQ Verified; optional WorldBench concept diagnosis |
| Instruction and action control | Subject actions, camera commands, environment edits and embodied goal completion | WBench; RoboJudge shared-50; selected WorldArena modes |
| State persistence and hidden evolution | Repeated controls; objects disappear and return in a changed state | WBench; optional MemoBench |
| Embodied manipulation | Reach, grasp, move, place, open, fold and other specified manipulations | RoboJudge shared-50 and WorldArena video prediction |
| Audio-visual dynamics (extension) | Impact synchronization, sound-source motion and viewpoint-aligned stereo | HelixBench |

Capabilities overlap; benchmark names are evidence sources rather than
independent abilities. Report both per-benchmark results and a coverage map
showing which conclusions each benchmark supports.

## Benchmark portfolio

### Core visual study

1. **Physics-IQ Verified:** preserve the existing 198-case adapter and protocol
   pins. Primary evidence for physical continuation.
2. **WBench:** navigation, subject action, event editing and perspective
   switching. Preserve official multi-turn conditioning rather than converting
   every turn into an independent I2V task.
3. **WorldScore:** camera/layout-following next-scene generation. Primary
   evidence for spatial generation, new pixels and complex environments.
4. **RoboJudge shared-50 generation evaluation:** reproduce the exact input set
   used for the 17-generator experiment in Section 5.6. Score PA, IA and their
   mean with RoboJudge-9B. This is not its 800-video judge-agreement benchmark.
5. **WorldArena video prediction:** complementary embodied scenarios and its
   released video-quality/world-consistency measurements. A video-only result
   does not establish its planning, policy evaluation or data-synthesis utility.

### Targeted extensions

- **MemoBench:** strong diagnostic for maintaining and updating a world beyond
  the current field of view.
- **WorldModelBench:** broader first-frame/task domain coverage if the core
  portfolio leaves creation or domain breadth insufficiently represented.
- **HelixBench:** optional joint RGB/PCM generation; report its six released
  metrics separately.
- **WorldBench:** isolated physics and perspective tests; evaluator release
  availability needs verification before scheduling.
- **iWorld-Bench:** reserve for additional trajectory-control evidence; it
  overlaps with WBench and WorldScore.
- **AVGen-Bench:** reserve for broader T2AV including speech/music, rather than
  making those modules prerequisites for the visual PixelWorld study.

Assign official samples to the task families after checking their released
conditioning. Do not assume every benchmark supplies all three task families.
Custom demonstrations are displayed separately from official benchmark runs.

## Main comparisons

### System comparison

Compare general coding agents against conventional video/world generators on
matched legal conditions. Measure the quality of the generated world, not only
whether the code executes. Report visual appearance, spatial/physical/temporal
coherence, instruction fulfillment, output validity and inference cost.

Use native-protocol reference results separately if resolution, sampling,
duration or controls cannot be matched. Do not infer a universal ranking by
averaging scores from unrelated evaluators.

### Agent capability comparison

New experiments use Text and Vision-Agent. Vision-Agent is the main multimodal
system and autonomously decides whether to inspect and refine its output.
Existing Vision-Input runs are retained as a historical ablation; no new
Vision-Input group is scheduled by default. Named v1 experiments keep all
original settings. These Tracks do not define different kinds of worlds.

Use the same task family, input set, helpers and model configuration within a
Track comparison. For tasks requiring additional observations or audio, define
and freeze an explicit protocol extension instead of claiming that the current
image-only Track gates already cover it.

### Process comparison

Compare the first valid generated candidate with the final candidate to assess
autonomous refinement. Distinguish frozen snapshots, successful generator
executions and actual visual tool reads. Deduplicate code-only/evidence-only
snapshot changes. Do not assume every additional round is better, and do not
replace the submitted final result with a retrospectively selected best round.

## Scientific conclusions to test

1. **Breadth:** does a fixed coding-agent system transfer across worlds and task
   families without benchmark-specific manual drawing assistance?
2. **Strength:** where is it competitive with dedicated generators in final
   RGB quality, physics, geometry, controllability or temporal state retention?
3. **Refinement:** does autonomous checking and program revision improve world
   generation, and what observable actions account for the improvement?
4. **Limits:** how do scene complexity, newly visible surfaces, nonrigid motion,
   action precision and sequence length change performance and cost?

## Efficiency and output scaling

Evaluate quality under fixed run-level generation-token budgets, together with
API cost, first-valid and end-to-end latency. Sweep resolution and output FPS
while holding task conditions and budget fixed. Distinguish prescribed video
FPS from actual agent throughput and already-authored program rendering speed.
These are central experiments for the PixelWorld claim, not incidental runtime
statistics. See [EFFICIENCY_PROTOCOL.md](EFFICIENCY_PROTOCOL.md) for accounting,
budget enforcement, sampling controls and the initial experiment grid.

Strong results on selected dimensions support scoped conclusions. The word
"Omni" describes the intended evaluation breadth, not an assumption of uniform
superiority across every metric or domain.

## Implementation boundary and next steps

The common harness remains the established cleanroom with separate per-case
contexts, legal inputs, autonomous review and frozen RGB artifacts. Multi-turn
state is scoped to one official task and follows that benchmark's input rules.
Reference continuations, labels, judge scores and other cases remain outside
generation context. The benchmark adapter packages conditions and outputs;
it must not supply the answer or a scene-specific motion program.

Immediate preparation: locate RoboJudge's exact shared-50 input manifest, then
smoke WBench, WorldScore and WorldArena adapters before scheduling full runs.
Audio and new task-family support remain proposed extensions. This document
does not start generation or resume a paused goal.

For source links, release status and evaluator details, see
[EVALUATION_ROADMAP.md](EVALUATION_ROADMAP.md).
