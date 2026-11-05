# Harness smoke evidence

The public harness was exercised with Codex CLI 0.166.0 and a custom
Responses-compatible deployment of `gpt-5.5-2026-04-24`.

One fresh case was run in all three Tracks with the same custom GPT-5.5 deployment:

| Track | Duration | Frozen rounds | Accepted |
|---|---:|---:|---:|
| Text (strict rerun) | 140.5 s | 2 | yes |
| Vision-Input (strict rerun) | 120.9 s | 2 | yes |
| Vision-Agent (strict rerun) | 140.3 s | 1 | yes |

Each produced 20 frames and passed:

- frame 00 exactly equals the conditioning image;
- tensor shape `(144,256,20)`, dtype `uint32`;
- all PNGs exactly equal their `0xRRGGBB` tensor slices;
- no network command, subagent, outside-workspace read/change, or visual-tool call;
- one observable frozen candidate round;
- clean terminal `turn.completed`.

The Vision-Agent model chose not to call `view_image` in the accepted smoke.
The manifest therefore reports zero visual-tool calls; tool availability is not
misreported as verified visual self-review.

The provider URL and credentials are intentionally not published. Use
`configs/gpt55-responses.example.json` with your own Responses-compatible
gateway.

Live playable outputs and visual traces:
https://siyuanmacs.github.io/PixelWorld/smoke/

During smoke testing, two harness issues were found and fixed before release:

1. `--ask-for-approval` is a Codex top-level option and must precede `exec`.
2. `--ignore-user-config` alone does not suppress bundled system skills. Each
   run now uses a new `CODEX_HOME` and `skills.bundled.enabled=false`; command
   auditing also rejects non-system absolute paths outside the case workspace.

## Multi-benchmark GPT-5.6-Sol smoke (2026-11-06)

[Playable benchmark review](https://siyuanmacs.github.io/physics-iq-pixel-preview/bench_smoke_20261106/index.html) · [Task contracts](BENCHMARK_SMOKE.md).

All 11 segments completed on GPT-5.6-Sol / Vision-Agent through the optional TRAE CLI backend. These are generation/artifact smoke results, without new benchmark judge scores. Codex remains the portable default.

| Benchmark | Case / turn | Frozen candidates | API output tokens | Reasoning output tokens | Artifact audit |
| --- | --- | ---: | ---: | ---: | --- |
| avgenbench | physical_10 | 1 | 8,218 | 992 | pass |
| physics_iq | 0008 | 2 | 8,345 | 3,395 | pass |
| robojudge | common50_0000 | 2 | 11,071 | 4,688 | pass |
| tcbench | 0000 | 3 | 8,975 | 2,115 | pass |
| wbench | case_1_turn_01 | 2 | 8,594 | 3,116 | pass |
| wbench | case_1_turn_02 | 3 | 7,789 | 3,211 | pass |
| wbench | case_1_turn_03 | 7 | 11,513 | 4,340 | pass |
| wbench | case_1_turn_04 | 2 | 7,303 | 3,101 | pass |
| worldarena | val_episode1 | 2 | 12,196 | 5,204 | pass |
| worldmodelbench | 0000 | 2 | 6,149 | 2,223 | pass |
| worldscore | static_000 | 4 | 4,380 | 1,186 | pass |

Total reported output tokens: **94,533**. Reasoning is preserved separately and not added to output tokens. Frozen-candidate counts are not interpreted as visual review counts.

WBench completed all four official navigation actions with an exact lossless generated-last-frame handoff. WorldArena preserves 121 frames / 24 fps but uses a validation episode at preview resolution. AVGen-Bench emits synchronized 10-second RGB and PCM WAV. The WorldArena numeric-frame-order validator fix rechecked the same output; no model retry occurred.
