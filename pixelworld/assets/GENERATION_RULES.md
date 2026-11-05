# PixelWorld generation contract v2

- Use only `first_frame.png` and `prompt.txt`. Work inside this workspace. No network, other cases, reference continuations, masks, scores, memory, external AI models, learned weights, external simulation/rendering engines, or subagents.
- Generate 20 RGB frames at 256×144, 4 fps, for 5 seconds. Frame 00 must be pixel-identical to `first_frame.png`.
- Implement `generate.py` and call `artifact_io.save(frames, case_dir)` with uint8 RGB arrays of shape `(20,144,256,3)`. Local Python drawing, image operations, shading, analytic geometry and mathematical dynamics are allowed.
- Choose your own approach and use the tools permitted by your Track. Save intermediate generated results in the workspace when producing candidates for inspection.
- Use `.tmp/` for temporary files. No additional planning or method report is required.
