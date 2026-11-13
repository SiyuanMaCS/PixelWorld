# Physics-IQ 512w24fps evaluation

The high-resolution cohort uses the same 198 official base BPP descriptions.
Its output is native 512×288 RGB, 120 frames at 24 FPS, for five seconds. Agents
receive the canonical 256×144 conditioning image enlarged with Pillow LANCZOS
to 512×288. This controls source image information; it does not introduce a
higher-resolution photograph. Generation prompts and budgets are preserved.

The exporter verifies the preserved canonical RGB hash, the exact LANCZOS
conditioning transform, the original prompt hash, every submitted PNG and the
RGB tensor. It writes lossless libx264rgb videos at the submitted frame rate and
checks decoded bytes against the tensor. There is no frame repetition,
interpolation or conversion of generated 24 FPS videos to the 4 FPS baseline.

All 198 submissions in a model/track cohort must be valid before official scoring
starts. The original pinned Physics-IQ evaluator detects the submitted video FPS
and prepares real references at that FPS through its own `fps_changer`; all
reference handling, masks, alignment and scoring remain evaluator-side. Report
512w24fps scores separately from the native 256×144/4 FPS main cohort. Score and
export receipts record the actual generation resolution, frame count and FPS.

Use the ordinary evaluator watcher with a separate output directory:

```bash
python tools/watch_physics_evaluation.py \
  --config configs/physics-iq-512w24fps.example.json \
  --evaluator-ready "$DATA_ROOT/PIXELWORLD_EVALUATOR_READY.json" \
  --output "$EVALUATION_ROOT/physics_iq_512w24fps" \
  --interval 60 --n-process 4
```

The prepared high-resolution input inventory must retain its `source_inputs`
and source image hashes. Missing provenance blocks export; it must not be
reconstructed from the generated video.
