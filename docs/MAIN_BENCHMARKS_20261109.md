# PixelWorld main benchmark set

The main PixelWorld portfolio is fixed as **4+1**: four official benchmark
axes, plus one paired I2V extension for PhyGenBench.

| Benchmark | Role | Scope |
|---|---|---|
| RoboJudge shared-50 | Embodied I2V manipulation | 50 shared tasks, Text and Vision-Agent. |
| Physics-IQ Verified | Physical continuation anchor | 198 official BPP/I2V tasks, Text and Vision-Agent. |
| PCVE-RigidBench | Physical counterfactual video editing | 129 official quantitative English edits, Text and Vision-Agent; native 96 frames at 24 FPS. |
| PhyGenBench official T2V | Compact physical concept coverage | 160 official text prompts mapped to Mechanics, Optics, Thermal and Material. |
| + PhyGenBench I2V extension | Paired initialization analysis | Same 160 prompts, with Qwen-Image-2.1 pre-action initial frames. |

VBench-2.0, WorldArena, WorldScore, WBench, OpenVE and older smoke experiments
are no longer part of the main portfolio. They remain available as exploratory
or historical links only.

OpenVE remains an optional completed smoke. No additional full benchmark is
being launched. [PCVE setup and evaluation](PCVE_RIGIDBENCH.md) documents the
source-only inputs, 1-based intervention frames and full-129 scoring scope.

All five current model configurations request `reasoning_effort="high"`.
Codex passes this explicitly and the Responses gateway forwards `high` to the
upstream API. This is a fixed requested effort setting, not a claim that the
providers use equal reasoning compute or that every model uses its highest
available native setting. Report actual output/reasoning token usage separately
from the external100k output-token limit per bounded retry round.

## Archived VBench-2.0 subset

The selected five dimensions are not the same as the Video-Coder paper's
three-dimension VBench-2.0 table. The local official metadata currently exposes:

| Dimension | Prompt rows |
|---|---:|
| Mechanics | 57 |
| Material | 50 |
| Motion_Rationality | 58 |
| Dynamic_Spatial_Relationship | 69 |
| Instance_Preservation | 57 |

This totals 291 dimension rows before any cross-file prompt de-duplication.
This adapter remains useful as a candidate diagnostic, but it is archived for
the current 4+1 main protocol. If revived, report selected-dimension scores
only, never a full VBench-2.0 score.

The official standard input validator requires three independent videos per
prompt for these dimensions; the current one-video-per-row generation does not
complete that sampling setting. See [the source-code audit](VBENCH2_OFFICIAL_PROTOCOL_AUDIT.md).

## PhyGenBench T2V and I2V extension

The local PhyGenBench prompt file contains 160 prompts:

| Raw category | Count | Reporting dimension |
|---|---:|---|
| Force | 40 | Mechanics |
| Light | 50 | Optics |
| Heat | 30 | Thermal |
| Physical Properties | 25 | Material |
| Chemical Properties | 15 | Material |

PhyGenBench is useful because it is compact and concept-targeted. Its official
condition is T2V and should be scored with the official benchmark protocol after
the complete 160-prompt cohort is generated.

PixelWorld additionally constructs an I2V condition by pairing each original
prompt with a selected pre-action Qwen-Image-2.1 initial frame. This I2V
condition is an extension for analyzing how much high-quality initial visual
state changes a coding agent's direct RGB video generation. It must be reported
separately from the official T2V leaderboard.

## Reference scores to display

Reference tables in the public page are copied from the Video-Coder paper as
context. They are not PixelWorld results.

PhyGenBench:

| Model | Mechanics | Optics | Thermal | Material | Average |
|---|---:|---:|---:|---:|---:|
| MiniMax-H3 | 0.61 | 0.73 | 0.52 | 0.55 | 0.61 |
| Wan2.2-TI2V-5B | 0.55 | 0.58 | 0.53 | 0.50 | 0.54 |
| Video-Coder + MiniMax-H3 | 0.68 | 0.79 | 0.60 | 0.61 | 0.67 |

Archived VBench-2.0 three-dimension paper reference:

| Model | Mechanics | Thermotics | Material | Average |
|---|---:|---:|---:|---:|
| Sora | 62.22% | 43.36% | 64.94% | 56.84% |
| Kling 1.6 | 65.55% | 59.46% | 68.00% | 64.34% |
| HunyuanVideo | 76.09% | 56.52% | 64.37% | 65.66% |
| MiniMax-H3 | 67.59% | 47.22% | 48.94% | 54.58% |
| CogVideoX-1.5 | 80.80% | 67.13% | 83.19% | 77.04% |
| Video-Coder + MiniMax-H3 | 88.67% | 70.88% | 75.02% | 78.19% |

That paper table is intentionally shown separately from our five-dimension
VBench-2.0 subset.
