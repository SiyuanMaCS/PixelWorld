# Official evaluation setup and scope

Use an existing user-owned Codex executable; PixelWorld does not install or vendor Codex. See [CODEX.md](CODEX.md) for clean contexts and explicit Responses-provider routing. Generation and neural evaluation use separate directories/environments.

## Source and environment recreation

```bash
python tools/setup_official_benchmark.py robojudge
python tools/setup_official_benchmark.py vbench-i2v
python tools/setup_official_benchmark.py worldarena
python tools/setup_official_benchmark.py wbench
python tools/setup_official_benchmark.py worldscore
```

Each command verifies an existing pristine pinned checkout, or clones the exact published revision into `vendor/`. It never resets another checkout, installs Codex, runs generation, downloads a baseline video, or computes a score.

Portable audited runtime locks for RoboJudge/VBench are in `configs/evaluation/`. Optional `--venv /path/to/eval-env --python 3.11` recreates those environments with uv. Source packages may additionally require their declared CUDA extensions; they must be built from the pinned source. WorldScore/WorldArena/WBench have separate official environment instructions and cannot be reduced to one generic LLM judge.

## Physics-IQ full evaluation handoff

Physics-IQ uses the pinned198 identities in `data/physics_iq_verified_i2v.json`,
independently of other benchmarks' prepared manifests. The input preparer now
also writes `<input-directory-name>_manifest.json` in the input parent; the
supervisor prefers that inventory. An existing generic manifest belonging to
another benchmark is preserved. The per-agent five-file input remains unchanged.

Before export, every accepted run is checked against its official case, model,
track, immutable switch-frame RGB and base BPP hashes, native256×144/4FPS/20-frame
contract, submitted tensor and matching PNG sequence. A full export requires all
198 accepted cases and verifies an exact lossless RGB decode. Existing exports
are preserved rather than overwritten.

Early native runs that predate `input_snapshot/` can use their preserved workspace
inputs only when their file hashes match the original run manifest and their RGB
and prompt identities match the pinned official case. Export records label this
as `early_workspace_inputs_hash_verified`; no historical snapshot is fabricated.
A missing snapshot that was declared by the run remains an error.

`tools/watch_physics_evaluation.py` runs in the evaluation environment and waits
for full delivery. Example:

```bash
python tools/watch_physics_evaluation.py \
  --config configs/physics_full.json \
  --resource-root /path/to/prepared-physics-resources \
  --output evaluation_outputs/physics_full
```

For a new host, use the repository's normal setup and its returned ready marker:

```bash
pixelworld physics-iq setup-evaluator \
  --upstream vendor/physics-IQ-benchmark \
  --benchmark-parent data/physics-iq-eval
python tools/watch_physics_evaluation.py \
  --config configs/physics_full.json \
  --evaluator-ready data/physics-iq-eval/PIXELWORLD_EVALUATOR_READY.json \
  --output evaluation_outputs/physics_full
```

The setup records the actual evaluator interpreter. An existing uv environment
can be selected with `UV_PROJECT_ENVIRONMENT`; `--no-install --no-download`
reuses prepared source/runtime/data without installing packages or downloading
reference data again. The ready-marker route verifies the same pins and exact
reference directory; it is not a reduced evaluation mode. The legacy
`--resource-root` route remains available for prior prepared experiments.

The resource directory contains `upstream/physics-IQ-benchmark`, `.venv`,
`protocol/descriptions_base.csv`, `protocol/dataset.json`, `tools/bin/ffmpeg`,
and `data/physics-IQ-benchmark-verified`. Source, descriptions and dataset revision
are checked before watching. Original inference runs with the declared native
4FPS grid and one run. Missing outputs prevent a full Verified score; exhausted
cases are retained. Progress-file counts are waiting hints, never full submission
proof. Any completed or terminal cohort is rechecked against actual runs.

## RoboJudge shared50

The input-only original50 identity manifest is `configs/evaluation/robojudge_shared50_inputs.json`. `tools/prepare_robojudge_shared50.py` downloads only the initial image and original instruction at its pinned data revision. Robot/human prefixes are the original paper prefix1; human corpus names and prefix are checked explicitly.

```bash
python tools/prepare_robojudge_shared50.py --manifest configs/evaluation/robojudge_shared50_inputs.json --output data/robojudge_inputs --indices all
python tools/setup_official_benchmark.py robojudge --download-checkpoint
```

The only checkpoint downloaded by that flag is published `HuggingFriends/RoboJudge-9B`, revision `54b5fd7b93e0288bc91a8827af03b72eec7ffad1`; complete local file hashes are recorded. `tools/evaluate_robojudge_shared50.py` runs unchanged upstream inference with original greedy/bfloat16/SDPA settings. Smoke requires explicit partial scope; only all50 complete PA/IA pairs can receive a full shared50 mean. No seed42/43 checkpoint or different judge is substituted.

One case's failed startup/recovery attempt folders are not independent submissions. Preparation selects the earliest completed, validated attempt and records every ignored attempt separately, consistent with the supervisor's reuse policy. If all attempts fail, that case remains failed. It does not choose an output by judge score or increase trial counts.

## VBench-I2V / VBench++

This is `vbench2_beta_i2v`, not VBench-2.0 T2V physics. Standard scope is all1,118 official pairs,355 initial images and five independent samples per pair (5,590 videos/configuration). The evaluator accepts an explicit `--generation-root`, so manifest-relative artifact paths can be used on another host. API seeds may be unreported: record independent completed session identities instead of inventing seeds.

`tools/evaluate_vbench_i2v.py` checks full counts and invokes unchanged official scorers. Full Total uses original `scripts/cal_i2v_final_score.py` normalization/weights only after complete raw metric coverage. The upstream submission helper silently fills missing metrics with zero; this adapter rejects missing metrics instead. Camera returns three fields (mean, category means, per-video records). Unrepresented-category NaN is retained only in explicitly named category smoke; standard full requires every camera category. Temporal flickering remains an extra raw dimension outside the nine-field I2V Total.

DreamSim changes Torch Hub to its `models/` directory. Seed the exact pinned DINO repository and checkpoint in that cache, and record the files; do not fetch a newer DINO/DINOv2 model to bypass a download error.

The generation-to-evaluation handoff is executable. Run this service in the
original VBench GPU environment, separately from agent workspaces:

```bash
python tools/watch_vbench_evaluation.py \
  --config configs/vbench_full.json \
  --input-provenance data/vbench/full_scope_manifest.json \
  --output evaluation_outputs/vbench_full
```

These paths refer to your prepared full generation config and the input-only
archive/crop provenance produced during provisioning. The watcher waits for all
5,590 accepted sample identities in each configured model/track. It selects the
supervisor's earliest accepted attempt, requires a distinct recorded session for
every sample, checks exact official prompts and deterministic conditioning-image
preprocessing, exports lossless RGB and then invokes standard evaluation. Cached
exports have source/run/RGB hashes and an exact decode receipt. Missing or
budget-exhausted deliveries stay visible and prevent full scoring; the watcher
does not rerun agents, choose by score, or fill absent videos. Original evaluator
errors are retained and require diagnosis before another scoring attempt.

For a handoff smoke, `tools/prepare_vbench_submission.py` accepts explicit
`--scope official-data-smoke --pair-index N`. A partial manifest cannot enter
standard evaluation. The service is bounded by `--max-hours` (default14days),
supports `--once` for a status check and stops when its evaluator-side `STOP`
file is created. Only one watcher can own an output directory at a time.

## WorldScore

Static needs all2,000 entries. Dynamic Total additionally needs all1,000 motion entries. Long static cases have three sequential scene segments; subsequent inputs are only previous generated last RGB plus the next official text control. Export removes repeated anchor frames and matches official camera metadata.

`tools/evaluate_worldscore.py run` calls the original `Evaluator` with only a model-registration metadata entry for PixelWorld; metric implementation and fixed empirical bounds stay unchanged. Aggregation respects metric applicability: content alignment is skipped on official intra-camera cases, rather than treated as a failed missing score. The current frontier board rows are team self-evaluations without complete public submission/runtime provenance; retain that limitation.

The preflight selects resource identities for `--split static`, `dynamic` or `all`. The pinned default metrics use **SEA-RAFT**; separate RAFT/FlowFormer files are alternate implementations and are not default requirements. Static resources also include the actual BERT, CLIP-IQA+ backbone/head, aesthetic backbone/head and VGG19. Full Evaluator import additionally needs torch-scatter, the spaCy English model and Mamba/CausalConv1D even when evaluating a static case. Base-package importability does not establish metric inference success; require actual predictions and complete applicable metric records.

The original Evaluator catches exceptions and assigns finite default penalties. At256×144, its SEA-RAFT half-scale/four-level correlation path failed on a zero-height interpolation and wrote raw100/normalized0. Preserve that original result and report the exception; do not call it successful optical-flow inference because JSON is finite or the process exits0. The adapter records these reported errors without altering the original penalty policy. A512×288 dimension probe passed; the working generation specification is updated to native512×288 rather than presenting upsampled old frames as a new native generation.

## WorldArena

Track1 text output is121 frames/24FPS, recommended640x480. The actual pinned test archive contains1,000 original episodes and two instruction-variant sets. Complete local16-indicator scope includes the variants; the public board averages15 fields and omits Action Following. Preserve this scope distinction instead of silently narrowing full submissions.

The unmodified CSV writer has two reproduced key defects. The explicitly named `aggregate-compatible` path changes only those two export keys in an external copied writer, records original/corrected hashes, keeps raw values and original metric source unchanged, and calls the actual pinned public board formula only after full checks. It does not certify organizer publication or fill missing fields.

`configs/evaluation/worldarena-hf-models.json` locks the original Qwen3-VL-8B-Instruct and Qwen2.5-VL-7B-Instruct repositories to explicit revisions and canonical object hashes for their configs, tokenizers and all weight shards. The official Qwen3 config does not contain `_name_or_path`; that incidental field is not an identity check. Resource validation uses the complete locked file set instead. These reproducibility pins do not establish which unpublished checkpoint revision was used for a public leaderboard row.

The March6 initial-input archive has no GT video payload. The separately pinned later reference archive is checked against all4,000 original image/instruction assets before staging; this byte alignment is independent of the unresolved per-baseline published test revision. Archive validation preserves path/link/duplicate checks and reads selected payloads sequentially instead of repeatedly seeking through gzip. No reference payload is placed in a generation workspace.

### WorldArena runtime probes and remaining boundary

The exact originalTorch2.10.0+cu128 core was installed and checked on the existing
V100. Its wheel lists sm70, and FP32 operations/SDPA passed. A small4D GEMM probe
failed for FP16/BF16, but actual2D `nn.Linear` at64 and512 features passed with
FP32, FP16 and BF16. Therefore the failed synthetic batched probe does not
establish that all VLM linear operations fail, nor prove a GPU upgrade necessary.
Full original-model inference remains the decisive check. No precision, judge,
attention implementation or model version was changed to manufacture a pass.

Original SAM3 access has not been established, and full Qwen weight sets and
complete three-stack metric imports remain pending. Modern-GPU resource capacity
is a separate issue: a visible queue quota is not proof of current-master/queue
compatibility. Keep preparation, device probes and actual metric inference as
three different statuses.

### Original WorldArena VLM component smoke

`tools/evaluate_worldarena_vlm_smoke.py` evaluates the preserved episode1 with
unchanged `video_quality/VLM_judge.py`, its original16-frame sampling,
Qwen3-VL-8B-Instruct checkpoint and greedy400-token generation parameters.
Only a configurable checkpoint path is supplied externally. All original
config/tokenizer/shard files, including generation_config.json, are checked
against their canonical hashes before inference. Exactly one video and all
three original metrics must be returned; missing fields/default zeros and parse
errors remain failed outcomes. This is a three-metric component smoke, not a
complete16-indicator WorldArena smoke or a1000/3000-video leaderboard score.

The current unversioned Transformers Git `main` resolves to5.23.dev0 and requires
Python3.11, contradicting the official README's Python3.10 environment. The
recorded reproduction choice is Git commit
`65d834fb48624221339830499602fa9428df0583`, the latest cached main commit before
the pinned WorldArena source's2026-07-22 publication timestamp. That snapshot
reports5.15.dev0, supportsPython3.10 and contains the Qwen3-VL implementation.
This preserves the nominal original model, Torch2.9.1/cu128, prompt and scoring
code. It is an explicit runtime pin for an otherwise unversioned dependency;
it does not establish which library revision the published baseline used.
The current-main installation rejection and selection evidence are retained.

The original decord0.6 distribution has a legacy cp36 tag in its WHEEL metadata,
so the package checker reports a platform incompatibility on Python3.10. Actual
import, reading all121 frames and exact first-RGB comparison have passed in the
prepared environment. The warning is retained; no wheel metadata or decoder
implementation was rewritten. The source image is320×240 and the declared
generation input is its640×480 LANCZOS resize. Decoder comparisons use that
provided input, rather than comparing arrays at different resolutions.

## WBench

Full is289 cases/1,058 turns. Later turns use previous generated last RGB; export retains all segment frames and stages pre-cut turn clips. `tools/evaluate_wbench.py run` invokes unmodified upstream phases, original Doubao judge and separate PAVRM environment, then checks every applicable case metric.

The original judge is `doubao-seed-2-0-lite-260215`. Existing local API-guide access was probed and returned `InvalidEndpoint.ClosedEndpoint`; another authorized working endpoint is required. The Qwen replacement judge is explicitly non-comparable to published Full baseline scores. The final coarse aggregation's public provenance must also be retained; do not label arbitrary available-metric means as a Full Total.

## Primary output and diagnostic ablations

See [OUTPUT_SPEC_AND_ABLATION_PLAN.md](OUTPUT_SPEC_AND_ABLATION_PLAN.md). All formal benchmark scores require the complete official setting. Small pipelines/case diagnostics are labeled smoke or analysis and never replace a standard leaderboard run. Raw pixels, executable programs, saved candidates, tools/images and exposed usage are recorded; unreturned provider internals and unsaved drafts cannot be claimed as captured.
