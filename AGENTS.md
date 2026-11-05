# PixelWorld repository instructions

- This repository evaluates coding agents that directly write RGB pixels. Do not add an image/video generation model, learned renderer, reference continuation, or physics engine to the generation path.
- New experiments default to Text and Vision-Agent. Text has no attached image and no visual output tool; Vision-Agent has both and decides autonomously whether to inspect/refine. Do not launch Vision-Input by default. Preserve its original boundary and results for explicit legacy configurations and v1 experiment continuation.
- Minimal v2 requires code/RGB outputs and saving intermediate candidates, without mandatory observation, event-plan or method reports. Record candidate artifacts, code revisions and tool logs externally. Keep legacy v1 task/rule text in assets/legacy_v1 unchanged.
- Never put credentials, local absolute paths, generated benchmark videos, Physics-IQ references, masks, or scores into git.
- `data/physics_iq/`, `vendor/`, `runs/`, `site/`, and `evaluation_outputs/` are generated and ignored.
- Run `pytest -q` and `pixelworld doctor` after changing the harness. Run a one-case smoke before a matrix.
- The official evaluator commit and dataset revision in `pixelworld/constants.py` are protocol pins. Change them only with an explicit protocol version bump.
