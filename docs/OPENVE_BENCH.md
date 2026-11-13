# OpenVE-Bench video editing

OpenVE remains an optional completed editing smoke; its full benchmark is not
launched. PCVE-RigidBench is the required physical counterfactual editing
benchmark in the current PixelWorld 4+1 protocol. PVIR is excluded. Existing
Physics-IQ, RoboJudge, PCVE and PhyGenBench T2V/I2V experiments retain their
inputs, prompts, budgets and evaluator pins.

## Official sources and pins

- Paper: <https://arxiv.org/html/2512.07826v1>
- Evaluator: <https://github.com/OpenVE-Team/OpenVE-3M>, commit `f36055a7f43186f7e7d77f9f4b243cb51731da97`.
- Data: <https://huggingface.co/datasets/Lewandofski/OpenVE-Bench>, revision `255b2ff91a8c7d45696f37f5aed14bd427b35e34`.
- Official CSV SHA256: `0ed856d1facc8de3a392d2678022fae11d02ebdb003b8a51a8af20e669e5ce55`. Modified cached manifests are rejected.
- 431 tasks: global style 58; local change 65; background change 59; local remove 59; local add 67; creative edit 30; camera edit 43; subtitle edit 50.
- Original CSV fields: `edited_type,prompt,original_video`. The submission appends `edited_result_path`.

The input is the **complete original video and the exact editing instruction**. This is video editing, not I2V continuation or prediction after a historical clip. Edited frame 00 may differ from the original. No target edited video, evaluator response, benchmark score or external mask is exposed to generation.

## Agent contract

Protocol version: `pixelworld-openve-edit-v1-20261110`. Use your own installed Codex. This checkout was verified with **Codex CLI 0.167.0**; it does not install a bundled Codex. Run `python -m pixelworld.cli doctor` first.

The isolated workspace adds these editing inputs to the existing helper/rule files:

| Input | Purpose |
| --- | --- |
| `source_video.mp4` | Complete original clip, without temporal cropping |
| `source_pixels.npz` | Sampled `rgb` uint8 array, `[time,height,width,3]` |
| `source_info.json` | Native dimensions/FPS/duration and exact sampling timestamps |
| `source_inspection.png` | Contact sheet of sampled source frames |
| `first_frame.png` | First sampled source frame; no copy constraint on edited output |
| `prompt.txt` | Unchanged official instruction |
| `task_spec.json` | Exact output dimensions, frame count, FPS and task type |

Text has no image attachment and disables image viewing tools, but can read RGB through local code. Vision-Agent receives the source first frame/contact sheet and can inspect its own candidates. Both retain the same workspace sandbox, no-network policy, 100k output-token budget, reproducible `generate.py`, required `artifact_io.save(...)` submission, and intermediate candidate capture. The model decides how to implement the edit and whether to refine.

## Sampling

The initial smoke uses long edge 256 and target 4 FPS. Preserve aspect ratio with even output dimensions. Keep the **complete source duration**: choose `n=round(source_duration*target_fps)`, then set exact playback FPS to `n/source_duration`. This avoids silently truncating a short or long clip to 5 seconds. Original and sampled metadata/hashes are retained outside the agent workspace.

Official row 58, `openve_0058`, requests replacing a silver sedan with a futuristic electric car with glowing blue accents while maintaining position and pose. Native input: 1280×720, 113 frames at 50 FPS, 2.26 seconds. Smoke output: 256×144, 9 frames at approximately 3.982300885 FPS, also 2.26 seconds.

These are PixelWorld sampling settings, not a claim of official mandated output FPS/resolution. The paper evaluates models at their respective official training resolutions and input frame counts. Report our sampling configuration alongside scores.

## Prepare and run a smoke

Install project dependencies as in the main README, plus `opencv-python-headless` for source decoding. `ffmpeg` is used only outside generation to export RGB for the official evaluator; `imageio-ffmpeg` is an optional encoder fallback.

```bash
python -m tools.setup_openve prepare \
  --data-root data/openve \
  --inputs-root data/openve/inputs \
  --case-index 58 --long-edge 256 --fps 4

cp configs/openve-smoke.example.json configs/openve-local.json
# Set your model/provider in this local config and supply its env credential.
python -m pixelworld.cli doctor --config configs/openve-local.json
python -m pixelworld.cli run-case \
  --config configs/openve-local.json --model your-model \
  --track vision-agent --case openve_0058
```

Prepared case directories are immutable. Use a new inputs root if changing sampling. To prepare all **431** official tasks, omit `--case-index`; after smoke success, remove `case_ids` in a distinct full-run config. Do not treat the one-case smoke as a full benchmark result.

## Export and evaluate

```bash
python -m tools.setup_openve export \
  --config configs/openve-local.json --model your-model \
  --track vision-agent --output evaluation_outputs/openve-smoke

git clone https://github.com/OpenVE-Team/OpenVE-3M vendor/openve-source
git -C vendor/openve-source checkout f36055a7f43186f7e7d77f9f4b243cb51731da97

python -m tools.evaluate_openve \
  --source vendor/openve-source \
  --input-csv evaluation_outputs/openve-smoke/new_result.csv \
  --data-root data/openve \
  --output evaluation_outputs/openve-smoke/seed_scores.csv --check-only
```

The adapter loads the **eight original Seed rubrics and original score parser** from the pinned source without importing its private TOS client. Its transport sends original/edited video data URLs at the official **2 FPS judge sampling rate**. Generation FPS and judge sampling FPS are distinct. No checkpoint or image/video model is used for generation.

To score, configure externally:

- `OPENVE_SEED_BASE_URL`: compatible chat API base URL;
- `OPENVE_SEED_API_KEY`: credential;
- `OPENVE_SEED_MODEL_ID`: deployed endpoint ID;
- `OPENVE_SEED_MODEL_IDENTITY=seed-1.6-vl`: only after verifying this endpoint actually serves the paper's judge.

Then remove `--check-only`. Credentials remain in the evaluator process environment. A newer Seed or another judge is not substituted automatically. Current local intake has no configured, verified Seed-1.6-VL judge endpoint, so no official score is claimed.

The official parser averages numeric scores per response; the official script then averages valid row scores. Instruction-related upper bounds on the other dimensions are **instructions inside the judge prompts**; the published parser does not numerically clamp them. The adapter preserves that behavior and records raw responses, scored coverage and errors. Full-paper comparability is enabled only when the exact full 431-row scope is submitted and all rows receive valid scores. Failed rows are not filled with zeros.

## Paper reference scores

Rechecked against official **v1 Table 2, Seed-1.6-VL**:

| Model | Overall / 5 |
| --- | ---: |
| VACE | 1.17 |
| OmniVideo | 1.02 |
| InsViE | 1.40 |
| Lucy-Edit | 1.95 |
| ICVE | 2.25 |
| DITTO | 2.06 |
| OpenVE-Edit | 2.41 |

Runway Aleph reports **3.50** on **30 examples per category, 240 total**, owing to cost constraints. That row is not a full-431 direct baseline. Gemini 2.5 Pro has a different table, as do the appendix's InternVL and Qwen judges; their scores must not be mixed with Seed-1.6-VL results.

## Current evidence

The editing contract, full-duration sampling, input snapshots and Text/Vision-Agent tool boundaries passed the complete **260-test** suite after this addition.

The separate GPT-6.1-Sol Vision-Agent smoke completed official row 58 in **746.77 seconds**, with **16,615 API-reported output tokens** (8,970 reasoning output tokens reported separately, not added again). It saved **three candidate generations**, delivered nine RGB frames, and passed local format, pixel/tensor consistency and isolation checks. The official submission CSV/video export and paired evaluator input/scope checks passed. This is **1/431 smoke coverage**, with no official judge score. The detail page plays the original, final edited pixels and all saved candidates; input/output video playback was checked in a browser.
