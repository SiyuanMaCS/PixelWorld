# Physics-IQ high-resolution / high-FPS run

This document records the high-resolution, standard-video-FPS Physics-IQ
setting used for PixelWorld capability analysis. It is an analysis run, not a
replacement for the main 256x144 / 4-FPS Physics-IQ Verified run.

## Output contract

| Field | Value |
|---|---:|
| Benchmark | Physics-IQ Verified inputs |
| Task type | I2V |
| Resolution | 512x288 |
| FPS | 24 |
| Frames | 120 |
| Duration | 5 seconds |
| Models | GPT-6.1-Sol, GPT-5.6-Sol |
| Tracks | Text, Vision |
| Scope | 198 cases x 2 models x 2 tracks = 792 videos |
| Output token budget | 100k reported output tokens per attempt window |
| Attempts | At most 5 total model attempts per case |

Every prepared case must include:

```text
first_frame.png  # exactly 512x288 RGB
prompt.txt
task_spec.json
```

The `task_spec.json` must be:

```json
{
  "task_type": "i2v",
  "width": 512,
  "height": 288,
  "frames": 120,
  "fps": 24,
  "audio": null,
  "benchmark": "physics_iq_highres_24fps"
}
```

Frame 00 remains a strict exact-copy condition: the generated frame 00 must be
pixel-identical to the prepared 512x288 `first_frame.png`.

## Preparing inputs

Start from the standard Physics-IQ input folder and resize only the legal
first-frame conditioning images. Do not expose reference videos, masks, scores
or future frames.

```bash
python - <<'PY'
from pathlib import Path
from PIL import Image
import json, shutil, hashlib

src = Path("data/physics_iq/inputs")
out = Path("data/physics_iq_512w24fps/inputs")
out.mkdir(parents=True, exist_ok=True)

spec = {
    "task_type": "i2v",
    "width": 512,
    "height": 288,
    "frames": 120,
    "fps": 24,
    "audio": None,
    "benchmark": "physics_iq_highres_24fps"
}

records = []
for case in sorted(p for p in src.iterdir() if p.is_dir() and (p / "first_frame.png").is_file()):
    dst = out / case.name
    dst.mkdir(exist_ok=True)
    image = Image.open(case / "first_frame.png").convert("RGB")
    image.resize((512, 288), Image.Resampling.LANCZOS).save(dst / "first_frame.png")
    shutil.copy2(case / "prompt.txt", dst / "prompt.txt")
    (dst / "task_spec.json").write_text(json.dumps(spec, indent=2) + "\n")
    records.append({
        "id": case.name,
        "source_first_frame_sha256": hashlib.sha256((case / "first_frame.png").read_bytes()).hexdigest(),
        "first_frame_png_sha256": hashlib.sha256((dst / "first_frame.png").read_bytes()).hexdigest(),
        "prompt_sha256": hashlib.sha256((dst / "prompt.txt").read_bytes()).hexdigest(),
        "task_spec": spec,
    })

(out.parent / "physics_iq_512w24fps_manifest.json").write_text(
    json.dumps({"schema": "pixelworld-highres-physics-iq-inputs-v1",
                "source_inputs": str(src.resolve()),
                "cases": records,
                "spec": spec}, indent=2) + "\n"
)
print("prepared", len(records), "cases")
PY
```

For the current local long run, the prepared input root is:

```text
runs/bench_codex_20261109/inputs/physics_iq_512w24fps
```

## Running the matrix

Use the template config:

```text
configs/physics-iq-512w24fps.example.json
```

For a local run, copy it and update:

- `inputs_root`
- `runs_root`
- provider `base_url`
- provider `env_key`
- `model_catalog_json`

Then launch:

```bash
python -m pixelworld.cli matrix run --config configs/physics-iq-512w24fps.local.json
```

The current local run uses:

```text
runs/bench_codex_20261109/physics_iq_512w24fps_gpt_native_full.json
runs/bench_codex_20261109/generations/physics_iq_512w24fps_gpt_native
```

It is managed in the background by:

```bash
python -u tools/manage_matrix.py \
  --config runs/bench_codex_20261109/physics_iq_512w24fps_gpt_native_full.json \
  --code-root /mnt/bn/embodied-lf3/masiyuan/PixelWorld \
  --state runs/bench_codex_20261109/managed_baseline/physics_iq_512w24fps_gpt_native.json
```

## Reporting

Report this as a high-resolution/high-FPS analysis condition:

```text
Physics-IQ 512w24fps
512x288 / 24 FPS / 120 frames / 5 seconds
```

Do not mix it with the main Physics-IQ Verified leaderboard score unless the
complete 198-case cohort is delivered and evaluated under a declared evaluator
protocol. Compare against the 256x144 / 4-FPS main condition as a controlled
PixelWorld ablation.
