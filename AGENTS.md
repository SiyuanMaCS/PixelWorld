# PixelWorld repository instructions

- This repository evaluates coding agents that directly write RGB pixels. Do not add an image/video generation model, learned renderer, reference continuation, or physics engine to the generation path.
- Keep the three Track boundaries exact: Text has no attached image and no visual output tool; Vision-Input has the initial image attachment but no visual output tool; Vision-Agent has both.
- Never put credentials, local absolute paths, generated benchmark videos, Physics-IQ references, masks, or scores into git.
- `data/physics_iq/`, `vendor/`, `runs/`, `site/`, and `evaluation_outputs/` are generated and ignored.
- Run `pytest -q` and `pixelworld doctor` after changing the harness. Run a one-case smoke before a matrix.
- The official evaluator commit and dataset revision in `pixelworld/constants.py` are protocol pins. Change them only with an explicit protocol version bump.
