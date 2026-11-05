# Multi-benchmark smoke

The smoke pass checks whether PixelWorld produces valid, inspectable outputs
under each benchmark's input interface. It is not a full leaderboard run.
The user reviews these videos before choosing the full benchmark suite.

Use one model and one fixed case per benchmark initially. This pass uses
GPT-5.6-Sol through the optional TRAE CLI backend because that is the requested
model route on the current host. Codex remains the default: use your own
installed CLI and model/provider configuration. No bundled Codex installation
is required. The agent's task, workspace, RGB helper, candidate recorder and
token recorder are shared across backends.

## Candidate suite and selected contracts

| Benchmark | Released scope | Smoke input | PixelWorld smoke output / deviation |
| --- | --- | --- | --- |
| Physics-IQ Verified | 198 cases | Prepared first frame + instruction, case 0008 | Existing 256×144, 20 frames at 4 fps. Existing v1 full matrix/evaluator remains unchanged. |
| WorldModelBench | 350 cases | Index 0: first frame + `text_instruction` only | Width 256, original aspect ratio, 20 frames at 4 fps. No `text_first_frame` is added to I2V. |
| TC-Bench | 150 T2V / 120 I2V in the inspected repository | T2V index 0, chameleon changing brown to green | 20 frames at 4 fps; no input image, editing instructions or target end image. |
| RoboJudge shared-50 | 50 unique original generation tasks | Original `common_set_50` input 0; robot prefix 1 from the paper appendix | Width 256, original aspect ratio, 20 frames at 4 fps; one specified prefix, no rewriting model. |
| WBench | 289 cases / 1,058 turns | Case 1, all four navigation turns | Official Wan `build_turn_prompt`, 5 s per turn, 4 fps, width 256. Previous generated last frame only; a fresh agent per turn. Lossless PNG conditions replace the upstream MP4-to-JPEG handoff. |
| WorldArena | Clean50 task split described in current release | Official downloaded validation episode 1, text-driven | Preserve 121 frames and 24 fps. 256×192 preview is below the recommended 640×480. Validation smoke is not a test-set result. |
| WorldScore | 3,000 examples: 2,000 static + 1,000 dynamic | First static entry: café, `camera_path=[push_in]` | Official image, next scene text/style and camera intent; 50 frames, preview playback at 10 fps, original aspect ratio at width 256. This tests one scene transition; no full camera-trajectory metric claim. |
| AVGen-Bench | 235 prompts in 11 released category files | `physical_experiment.json` index 10, floating ping-pong ball in dryer airflow | T2AV, 10 s at 4 fps RGB, 24 kHz mono int16 PCM. This is an audio extension, not a classical core benchmark or a spatial-audio test. |

These counts were checked from the released metadata or upstream README.
TC-Bench and WorldModelBench are the smaller, earlier video benchmark
candidates. WBench and WorldArena cover interaction and embodiment. WorldScore
is larger; smoke first and defer full scope selection. AVGen-Bench is newer;
do not describe it as a classical joint audio/video benchmark.

Official sources: [Physics-IQ](https://github.com/google-deepmind/physics-IQ-benchmark),
[WorldModelBench](https://github.com/WorldModelBench-Team/WorldModelBench),
[TC-Bench](https://github.com/weixi-feng/tc-bench),
[RoboJudge](https://github.com/Sphere-AI-Lab/RoboJudge),
[shared-50 inputs](https://huggingface.co/datasets/HuggingFriends/mllm-as-embodied-world-judge),
[WBench](https://github.com/meituan-longcat/WBench),
[WorldArena](https://github.com/tsinghua-fib-lab/WorldArena),
[WorldScore](https://github.com/haoyi-duan/WorldScore),
[AVGen-Bench](https://github.com/microsoft/AVGen-Bench).

The original RoboJudge manifest has exactly 50 unique task keys. The later
substitution manifests have 65 keys and are not used. Neither the 800-video
judge-agreement set nor any generated baseline continuation is given to the
generation agent.

## Per-case interface

A prepared input directory has `prompt.txt` and optional `first_frame.png`.
An optional `task_spec.json` supplies only the task/media contract:

```json
{
  "benchmark": "example",
  "task_type": "i2v",
  "width": 256,
  "height": 192,
  "frames": 121,
  "fps": 24,
  "audio": null
}
```

`task_type=t2v` supplies no initial image. Audio uses
`{"sample_rate":24000,"channels":1}`. The harness freezes this specification
outside the agent workspace for validation. Only the minimal task/rules text
and output dimensions change. Legacy v1 rejects media overrides.

The agent calls `artifact_io.save(frames, case_dir)`; audio tasks additionally
pass `audio=pcm` with int16 `(samples, channels)`. The helper saves explicit
`pixels.npz`, numbered RGB PNGs, contact sheets, a pixel player and optional
PCM WAV. The validator checks every numbered PNG against the immutable tensor,
checks I2V frame zero, and checks PCM rate, channel count and sample count.

Prepare a WorldModelBench smoke using only its legal conditioning assets:

```bash
python tools/prepare_worldmodelbench.py --output data/worldmodelbench/inputs --indices 0
pixelworld run-case --config configs/your-benchmark.json --model your-model-key --track vision-agent --case 0000
```

Point the config's `inputs_root` at this directory and give it an independent
`runs_root`. Pin `--revision` to an upstream commit before a full experiment.
Other inputs were prepared using the source mappings in the table above.

## Interaction interface

An episode directory contains a first frame, a media specification and an
`interactions.json` list of `{ "action": "W", "prompt": "..." }` entries.
This list is read by the outer harness, not mounted in the agent workspace.
Run:

```bash
pixelworld run-sequence --config configs/your-benchmark.json --model your-model-key --track vision-agent --episode case_1
```

The current agent receives the current instruction and the previous generated
last frame. Previous code, future interactions, evaluator masks, target
trajectories and scores are not passed. A failed turn stops the episode; it
does not silently advance or choose another candidate. Each turn retains its
own run manifest, tokens, tools and candidate history.

## Review and evaluation boundary

`python -m pixelworld.smoke_web --root RUN_ROOT --site SITE_ROOT` builds the
review page from an `inventory.json` and completed per-benchmark runs. Each
completed case has a final pixel player, every frozen candidate's pixel player,
inspection images, source differences and observed tool events. Multi-turn
episodes also have continuous segment playback. WAV and RGB share one clock.

The watcher preserves candidates without asking the agent to review them or
feeding diagnostics back. A frozen candidate is evidence of a generated
artifact; visual inspection is established by image tool events. No mandatory
review count or method report is introduced.

Only generation/artifact/interaction/player smoke checks are performed here.
New benchmark judges and full scoring are separate. Export wrappers and
evaluator smoke need to be frozen before claiming leaderboard comparability:
WorldModelBench's released VILA judge, RoboJudge PA/IA scorer, WBench's combined
video pipeline, WorldArena's video-quality pipeline, WorldScore's camera-aware
metrics, TC-Bench's assertions, and AVGen-Bench's module-specific judges.
VBench custom-input quality metrics can reuse these outputs; that result is
not a VBench standard-prompt full leaderboard score. Existing Physics-IQ official
evaluation remains independently active.

## Verification details

The first WorldArena artifact exposed a harness ordering bug at 100+ PNGs.
The validator was corrected to check numeric indices rather than lexicographic
filenames. The original video was revalidated, with the prior validation kept
in its logs; no model regeneration or output change was made. Regression tests
cover 121 frames, I2V consistency, T2V, audio formats and per-turn isolation.

TRAE CLI's `workspace-write` blocks writes and network as configured; it is
not an OS-level mount that physically hides every outside file. The workspace
contract and audit additionally prohibit outside data reads. This limitation
is the same as the documented portable cleanroom boundary.

The review builder accepts `--asset-base` for an alternate public origin of the same lossless PNG files. This changes only browser transport, without changing generated RGB or benchmark evaluation input. The current public preview uses the repository raw-file origin for pixel sprites after observing slower Pages transfers.
