# PCVE-RigidBench: physical counterfactual video editing

PCVE is a required benchmark. OpenVE remains an optional, completed smoke and is not being launched at full scale. Physics-IQ, RoboJudge, VBench-2.0 five dimensions and PhyGenBench continue under their existing generation protocols.

## Official sources

- Paper: <https://arxiv.org/html/2609.35134v1>, Appendix B and C.1.
- Project: <https://videophysedit.github.io/>.
- Benchmark/evaluator: <https://github.com/Hammour-steak/PCVE-RigidBench>, commit `e262f93e9ab69208023413f342adf9d80fa098e5`.
- Dataset: <https://huggingface.co/datasets/ccmoony/PCVE-RigidBench>, revision `772f7b50c9be0648a5b5598861b70211d8b73907`.
- Manifest SHA256: `0b2c92998aa4cf3710b820ff5469cc8c3beb94ce7274a65d63a06f3c16dbc5de`.

There are **129** edits in **20** synthetic rigid-body scenes: mass 32, friction 21, restitution 13, initial velocity 26, addition 7 and deletion 30. Of these, 117 intervene at the first frame and 12 partway through the source video.

The input is a complete source video and an editing instruction. The output is the complete counterfactual video on the same timeline, preserving factual history before the intervention and depicting changed motion/interactions afterward. This differs from predicting a continuation after the source clip.

## Fixed full-generation protocol

The paper and downloaded first source video both specify **96 frames, 24 FPS, 4 seconds**, at source resolution 1280×720. The smoke uses **256×144, 96 unique RGB frames, 24 FPS, 4 seconds**. Unlike the existing 4-FPS experiments, PCVE keeps its native temporal grid because its instructions and trajectory scoring use explicit frame numbers. No duplicate-frame upsampling is used.

Instructions are the original **`prompts.quantitative.en`**, as used for the official reported baselines. The released manifest counts source frames from **1**: frame 1 is time zero. The input metadata explicitly records the execution frame and `(frame-1)/24` seconds.

Full generation covers GPT-6.1-Sol, GPT-5.6-Sol, GPT-6-Astra, DeepSeek-V4.1-Flash and Seed-2.1-Pro-0915, each in Text and Vision-Agent: **129 × 5 × 2 = 1,290 videos**. The first task is `air_hockey_chain/edit_heavy_middle_mallet`, increasing the red mallet's mass by a factor of four from frame 1. Existing successful smoke submissions and all failed-attempt histories are preserved. The shared launch cap remains four per model across benchmarks; the full PCVE supervisor allows ten concurrent tasks, at most one per model/Track, subject to that shared cap.

The same native v2 submission/recording rules apply: runnable `generate.py`, required `artifact_io.save`, saved intermediate candidates, autonomous checking/refinement and external token recording. Python/numpy/PIL/OpenCV pixel operations and mathematical geometry/dynamics are allowed. Generation cannot call external physics/rendering engines or image/video models.

## Input isolation

`tools/setup_pcve.py` prepares the original video, an RGB array, the first frame, a 12-frame source contact sheet, native timing metadata, exact instruction and output spec. Text receives no image attachment and has image-view tools disabled; Vision-Agent receives the source images and decides whether to inspect outputs.

The manifest also contains `edited_video`, `ground_truth`, `physics_diff`, and `edit_summary`. In particular, `edit_summary` describes the counterfactual consequences. **None of these is copied into the generation workspace.** The preparation record outside the workspace contains only input identification/hashes and protocol information. Ground truth and target videos remain in the evaluator-side dataset directory.

```bash
python -m tools.setup_pcve prepare \
  --data-root data/pcve-rigid \
  --inputs-root data/pcve-rigid-inputs \
  --case-index 0
```

Omit `--case-index` to prepare all 129 tasks in a fresh immutable input root. Use your own installed Codex; this harness is checked with CLI **0.167.0**, and current runs record **0.167.1**. Copy [the full configuration template](../configs/pcve-full.example.json), set your model and Responses provider, then run:

```bash
python -m tools.setup_pcve prepare --data-root data/pcve-rigid --inputs-root data/pcve-rigid-inputs
python -m pixelworld.cli matrix run --config configs/pcve-local.json
```

The current full runtime configuration is `runs/bench_codex_20261109/pcve_full.json`. Its input and generation directories retain the historical `pcve_smoke` name to preserve original run manifests, snapshots, retry windows and published URLs. The full scope is explicitly 129 cases in the configuration and status file. The original one-case `pcve_smoke.json` is retained as provenance and no longer has a separate active supervisor.

## Official evaluation

Export validated pixels into the exact prediction layout expected by the original evaluator:

```bash
python -m tools.setup_pcve export \
  --config configs/pcve-local.json --model your-model --track vision-agent \
  --benchmark-root data/pcve-rigid --baseline pixelworld_your_model_vision

python vendor/pcve-rigid-source/eval/compute_metrics.py \
  --benchmark-root data/pcve-rigid \
  --baseline pixelworld_your_model_vision --limit 1
```

For full evaluation, omit `--limit` only after all 129 cases are present. Source/edited ground truth, scene tracking descriptions and the original GroundingDINO/SAM2 tracker stay outside generation. The official scorer resizes predictions to target resolution; matching native 24-FPS frame indices preserves the four-second timeline.

The tracker uses GroundingDINO Tiny and SAM2.1 Hiera-L; FVD uses the official Kinetics-400 I3D TorchScript extractor. Install the original evaluator's dependencies in a separate environment, including PyTorch with CUDA, `sam2`, `transformers`, `torchmetrics`, `lpips`, `open_clip_torch`, `av`, `imageio`, NumPy and Pillow. Place the original SAM2.1 Hiera-L and I3D checkpoints under `vendor/pcve-eval-models/`, or set `PCVE_SAM2_CHECKPOINT` and `PCVE_I3D_CHECKPOINT`. Set `PCVE_EVAL_PYTHON` if that environment uses a different Python executable.

[The complete-cohort adapter](../tools/evaluate_pcve_full.py) verifies all 129 submissions, the pinned untouched source, checkpoint files and CUDA/dependencies before exporting. Its evaluator-side driver overrides only the two author-specific checkpoint path defaults; the original tracker, thresholds, alignment, PES floor and metrics remain unchanged. Target videos and GT JSON are fetched only into the evaluator-side data root. Original per-case metrics must cover exactly 129 cases without failures before a full summary is accepted, and missing FVD/visual metrics are not reported as a complete result.

```bash
PCVE_EVAL_PYTHON=/path/to/eval-env/bin/python python tools/evaluate_pcve_full.py \
  --config configs/pcve-local.json --model your-model --track vision-agent \
  --output evaluation/pcve/your-model/vision-agent
```

Current runtime auto-evaluation is monitored under `evaluation/pcve_full_scheduler/`; it waits for each complete 129-case model/Track cohort. Generation is active; no PCVE score or successful GPU evaluation smoke is claimed until the original evaluator actually runs. Checkpoint/environment blockers remain visible and do not stop generation.

The main physical metrics are **PES**, trajectory error **TE**, and **Mask IoU**. Visual metrics are PSNR, SSIM, LPIPS, CLIP similarity and FVD. PES measures improvement over leaving the source unedited: `max(1 - sum(TE_prediction)/sum(TE_no_edit), -1)`, with the official null-error eligibility filter. Thus PES=0 means no improvement over the source; positive means the intended physical change was better captured.

## Published full-129 references

| Method | PES | TE | Mask IoU |
| --- | ---: | ---: | ---: |
| VACE | -0.042 | 146.26 | 0.273 |
| Ditto | -0.120 | 149.94 | 0.264 |
| MiniMax H3 | -0.096 | 152.00 | 0.250 |
| Seedance 2.5 | -0.087 | 144.99 | 0.231 |
| No edit | 0.000 | 143.13 | 0.289 |
| VideoPhysEdit | 0.376 | 66.70 | 0.421 |

These are the official paper's Table 1 values. The removal-only 30-task table is a different scope. VideoPhysEdit's generated-video-only 116-task result is also different from its complete-129 result. Do not compare our single-case smoke to either full table.
