# Add a new model

This runbook is for collaborators who already have their own Codex
installation and model/API access. PixelWorld does not vendor Codex or API
keys; it launches the user's `codex` executable in clean per-case workspaces.

## 1. Install and verify Codex

Use Codex CLI **0.167.x** for new runs. Current live runs record 0.167.1, and
0.167.0 is the validated baseline. Other versions may work, but must pass a
smoke in both `text` and `vision-agent` before full dispatch.

```bash
codex --version
export PIXELWORLD_CODEX="$(command -v codex)"
python -m pixelworld.cli doctor --config configs/benchmark.example.json
```

If your model is available in the local Codex catalog, use a `builtin`
provider. If it is exposed through an OpenAI Responses-compatible gateway, use
`provider.type="responses"`. PixelWorld passes the environment-variable name to
Codex; never put secrets in JSON.

```bash
export MY_MODEL_API_KEY='...'
```

```json
{
  "key": "my-model",
  "model": "provider/model-id",
  "reasoning_effort": "high",
  "cli_backend": "codex",
  "tracks": ["text", "vision-agent"],
  "provider": {
    "type": "responses",
    "id": "my_gateway",
    "name": "My Responses gateway",
    "base_url": "https://api.example.com/v1",
    "env_key": "MY_MODEL_API_KEY"
  }
}
```

## 2. Choose the benchmark config

Start from the closest template:

| Benchmark | Template | Notes |
|---|---|---|
| Physics-IQ Verified | `configs/benchmark.example.json` | 198 I2V cases; 256x144, 4 FPS, 20 frames. |
| RoboJudge shared-50 | `configs/robojudge.baseline.example.json` | 50 I2V cases; width 256, aspect preserved, 4 FPS, 20 frames. |
| PCVE-RigidBench | `configs/pcve-full.example.json` | 129 video-editing cases; 256x144, 24 FPS, 96 frames. |
| PhyGenBench T2V/I2V | see `docs/PHYGENBENCH_PIXELSPACE_PAIRED_V2.md` | Official T2V plus PixelWorld I2V extension. |

Use a new output root for every new model/batch. Do not write into another
model's completed directory.

```json
{
  "runs_root": "runs/my_benchmark_my_model_YYYYMMDD",
  "max_concurrency": 2,
  "max_per_config": 1,
  "max_attempts": 2,
  "max_total_attempts": 5,
  "output_token_budget": 100000
}
```

The public policy is at most **5 total model attempts** per case.
`token_budget_exhausted` counts as a model failed attempt. Infrastructure
failures such as missing keys, 429/rate limits, provider payload errors, mux
errors or stream transport failures should be quarantined and retried without
counting as model attempts.

## 3. Run a smoke

Run one representative case per enabled track before launching the full matrix.

```bash
python -m pixelworld.cli run-case \
  --config configs/my-model.local.json \
  --model my-model \
  --track text \
  --case 0001

python -m pixelworld.cli run-case \
  --config configs/my-model.local.json \
  --model my-model \
  --track vision-agent \
  --case 0001
```

Inspect:

- `run_manifest.json`: validation pass/fail, token usage, stop reason;
- `workspace/generate.py`: rerunnable generator;
- `workspace/pixels.npz`: RGB tensor;
- `workspace/index.html`: local playback page;
- `logs/events.jsonl` and `logs/events.raw.jsonl`: actual Codex events and
  tool evidence.

## 4. Launch the full matrix

```bash
python -m pixelworld.cli matrix run --config configs/my-model.local.json
python -m pixelworld.cli matrix status --config configs/my-model.local.json
```

For durable background operation, use the service/watchdog pattern under your
own run root. The current long-running run uses:

```text
runs/bench_codex_20261109/benchmark_services.json
tools/watch_benchmark_services.py
tools/watch_failed_retries.py --max-total-attempts 5
```

## 5. Evaluate

Only evaluate complete cohorts:

- Physics-IQ: all 198 valid videos for one model/track;
- RoboJudge: all 50 valid videos for one model/track;
- PCVE-RigidBench: all 129 valid videos for one model/track;
- PhyGenBench T2V: all 160 official prompts for one model/track.

Missing videos block official scoring. Do not duplicate outputs, drop failed
cases or invent zero-score rows unless a separate protocol explicitly says so.

## 6. Publish monitoring pages

Raw run directories are large and should not be committed to the source repo.
The repository should contain code, configs, docs and small provenance files
only.

For the live project site:

- source repository: `SiyuanMaCS/PixelWorld`;
- public site branch/repo path: `SiyuanMaCS.github.io/pixelworld/`;
- public entry: <https://siyuanmacs.github.io/pixelworld/index.html>.

Use `tools/sync_stable_pixelworld_pages.py` to publish dashboards and bounded
case previews. Large generated videos/tensors stay in the run root or an
artifact store; GitHub Pages receives lightweight HTML, posters and selected
preview assets.

```bash
python -u tools/sync_stable_pixelworld_pages.py \
  --run-root runs/bench_codex_20261109 \
  --heavy-web /path/to/heavy/web \
  --stable-repo /path/to/SiyuanMaCS.github.io \
  --status runs/bench_codex_20261109/stable_pixelworld_refresh_status.json \
  --core-only \
  --delivery-repo /tmp/pixelworld-pages-delivery
```

After publication, verify the public page with a cache-busting query:

```bash
curl -L 'https://siyuanmacs.github.io/pixelworld/index.html?refresh=manual' | head
```

## 7. What to upload

Commit to GitHub:

- benchmark config templates;
- protocol docs;
- evaluator setup notes;
- small JSON provenance summaries;
- code changes and tests.

Do not commit:

- API keys or Codex auth files;
- full generated tensors/videos;
- Physics-IQ reference videos/masks;
- PCVE target videos or evaluator-only ground truth;
- per-case raw traces unless explicitly sampled and size-bounded.

For sharing a finished model run with collaborators, package a manifest with:

- config JSON and git commit;
- model id/provider id;
- run root path or artifact-store URI;
- status JSON;
- evaluation result JSON;
- dashboard URL.
