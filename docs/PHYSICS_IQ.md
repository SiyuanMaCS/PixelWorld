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
