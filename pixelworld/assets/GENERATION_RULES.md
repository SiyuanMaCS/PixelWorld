# PixelWorld generation contract v2

- Use only `first_frame.png` and `prompt.txt`. Work inside this workspace. No network, other cases, reference continuations, masks, scores, memory, external AI models, learned weights, external simulation/rendering engines, or subagents.
- Generate 20 RGB frames at 256×144, 4 fps, for 5 seconds. Frame 00 must be pixel-identical to `first_frame.png`.
- You must create `generate.py`, run it, and call `artifact_io.save(frames, case_dir)` at least once before finishing. Finish only after the required output artifacts exist. Keep `generate.py` runnable so it regenerates the submitted RGB video.
- Local Python drawing, image operations, shading, analytic geometry and mathematical dynamics are allowed.
- Choose your own approach and use the tools permitted by your Track. If you revise the video, save each revised candidate before continuing. Avoid repeated revision without a clear expected improvement; aim for high-quality output while considering efficiency.
- Use `.tmp/` for temporary files. No additional planning or method report is required.
