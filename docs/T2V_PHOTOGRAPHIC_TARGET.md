# T2V photographic output target

Existing T2V runs remain original-protocol observations. Representative first
frames use layered polygons and ellipses, simple shading and analytic liquid
surfaces; these are schematic illustrations rather than photographic footage.
Saving a correctly shaped RGB tensor establishes artifact validity, not visual
realism or physical correctness.

New T2V experiments can opt in with `"visual_target": "photoreal"` in a fresh
task input directory. Use a separate protocol label and output root; preserve
the official task text and old inputs, histories and submissions.

`tools/prepare_photoreal_t2v.py` creates only fresh prompt/spec inputs, a
separate protocol/config and an empty paused output directory. It does not copy
old videos, code or feedback, and does not start an agent:

```bash
python tools/prepare_photoreal_t2v.py --source-config configs/old-t2v.json \
  --inputs-root data/new-photoreal-inputs --runs-root runs/new-photoreal \
  --output-config configs/new-photoreal.json
```

The additional model-visible requirements are:

> Construct the video directly in image/pixel space. Do not build a separate
> scene/world model or physics simulation and render it into video.
>
> Aim for live-action photographic realism for the full scene, with coherent
> appearance and motion.

The existing Python and image/pixel tools remain available. Local coordinates,
masks, interpolation, texture and motion calculations can support pixel
construction. The new method restriction targets a separate scene/simulation
model rendered into video; it is not a blanket ban on mathematical functions,
geometric drawing or filters. The requested primary representation is image
appearance, rather than a world-state/renderer pipeline.

VBench and PhyGenBench generation/evaluation remain user-paused. This option
does not start a new smoke, resume a benchmark, modify existing runs or add a
visual-feedback requirement to the Text track. Actual photographic quality
requires evaluation of generated images; it is not automatically certified by
the existing artifact validator or by the agent's own description.
