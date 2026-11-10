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

## Fixed smoke protocol

The paper and downloaded first source video both specify **96 frames, 24 FPS, 4 seconds**, at source resolution 1280×720. The smoke uses **256×144, 96 unique RGB frames, 24 FPS, 4 seconds**. Unlike the existing 4-FPS experiments, PCVE keeps its native temporal grid because its instructions and trajectory scoring use explicit frame numbers. No duplicate-frame upsampling is used.

Instructions are the original **`prompts.quantitative.en`**, as used for the official reported baselines. The released manifest counts source frames from **1**: frame 1 is time zero. The input metadata explicitly records the execution frame and `(frame-1)/24` seconds.

The ten background smoke configurations cover GPT-6.1-Sol, GPT-5.6-Sol, GPT-6-Astra, DeepSeek-V4.1-Flash and Seed-2.1-Pro-0915, each in Text and Vision-Agent. The first task is the first official manifest entry: `air_hockey_chain/edit_heavy_middle_mallet`, increasing the red mallet's mass by a factor of four from frame 1. Smoke concurrency is two across all models so the four ongoing full experiments retain their capacity.

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

Omit `--case-index` to prepare the full 129 tasks, using a fresh immutable input root. Use your own installed Codex; this harness is checked with CLI **0.167.0**. Generation configuration and model routing follow the main README. Runtime `pcve_smoke.json` is the current ten-configuration one-case smoke; it is not a full benchmark run.

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

The tracker uses GroundingDINO Tiny and SAM2.1 Hiera-L. The released tracker has an author-specific absolute SAM2 checkpoint path; a portable evaluator setup must point to the same checkpoint locally without changing the scoring logic. Current host checks show no CUDA access and SAM2, LPIPS, OpenCLIP and scikit-image are not installed in the foreground environment. Therefore **generation smoke is running, but no PCVE score is claimed**. Installation and scoring are separate from generation delivery.

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
