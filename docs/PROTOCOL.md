# PixelWorld cleanroom protocol: current defaults and v1 compatibility

New configurations use two active Tracks. Explicit historical Vision-Input
configurations and named v1 defaults remain supported for continuation and
reproduction; do not alter ongoing three-Track matrices or historical results.

1. Prepare legal I2V switch frames and prompts with the pinned input setup.
2. Run a fresh smoke in every enabled Track; new experiments default to Text and Vision-Agent.
3. Release the full queue only after format, Track, isolation, and playback checks pass.
4. Start one new Codex session and one empty workspace per model/Track/case attempt.
5. Do not provide human feedback, reference outputs, masks, metrics, other cases, or a fixed review prompt.
6. Freeze every stable candidate independently of whether the Agent visually inspected it.
7. Validate the RGB ABI and audit JSONL before accepting a case.
8. Retry infrastructure/format failures from identical inputs without failure feedback, up to the configured attempt limit.
9. Keep weak but valid generations; they are benchmark outcomes.
10. Run the official evaluator only when all 198 accepted outputs in a group are frozen.

Track comparisons are valid only when model/provider/reasoning settings, tasks, helpers, tools, environment, and input set are identical except for the defined image-attachment/output-visual-tool boundary.
