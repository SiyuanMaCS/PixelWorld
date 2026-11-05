# Agent workspace and task audit

## Initial scene-specific and shared files

```text
workspace/
  first_frame.png       conditioning RGB image; varies by case
  prompt.txt            benchmark scene/action instruction; varies by case
  GENERATION_RULES.md   shared output and tool contract
  artifact_io.py        shared serialization/inspection/export helper
  player_template.html shared HTML pixel player
  .tmp/                initially empty local temporary directory
```

The first two files contain scene information. The other three are identical
shared infrastructure within a fixed experiment. The image is a single first
frame, not a reference continuation or trajectory. The prompt describes the
requested action, not a scene-specific drawing program.

`artifact_io.save(frames, case_dir)` receives already computed uint8 RGB arrays
of shape `(20,144,256,3)`. It packs them as `0xRRGGBB`, saves a uint32 tensor of
shape `(144,256,20)`, saves PNGs, creates inspection sheets, and embeds pixels
and frame differences into the player template. It does not choose positions,
draw dynamic objects, calculate future colors or implement motion.

`player_template.html` decodes the provided pixel data and supports playback,
pause, replay and seeking. It contains no scene-specific geometry or trajectory.
Both files are provided to the model as common submission/display helpers;
they are not claimed as model-generated artifacts. Reading them can contribute
to context and token cost.

For new v2 runs, the agent must create `generate.py` and supply RGB arrays to
`artifact_io.save`. The helper saves tensors, frame PNGs, inspection images and
the player. `OBSERVATION.md` and `METHOD.md` are optional. The fixed first-frame
and frame-count requirements remain. The task asks only to save intermediate
results when producing candidates for inspection; it does not prescribe a
review loop or a report. Legacy v1 runs preserve their original required reports.
Logs, token usage, code revisions and frozen candidate archives are recorded
outside the workspace. New runs preserve the exact stdin task in
`task_prompt.txt` for audit.
The CLI can create empty/read-only `.git`, `.agents`, `.codex`, `.trae` mounts
and local cache directories during startup. These are not scene inputs. The
run manifest records the initial five provided files and the actual command.

## Task instructions

The CLI supplies its ordinary coding-agent system and tool instructions.
PixelWorld additionally sends one fixed Track task on stdin. This is not a
blank system context; compare model configurations within the same harness.

Public Codex v2 task text, Vision-Agent:

> Generate the RGB video requested in `prompt.txt`, following
> `GENERATION_RULES.md`. `first_frame.png` is attached visually. Visual image
> tools are available. Choose your own approach.

Text:

> Generate the RGB video requested in `prompt.txt`, following
> `GENERATION_RULES.md`. `first_frame.png` is available through local code and
> numeric RGB operations; it is not attached visually. Visual image tools are
> disabled. Choose your own approach.

The Text Track's image is copied into the workspace as a PNG file, not attached
to the model conversation. The agent can load it into a Python array, for
example `rgb = np.asarray(Image.open('first_frame.png').convert('RGB'))`.
Only values it prints, such as shape, selected RGB triples, region statistics,
connected components, or an ASCII map, become text in the model's context.
The in-memory array itself is not a visual input to the language model.
This is numerically conditioned I2V, not unconditional T2V.

The current TRAE matrix uses its legacy fixed task files under the cleanroom
directory. Its files, mandatory reports and ten-configuration v1 schedule stay
intact; they are not silently converted to the new minimal v2 contract.

## Shared task contract

- Only the first-frame image and benchmark prompt supply case information.
- For the existing Physics-IQ setting: 20 frames, 256x144, 4 fps, five seconds;
  frame00 must exactly match the input image.
- Local Python drawing, copying/cropping, transforms, warping, inpainting,
  procedural shading, analytic normals and mathematical motion are allowed.
- No mandatory observation, event plan or method report in v2. Save intermediate
  generated results when producing candidates for inspection; choose your own
  approach. No fixed visual-review prompt or round limit.
- Use no external AI generation models, references, masks, evaluator scores,
  memory, network or other agents. Keep temporary files under `.tmp/`.
- Submit RGB artifacts and code; only claim visual inspection when an image
  actually entered the visual model context.

## Current isolation and enforcement

The command uses ephemeral sessions, ignores user rules/config, disables
bundled skills and memory, restricts tool networking and disallows visual tools
in the Text Track. Tool logs are audited for violations.

`workspace-write` principally limits writes. It is not an OS guarantee that
only the five workspace files are readable: filesystem reads outside the
workspace are also restricted by the task contract and audit. Do not describe
this harness as having a physical five-file-only read mount. Stronger read
isolation would require a separate sandbox change and verification.

## Track policy

New configurations default to `text` and `vision-agent`. The latter receives
the visual input and can choose to inspect/refine its own results, or finish
without doing so. The internal ID stays `vision-agent` for continuity.

Existing `vision-input` runs/results and explicitly configured legacy groups
remain usable. Named v1 configurations retain their old three-Track defaults.
The current Physics-IQ v1 matrix is not modified or restarted by this policy.


## External recording in v2

- `events.raw.jsonl` preserves exact CLI stdout; `events.jsonl` adds collector
  receipt UTC and monotonic timestamps, without sending messages to the agent.
- Code changes are sampled into `trace/code_history.jsonl` and `code_versions/`,
  including observed edits before the first candidate exists.
- Stable candidates are copied outside the workspace and verified before being
  committed: frame0 exact, all PNGs match the tensor, and copied code/tensor
  hashes match the observed source. Invalid or in-progress copies are retried
  silently; no quality feedback is emitted.
- Candidate snapshots do not prove visual inspection or quality improvement.
  Sampling may miss very short-lived outputs; exact image-payload association
  and per-request token usage require additional tool/provider instrumentation.
- Total run token usage continues to be recorded. Neither review count nor
  generation-token budget is capped by these recording changes.
