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

## RoboJudge shared50

The input-only original50 identity manifest is `configs/evaluation/robojudge_shared50_inputs.json`. `tools/prepare_robojudge_shared50.py` downloads only the initial image and original instruction at its pinned data revision. Robot/human prefixes are the original paper prefix1; human corpus names and prefix are checked explicitly.

```bash
python tools/prepare_robojudge_shared50.py --manifest configs/evaluation/robojudge_shared50_inputs.json --output data/robojudge_inputs --indices all
python tools/setup_official_benchmark.py robojudge --download-checkpoint
```

The only checkpoint downloaded by that flag is published `HuggingFriends/RoboJudge-9B`, revision `54b5fd7b93e0288bc91a8827af03b72eec7ffad1`; complete local file hashes are recorded. `tools/evaluate_robojudge_shared50.py` runs unchanged upstream inference with original greedy/bfloat16/SDPA settings. Smoke requires explicit partial scope; only all50 complete PA/IA pairs can receive a full shared50 mean. No seed42/43 checkpoint or different judge is substituted.

## VBench-I2V / VBench++

This is `vbench2_beta_i2v`, not VBench-2.0 T2V physics. Standard scope is all1,118 official pairs,355 initial images and five independent samples per pair (5,590 videos/configuration). The evaluator accepts an explicit `--generation-root`, so manifest-relative artifact paths can be used on another host. API seeds may be unreported: record independent completed session identities instead of inventing seeds.

`tools/evaluate_vbench_i2v.py` checks full counts and invokes unchanged official scorers. Full Total uses original `scripts/cal_i2v_final_score.py` normalization/weights only after complete raw metric coverage. The upstream submission helper silently fills missing metrics with zero; this adapter rejects missing metrics instead. Camera returns three fields (mean, category means, per-video records). Unrepresented-category NaN is retained only in explicitly named category smoke; standard full requires every camera category. Temporal flickering remains an extra raw dimension outside the nine-field I2V Total.

DreamSim changes Torch Hub to its `models/` directory. Seed the exact pinned DINO repository and checkpoint in that cache, and record the files; do not fetch a newer DINO/DINOv2 model to bypass a download error.

## WorldScore

Static needs all2,000 entries. Dynamic Total additionally needs all1,000 motion entries. Long static cases have three sequential scene segments; subsequent inputs are only previous generated last RGB plus the next official text control. Export removes repeated anchor frames and matches official camera metadata.

`tools/evaluate_worldscore.py run` calls the original `Evaluator` with only a model-registration metadata entry for PixelWorld; metric implementation and fixed empirical bounds stay unchanged. Aggregation respects metric applicability: content alignment is skipped on official intra-camera cases, rather than treated as a failed missing score. The current frontier board rows are team self-evaluations without complete public submission/runtime provenance; retain that limitation.

The preflight selects resource identities for `--split static`, `dynamic` or `all`. The pinned default metrics use **SEA-RAFT**; separate RAFT/FlowFormer files are alternate implementations and are not default requirements. Static resources also include the actual BERT, CLIP-IQA+ backbone/head, aesthetic backbone/head and VGG19. Full Evaluator import additionally needs torch-scatter, the spaCy English model and Mamba/CausalConv1D even when evaluating a static case. Base-package importability does not establish metric inference success; require actual predictions and complete applicable metric records.

## WorldArena

Track1 text output is121 frames/24FPS, recommended640x480. The actual pinned test archive contains1,000 original episodes and two instruction-variant sets. Complete local16-indicator scope includes the variants; the public board averages15 fields and omits Action Following. Preserve this scope distinction instead of silently narrowing full submissions.

The unmodified CSV writer has two reproduced key defects. The explicitly named `aggregate-compatible` path changes only those two export keys in an external copied writer, records original/corrected hashes, keeps raw values and original metric source unchanged, and calls the actual pinned public board formula only after full checks. It does not certify organizer publication or fill missing fields.

## WBench

Full is289 cases/1,058 turns. Later turns use previous generated last RGB; export retains all segment frames and stages pre-cut turn clips. `tools/evaluate_wbench.py run` invokes unmodified upstream phases, original Doubao judge and separate PAVRM environment, then checks every applicable case metric.

The original judge is `doubao-seed-2-0-lite-260215`. Existing local API-guide access was probed and returned `InvalidEndpoint.ClosedEndpoint`; another authorized working endpoint is required. The Qwen replacement judge is explicitly non-comparable to published Full baseline scores. The final coarse aggregation's public provenance must also be retained; do not label arbitrary available-metric means as a Full Total.

## Primary output and diagnostic ablations

See [OUTPUT_SPEC_AND_ABLATION_PLAN.md](OUTPUT_SPEC_AND_ABLATION_PLAN.md). All formal benchmark scores require the complete official setting. Small pipelines/case diagnostics are labeled smoke or analysis and never replace a standard leaderboard run. Raw pixels, executable programs, saved candidates, tools/images and exposed usage are recorded; unreturned provider internals and unsaved drafts cannot be claimed as captured.
