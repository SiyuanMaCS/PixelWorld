# PixelWorld

PixelWorld evaluates a **coding agent as a direct RGB pixel world model**. The agent receives a Physics-IQ Verified first frame and prompt, writes Python code, and emits a 5-second continuation as a `uint32` RGB tensor. It does not call an image/video generator.

The repository is a portable benchmark harness built around **OpenAI Codex CLI**. Model identity and API routing are configuration, so the same cleanroom can run against any model exposed by a Codex installation or an OpenAI Responses-compatible gateway.

**PixelWorld does not install, vendor, or replace Codex.** It invokes the
user's existing `codex` executable from `PATH`. To use a specific local build:

```bash
export PIXELWORLD_CODEX=/absolute/path/to/codex
```

Codex authentication, available models, and API access remain owned by the
user's installation. Codex is intentionally not a Python dependency of this
repository.

> Status: research preview. Generated quality remains the measured model outcome. No human selects or repairs individual cases.

The current frozen native baseline is documented at
[baselines/native_v2_100k](baselines/native_v2_100k/README.md), with code commit
and exact generation-file hashes. It uses100k cumulative reported output tokens,
Text/Vision-Agent and autonomous review. Start another RoboJudge model from
[the sanitized config](configs/robojudge.baseline.example.json). RSI variants
must use separate code checkouts and output directories.

The current main benchmark portfolio is fixed in
[docs/MAIN_BENCHMARKS_20261109.md](docs/MAIN_BENCHMARKS_20261109.md) and
[configs/benchmark_portfolio_20261109.json](configs/benchmark_portfolio_20261109.json):

- RoboJudge shared-50;
- Physics-IQ Verified;
- VBench-2.0 five-dimension subset;
- PhyGenBench 160 prompts.

WorldArena, WorldScore, WBench and older multi-benchmark smokes remain
historical/exploratory pages rather than the main portfolio.

Live run entry points, background supervisors, and score-readiness rules are
tracked in [docs/LIVE_RUNS_20261109.md](docs/LIVE_RUNS_20261109.md).

## Included

- Two default capability Tracks: Text and Vision-Agent; historical Vision-Input runs remain supported.
- One clean Codex session per case; empty output workspace; no memory, network tools, subagents, other cases, references, masks, or scores.
- Direct `256×144 × 20` RGB output at 4 fps / 5 seconds.
- Exact PNG ↔ `uint32 0xRRGGBB` tensor validation and frame-00 equality.
- Unlimited autonomous revision with every stable candidate frozen into an observable Trace.
- Fair, restartable matrix scheduling with bounded concurrency and independent retries.
- Pinned Physics-IQ Verified I2V input preparation (198 switch frames only).
- Lossless MP4 export and the unmodified official Physics-IQ Verified evaluator.
- A model × Track dashboard, playable galleries, and per-case visual generation Trace pages.

The repository does **not** contain Physics-IQ reference videos/masks, generated benchmark outputs, API keys, or the original experiment's scores.

## Quick start

Requirements: Linux, Python 3.11+, [Codex CLI](https://github.com/openai/codex) (current validation0.167.0; legacy0.166.0 preserved), `git`, `ffmpeg`, and `uv` for official evaluation.

```bash
git clone https://github.com/SiyuanMaCS/PixelWorld.git
cd PixelWorld
uv venv --python 3.11 .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
pixelworld doctor --config configs/benchmark.example.json
```

Prepare only the 198 legal I2V conditioning images and base prompts:

```bash
pixelworld physics-iq setup-inputs
```

This downloads **switch frames only** at the pinned dataset revision, resizes them to 256×144, verifies RGB hashes, and writes `data/physics_iq/manifest.json`. It does not download evaluation videos or masks.

Physics-IQ Verified is gated, so authenticate first with `hf auth login`. If the
official dataset already exists locally, avoid another download:

```bash
pixelworld physics-iq setup-inputs \
  --source-dir /path/to/physics-IQ-benchmark-verified
```

## Configure models and APIs

For a model in the local Codex catalog:

```json
{
  "key": "my-model",
  "model": "model-id-visible-to-codex",
  "reasoning_effort": "high",
  "provider": {"type": "builtin"},
  "tracks": ["text", "vision-agent"]
}
```

For a Responses-compatible gateway:

```json
{
  "key": "gateway-model",
  "model": "upstream-model-id",
  "reasoning_effort": "high",
  "provider": {
    "type": "responses",
    "id": "my-gateway",
    "name": "My gateway",
    "base_url": "https://api.example.com/v1",
    "env_key": "MY_RESPONSES_API_KEY"
  },
  "tracks": ["text", "vision-agent"]
}
```

Export the key in the parent shell; never put it in JSON:

```bash
export MY_RESPONSES_API_KEY='...'
```

The runner passes the environment-variable **name**, not its value, into the Codex provider config. See [docs/CODEX.md](docs/CODEX.md).

For the optional TRAE CLI backend, [configs/deepseek-v41-flash.example.json](configs/deepseek-v41-flash.example.json)
configures DeepSeek-V4.1-Flash with the minimal-v2 contract and Text/Vision-Agent
Tracks. It requires that model in your own TRAE CLI catalog. Run case 0001 in
each Track before starting all 198 cases; preserve the same output root so the
full run reuses the validated smoke cases. Agent-authored planning and method
reports are optional; code revisions, candidate RGB outputs and tool events are
recorded externally.

On Linux, check the sandbox launcher after a CLI upgrade. With an empty shell
environment, TRAE CLI must have `traecli-resources/bwrap` beside its resolved
executable, or a discoverable system installation. A missing launcher is an
infrastructure failure; repair it before retrying rather than disabling the
workspace sandbox or its network restrictions.

## Smoke, run, and monitor

Run one case first:

```bash
pixelworld run-case \
  --config configs/benchmark.example.json \
  --model openai-example \
  --track vision-agent \
  --case 0001
```

Run a one-case smoke for both active Tracks:

```bash
cp configs/smoke.example.json configs/smoke.local.json
# edit the model ID/provider
pixelworld matrix run --config configs/smoke.local.json
pixelworld matrix status --config configs/smoke.local.json
```

After checking the smoke outputs, run the full matrix:

```bash
cp configs/benchmark.example.json configs/benchmark.local.json
# edit models, providers, and concurrency
pixelworld matrix run --config configs/benchmark.local.json
```

The supervisor is restart-safe. A detached example:

```bash
nohup pixelworld matrix run --config configs/benchmark.local.json \
  > runs/supervisor.log 2>&1 &
```

## Two default Tracks and legacy compatibility

| Track | Initial image attachment | Output visual tool | Purpose |
|---|---:|---:|---|
| `text` | No | Disabled | Code/numeric RGB-only baseline |
| `vision-input` (legacy) | Yes | Disabled | Retained for old configurations and results |
| `vision-agent` | Yes | Available | Autonomous visual self-review |

New experiments default to `text` and `vision-agent`. Explicit legacy Track
configurations remain supported, and named v1 configurations retain their old
three-Track defaults. Existing v1 experiments and saved outputs are unchanged.

These are command-level differences:

- `-i/--image first_frame.png` is present only for the two visual Tracks.
- `--disable view_image` is added to Text and Vision-Input.
- Vision-Agent keeps `view_image` available and chooses its own review count.
- JSONL events are audited; a visual call in a disabled Track is a hard failure.

There is no fixed visual-review prompt and no review-count budget.

New v2 runs require code and RGB outputs, without mandatory observation,
event-plan or method reports. They ask only to save intermediate results when
producing candidates for inspection. The harness records code versions,
validated stable candidates and timestamped tool events externally, preserving
exact CLI stdout in `events.raw.jsonl`. See
[docs/WORKSPACE_AND_TASK.md](docs/WORKSPACE_AND_TASK.md).
Legacy v1 rules/tasks remain frozen under `pixelworld/assets/legacy_v1/`.


Every finalized run records API-reported input, output, cache and reasoning
tokens in `run_manifest.json` (`token_usage`) and `logs/token_usage.json`.
Missing usage remains explicit rather than zero. To backfill older runs and
export one CSV row per run/attempt:

```bash
python -m pixelworld.usage --runs-root runs --output runs/token-report
```

See [docs/EFFICIENCY_PROTOCOL.md](docs/EFFICIENCY_PROTOCOL.md) for accounting
and optional passive recording of older jobs that are still running.

## Codex invocation

The exact command is stored in every `run_manifest.json`. Its stable shape is:

```bash
codex --ask-for-approval never exec - \
  --model MODEL \
  --ephemeral --ignore-user-config --ignore-rules \
  --skip-git-repo-check \
  --sandbox workspace-write \
  --strict-config --json \
  -C RUN/workspace \
  -c sandbox_workspace_write.network_access=false \
  -c 'sandbox_workspace_write.writable_roots=[]' \
  -c sandbox_workspace_write.exclude_slash_tmp=true \
  -c project_doc_max_bytes=0 \
  -c skills.bundled.enabled=false \
  -c shell_environment_policy.inherit=none \
  -c 'shell_environment_policy.set.PATH="<active-venv>/bin:/usr/local/bin:/usr/bin:/bin"' \
  -c 'web_search="disabled"' \
  --disable browser_use --disable computer_use \
  --disable image_generation \
  --disable multi_agent --disable multi_agent_v2 \
  --disable apps --disable plugins --disable memories --disable skill_search
```

The fixed Track task is supplied on stdin. Responses gateway settings are explicit invocation-local `-c model_providers.<id>...` values.

## Output contract

```text
runs/<model-key>/<track>/case_0001_attempt_01/
├── run_manifest.json
├── logs/{events.jsonl,stderr.log,validation.json}
├── trace/{rounds.jsonl,round_000/, ...}
└── workspace/
    ├── generate.py
    ├── pixels.npz             # uint32 (144,256,20), 0xRRGGBB
    ├── frames/00.png ... 19.png
    ├── inspection.png
    ├── transition_check.png
    ├── OBSERVATION.md
    ├── METHOD.md
    └── index.html
```

Acceptance requires every PNG to exactly equal its tensor slice and frame 00 to exactly equal the conditioning image. A `uint32 (20,144,256)` tensor is repaired only when it already matches all PNGs and can be losslessly transposed.

## Visualization

```bash
pixelworld web build --config configs/benchmark.local.json --output site
python -m http.server 8000 --directory site
```

Open <http://127.0.0.1:8000>. The page uses model rows and fixed Track columns. Each case has a playable final tensor and a Trace with frozen candidate rounds, event counts, validation evidence, and separately labelled Agent-authored claims.

## Official Physics-IQ Verified evaluation

Generation and evaluation data are deliberately separate. Only after a complete 198-case group is frozen:

```bash
pixelworld physics-iq setup-evaluator

pixelworld physics-iq eval \
  --config configs/benchmark.local.json \
  --model openai-example \
  --track vision-agent
```

The exporter creates 198 lossless `libx264rgb` videos and decodes each back to RGB for byte-exact comparison. It then runs the official evaluator at:

```text
google-deepmind/physics-IQ-benchmark
commit d3f3de16a9c66b4d3bfd6bdb5518570e8b72ad48
```

Equivalent official command:

```bash
uv run python -m physiq.run_physics_iq \
  --input_folders <198-video-folder> \
  --output_folder evaluation_outputs/official_results \
  --descriptions_file descriptions/best_practice/descriptions_base.csv \
  --benchmark_base_folder vendor/physics-iq-data \
  --n_process 8
```

PixelWorld reports `final_score_view` as the Verified score. The default protocol is I2V, base best-practice prompt, 4 fps, 5 seconds, and one deterministic run. Physics-IQ accepts one run for inclusion but recommends four runs and requires standard deviation for SOTA claims. See [docs/PHYSICS_IQ.md](docs/PHYSICS_IQ.md).

## Leakage and isolation

- Reference videos and masks are never copied into an Agent workspace.
- The generation setup command does not download them.
- Network-capable tools, browser/computer use, external image generation, plugins, memories, skills, and multi-agent features are disabled.
- Every attempt receives a fresh `CODEX_HOME`, and bundled skills are disabled.
- Agent shell commands and file actions are recorded and audited.
- Each attempt receives a fresh directory; only `first_frame.png` and `prompt.txt` vary by case.
- No human Best-of-N or per-case feedback is allowed.

Codex `workspace-write` is the portable native mode. It hard-restricts writes and tool network access; read isolation depends on the installed Codex sandbox. For adversarial models, run the harness in an externally isolated VM/container containing only this repository and allowed inputs. The trace audit remains required.

## Test

```bash
pytest -q
pixelworld doctor --config configs/benchmark.example.json
```

Always run a fresh case in every enabled Track before releasing a full matrix.
The harness's sanitized GPT-5.5 custom-provider smoke evidence is recorded in
[docs/SMOKE_RESULTS.md](docs/SMOKE_RESULTS.md); the corresponding reusable
configuration shape is [configs/gpt55-responses.example.json](configs/gpt55-responses.example.json).

Play the three accepted smoke videos and inspect their round-by-round traces:
**https://siyuanmacs.github.io/PixelWorld/smoke/**

## Upstream attribution

PixelWorld does not redistribute Physics-IQ code or data. Follow the licenses and terms of:

- [Physics-IQ and Physics-IQ Verified](https://github.com/google-deepmind/physics-IQ-benchmark)
- [Physics-IQ Verified dataset](https://huggingface.co/datasets/Anates-Labs-Research/Physics-IQ-Verified)
- [OpenAI Codex CLI](https://github.com/openai/codex)

Current evaluation scope: [I2V world-model suite, complete official settings and published baseline comparisons](docs/WORLDMODEL_PLAN.md). Historical multi-benchmark smoke: [task interfaces, source mappings, RGB/PCM contracts and review pages](docs/BENCHMARK_SMOKE.md). New benchmarks are smoke-only until user review; existing Physics-IQ v1 remains unchanged.
