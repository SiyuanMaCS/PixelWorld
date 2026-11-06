# Historical inputs and controlled interventions

The main Text and Vision-Agent tasks preserve autonomous generation, inspection,
revision and stopping. Experimental inputs are opt-in and must have their own
configuration and output directory; their results do not replace a standard run.

## V2V

A prepared V2V case contains `prompt.txt`, `task_spec.json`, `first_frame.png`,
`conditioning.mp4`, `conditioning_frames/`, `conditioning_info.json`, and
`conditioning_inspection.png`. Set `task_type` to `v2v` in the task specification.
`first_frame.png` represents the last historical observation. The output contains
only the future continuation, so output frame 00 is not required to copy it.

Record the input source, sampled source-frame indices, frame timestamps, last
observation time and prediction boundary. For Physics-IQ, the conditioning window
is three seconds and the future window is five seconds. Sparse sampling can leave
a gap between the last observation and the prediction boundary; the agent must
receive this timing information. A comparison using the same last frame should
retain the same future-only convention and prediction boundary.

Text receives no image attachment and has no visual inspection tool. It can read
the legal pixels with local code. Vision-Agent receives the last frame and history
inspection image, and decides whether to use additional visual inspection.

Only legal historical data may enter a generator workspace. Future target videos,
evaluation masks, scores, other-case code and baseline outputs belong in external
analysis. A public Original prefix and a matching Verified switch image are useful
provenance evidence; this alone does not establish a full Verified V2V submission.

## Explicit task and input overrides

```bash
pixelworld run-case --config configs/study.json --model model-key \
  --track vision-agent --case case-id \
  --task-file experiments/repair_task.txt \
  --rules-file experiments/repair_rules.md \
  --extra-input previous_candidate --extra-input previous_code.py
```

Additional input paths are relative to the prepared case directory. Absolute paths,
parent-directory escapes and symlink escapes are rejected. Task text, rules,
additional input names and the visible workspace manifest are retained for audit.
If a repair task receives an earlier candidate or feedback, state this explicitly;
it is a separate intervention rather than a clean native generation run.

## Candidate analysis

Saved RGB candidates can be replayed without executing a generator. The viewer
merges consecutive identical RGB snapshots, preserves A → B → A as three
chronological versions, and labels a recovered PNG sequence when its tensor is
unreadable. Independent playback and a shared comparison clock are available.

Count tool executions, candidate snapshots, chronological RGB versions and unique
RGB videos separately. A model's review statement is not evidence of a visual
tool invocation. First/final comparisons of a native run are retrospective; they
are not the results of a prompt that forbids revision.

New minimal-protocol runs also retain `logs/full_rollout.jsonl`,
`logs/tool_calls.json`, and actual returned images under `logs/tool_images/`.
The CLI stdout JSONL is a partial projection: it can omit an entire nested
`exec → tools.view_image(...) → image(...)` call. Count image delivery from
matched full-rollout call/output records, rather than treating a missing stdout
event as no visual inspection. The trace viewer shows these actual images.

Full recording persists an external CLI session file without resuming an old
session or enabling memory/history reuse. The fresh agent workspace and native
task instructions are unchanged. Legacy ephemeral launch settings are preserved.
If full recording is unavailable, its status is explicitly `missing` or `error`;
old stdout-only traces cannot establish the absence of visual inspection. Raw
rollouts remain local; public pages export tool evidence and images, not system
instructions or hidden model reasoning.
