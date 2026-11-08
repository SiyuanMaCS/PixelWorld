# Physics-IQ Verified protocol

Runtime pins in `pixelworld/constants.py`:

- evaluator: `google-deepmind/physics-IQ-benchmark@d3f3de16a9c66b4d3bfd6bdb5518570e8b72ad48`;
- dataset: `Anates-Labs-Research/Physics-IQ-Verified@b65f567dd8446a4076c7f72446335b3c217a8464`;
- I2V take-1 inputs: IDs `0001`–`0198`;
- prompts: upstream `descriptions/best_practice/descriptions_base.csv`, pinned SHA256;
- output: 20 frames, 256×144 RGB, 4 fps, exactly 5 seconds;
- one `bpp-base` run per config by default.

## Two setup phases

`setup-inputs` downloads only 198 `switch-frames/*.jpg` objects. It verifies source hashes, resized RGB hashes, and prompt hashes against `data/physics_iq_verified_i2v.json`. These are the only benchmark-derived files used for generation.

`setup-evaluator` is separate. It clones the official evaluator and downloads the complete Verified dataset under `vendor/`. Run it only after generation is frozen. Never mount `vendor/physics-iq-data` into an Agent workspace.

## Evaluation

`pixelworld physics-iq eval` requires a complete validated 198-case model/Track group. It:

1. maps every case to the official generated filename;
2. encodes 20 PNGs as lossless `libx264rgb` at 4 fps;
3. decodes the MP4 and compares every RGB byte against the source frames;
4. checks the official checkout commit and prompt CSV hash;
5. invokes `physiq.run_physics_iq` without modifying upstream code;
6. records the command, metrics path, component scores, protocol pins, and timestamp in `scores.json`.

This is a single-run evaluation. Repeat the entire generation protocol independently when mean/std reporting is required.

## What the Verified score measures

The reported leaderboard field is **`final_score_view * 100`**. It is distinct
from `final_score_orig` and `final_score_stable`, which the evaluator also writes.
The following describes the pinned evaluator above, rather than inferring the
formula from column names or comments about the Original score.

The pipeline detects the submitted FPS and prepares real testing videos and
masks at that FPS. PixelWorld's completed runs use 4 FPS: 20 frames over five
seconds. In `load_view`, all videos and masks are resized to the same evaluation
size, one quarter of the real reference video's width and height.

Motion masks are generated with OpenCV: grayscale conversion, Gaussian blur,
an exponentially updated background, thresholding and morphological operations.
They represent detected image changes, not object-instance segmentation or
physical-state labels.

For each scene and camera view, the generated video G is compared to real take-1
R1. Real take-2 R2 supplies a measure of repeat-trial variation. Four metrics are
computed:

| Metric | Raw comparison | Verified normalization |
|---|---|---|
| Spatial IoU | IoU of all-time unions of motion masks | IoU(G,R1) / (IoU(R1,R2) + epsilon) |
| Spatiotemporal IoU | Mean of corresponding-frame motion-mask IoUs | Mean IoU(G,R1) / (mean IoU(R1,R2) + epsilon) |
| Weighted spatial IoU | Min/max overlap of per-pixel motion-mask occupancy fractions | Weighted IoU(G,R1) / (weighted IoU(R1,R2) + epsilon) |
| MSE | Mean full-frame normalized RGB squared error | Inverse of MSE(G,R1) / (MSE(R1,R2) + epsilon) |

Each normalized component is clipped to [0,1]. The four components receive equal
weight, and the result is averaged over all 66 scenes and their three views, then
multiplied by 100. Here epsilon is 1e-8. The `variance_*` fields for IoU contain
real-real similarities; they are not ordinary statistical variances.

For GPT-6.1 Vision-Agent, the frozen official output gives Verified components
48.424195, 45.143150, 43.858051 and 44.362008. Their mean is **45.446851**.
The MSE component here is a higher-is-better normalized score, not raw MSE.
The same output's Original score is 44.298107; that is not the displayed
Verified score.

The score is a reference-based image/motion comparison, rather than an LLM
judgment or a fraction of videos proven physically correct. It captures spatial
and temporal agreement and pixel fidelity, but does not by itself assess every
physical constraint or perceptual video quality. FPS changes also change the
sampled reference and motion masks; report native FPS with scores.

Official implementation:

- [Motion masks](https://github.com/google-deepmind/physics-IQ-benchmark/blob/d3f3de16a9c66b4d3bfd6bdb5518570e8b72ad48/physiq/binary_mask_generator.py)
- [Raw metrics](https://github.com/google-deepmind/physics-IQ-benchmark/blob/d3f3de16a9c66b4d3bfd6bdb5518570e8b72ad48/physiq/calculate_and_write_metrics_to_csv.py)
- [Verified normalization and aggregation](https://github.com/google-deepmind/physics-IQ-benchmark/blob/d3f3de16a9c66b4d3bfd6bdb5518570e8b72ad48/physiq/calculate_iq_score_stable.py)

Published mean ± standard deviation summarizes independently generated full runs.
The official aggregation accepts one to four CSVs; a single run has no run-to-run
standard deviation. Scene bootstrap uncertainty is a different quantity.
