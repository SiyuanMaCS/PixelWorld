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

During smoke testing, two harness issues were found and fixed before release:

1. `--ask-for-approval` is a Codex top-level option and must precede `exec`.
2. `--ignore-user-config` alone does not suppress bundled system skills. Each
   run now uses a new `CODEX_HOME` and `skills.bundled.enabled=false`; command
   auditing also rejects non-system absolute paths outside the case workspace.
