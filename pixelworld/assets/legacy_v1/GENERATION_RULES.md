# PixelWorld generation contract

- Scene inputs are only `first_frame.png` and `prompt.txt`. Stay inside this workspace. Do not access the network, other cases, benchmark references, masks, scores, memories, external AI/image/video models, learned weights, physics engines, 3D renderers, or subagents.
- Directly compute 20 RGB frames at 256×144, 4 fps, 5 seconds. Frame `00` must exactly equal `first_frame.png`.
- Local Python pixel operations are allowed: drawing, source-pixel copy/crop, transforms, warps, inpainting, procedural shading, analytic normals, and mathematical motion. Describe the actual method honestly.
- Before coding, write `OBSERVATION.md` with visible measurements and a 20-frame event plan. You may revise any number of times.
- Save `generate.py`, `pixels.npz`, `frames/00.png`–`19.png`, `inspection.png`, `transition_check.png`, `index.html`, and `METHOD.md`. The tensor must be uint32 `0xRRGGBB`, shape `(144,256,20)`, and exactly match all PNGs.
- Put temporary files under workspace `.tmp/`, never shared `/tmp`. Only claim visual review if you actually used a visual tool.
