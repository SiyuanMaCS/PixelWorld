# Multi-benchmark PixelWorld smoke goal

## Objective

Adapt legal benchmark inputs and output contracts to the existing PixelWorld
coding-agent harness, then run one to three real-model smoke cases per candidate
benchmark. Publish playable outputs and raw process traces for the user to
review before choosing any new full benchmark run.

## Fixed structure

- Keep Text and Vision-Agent as the active Tracks. Legacy Vision-Input and the
  ongoing Physics-IQ v1 three-Track matrix are preserved.
- Keep the same Codex invocation, per-case cleanroom, isolated history, no
  generator network/reference access, autonomous review, code/RGB snapshots,
  raw tool events and per-run API token usage.
- Do not add mandatory observation, event-plan, review-count or method reports.
- The model writes code and explicit RGB; audio tasks additionally write PCM.
- Task-specific changes are confined to legal conditioning assets, interaction
  inputs, media shape/duration/rate and the minimal artifact contract.

## Candidates

1. Physics-IQ Verified: first-frame physical continuation.
2. RoboJudge shared-50: exact generation task set from paper Section 5.6. Locate
   its input manifest; never substitute arbitrary items from the 800-video
   judge-agreement set.
3. WBench: include one complete interaction sequence, preserving its turn order
   and allowed conditioning history.
4. WorldArena: video prediction under the selected released conditioning mode.
5. WorldScore: camera/layout-controlled scene generation.
6. A smaller established video-generation benchmark, with TC-Bench checked as
   a candidate; VBench custom quality metrics can reuse generated videos.
7. A compact joint audio/video candidate, with AVGen-Bench checked before
   scheduling; audio waveform generation and AV synchronization must be shown.

HelixBench, MemoBench and other candidates remain optional pending protocol and
cost review. No requirement to generate their full test sets during smoke.

## Smoke model and budget policy

Use GPT-5.6-Sol for the first smoke pass, per the latest user selection. GPT-6.1-Sol is an allowed alternative; do not multiply both before review. Keep the public Codex harness portable and record any CLI/provider adapter used to access this model. Record
the exact model/provider configuration in private run metadata. Initially use
Vision-Agent for capability smoke; exercise Text through common harness tests
and selected paired smoke where useful. Do not multiply every benchmark by
every model/Track before the user review.

Prioritize established benchmarks with test sets in the hundreds, including WorldModelBench and TC-Bench after source verification. Start with one fixed case per candidate, expanding to at most three only when
needed to cover different task interfaces. No quality-based retries or
retrospective best-of-N. Infrastructure failures may be repaired, documented
and retried from clean inputs.

## Deliverables

- Per-benchmark legal input provenance and exact task contract.
- A validated real-model output, or a concrete data/protocol/adapter blocker.
- Playable RGB and optional audio, complete multi-turn segment playback, frozen
  candidates, code differences, tool logs and token usage.
- A unified public review entry showing capability type, output specifications,
  compatibility deviations, failures and implementation/readiness status.
- Smoke test results; official scores only when the evaluator and input scope
  genuinely match, never an invented full leaderboard score from a few cases.

## Acceptance

The user can open every successful smoke and inspect its video, sound where
required, and model process. Each listed candidate has a smoke outcome or a
verified blocker. The existing Physics-IQ full run remains live. No new full
matrix is started until the user selects benchmarks after reviewing the smoke.
