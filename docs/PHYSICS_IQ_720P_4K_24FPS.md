# Physics-IQ native-source resolution experiment

Both conditions run all 198 official Physics-IQ Verified BPP/I2V tasks, with
GPT-6.1-Sol, GPT-5.6-Sol and DeepSeek-V4.1-Flash on Text and Vision. There are
1,188 videos per condition, 2,376 total. Resolution ablation is limited to
Physics-IQ; no corresponding new runs are launched for other benchmarks.

| Condition | Resolution | FPS | Frames | Duration |
|---|---:|---:|---:|---:|
| Standard video resolution | 1280×720 | 24 | 120 | 5 seconds |
| Original recorded resolution | 3840×2160 | 24 | 120 | 5 seconds |

Original recordings are 4K at 30 FPS. Here only resolution is taken from the
native recording; generation FPS stays at the user-selected 24. Native 4K
switch images are checked against the pinned source-file SHA256. 720p inputs
are derived directly from those images using LANCZOS; 4K inputs preserve RGB.
Both therefore retain more conditioning detail than the earlier experiment
which enlarged the canonical 256×144 image to 512×288. Record this input-detail
change when comparing the earlier experiment.

Output token budget remains 100k per recorded attempt window, reasoning effort
high, and at most five model attempts per case (infra interruptions excluded).
Agents choose their own checking and refinement strategy. A resolution-specific
output helper avoids embedding gigabytes of pixels in the local HTML. It
preserves the same packed RGB tensor and native PNG submission formats. Public
large RGB playback uses lossless chunks; no low-resolution result is upscaled
to stand in for a native submitted video.

The ordinary official Physics-IQ watcher exports every native frame to a
lossless libx264rgb video and checks decoded RGB frame by frame. Complete 198
case cohorts are required before scoring. Generation, reference FPS handling,
failed attempts, and existing legacy results stay separate.

Prepare official inputs using the original first-frame directory:

```bash
python tools/prepare_physics_iq_4k.py --source-frames "$SWITCH_FRAMES" \
  --base-inputs "$BPP_INPUTS" --inputs data/physics_iq_720p24fps/inputs \
  --width 1280 --height 720
python tools/prepare_physics_iq_4k.py --source-frames "$SWITCH_FRAMES" \
  --base-inputs "$BPP_INPUTS" --inputs data/physics_iq_4k24fps/inputs
```

Use `configs/physics-iq-720p24fps.example.json` and
`configs/physics-iq-4k24fps.example.json` with your existing Codex and compatible
API routing. Keep source image hashes and per-case input inventories intact.
The first officially indexed case checks the submission pipeline and is reused
in the full cohort, never counted as an extra sample or selected using scores.
