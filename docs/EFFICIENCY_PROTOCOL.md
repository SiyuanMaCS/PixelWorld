# PixelWorld: budget, latency, cost and output scaling

This is a proposed experiment protocol. Existing runs are autonomous,
uncapped-token runs; they must not be relabelled as fixed-budget experiments.
The current runner records total duration and preserves JSONL usage events.
Every finalized run also writes API-reported tokens to `run_manifest.json`
under `token_usage` and to `logs/token_usage.json`, including failed attempts.
Running jobs have pending usage; missing/partial reports remain explicit.
Output and reasoning counters are stored separately, without inferring their
inclusion semantics. Hard run-level token enforcement and per-request timing
remain to implement.

Backfill existing finalized runs and export one CSV row per run/attempt:

```bash
python -m pixelworld.usage --runs-root runs --output runs/token-report
```

Add `--watch --interval 60` to record completed legacy jobs and refresh the
CSV periodically. The observer does not call a model or change generation
status. Create `runs/token-report/STOP_TOKEN_WATCH` to stop it. Optional
`--path-contains` limits the observer to a selected experiment.

Read-only retrospective usage export (no generation or API calls):

```bash
python tools/summarize_usage.py --runs-root runs --output runs/usage-report
```

The utility writes per-run CSV and per-model/Track JSON summaries. Optional
`--case-id` and `--path-contains` filters select a matched case or experiment.
It preserves output and reasoning fields separately and reports missing usage.

## Questions

1. What quality does the agent achieve under a fixed generation-token budget?
2. How much API cost and end-to-end time does an accepted world continuation
   consume, including autonomous checking and revision?
3. How do output resolution and temporal sampling affect quality and cost?
4. How cheaply can an already authored program generate its frames again?

## Token accounting

Use API-reported usage, not the length of visible reasoning or a tokenizer
applied to the exported trace. Retain input tokens, cached-input tokens,
cache-creation tokens, output tokens and reasoning-token details wherever the
provider exposes them. Verify the provider's field semantics before aggregation.

Primary reasoning/generation budget B: cumulative assistant generation tokens
across the complete run, covering planning, code, tool-call arguments and review.
Reasoning tokens count toward B. If output_tokens already includes reasoning,
do not add reasoning tokens twice. If a provider reports them separately, use
the documented total. Undisclosed reasoning usage must be marked unknown.

Also report cumulative input/context tokens. Repeated context and image/tool
inputs incur cost even though they are not the primary generation budget.
Equal native token counts across model families are an operational comparison,
not a claim of equal FLOPs; include USD cost curves as a second comparison.

## Enforcing a fixed budget

Before each model request, calculate the remaining run-level budget and apply
an effective per-request output limit if the provider supports it, including
reasoning. Account for the actual returned usage before scheduling another
request. Do not prescribe a fixed number of review rounds.

At the budget boundary, freeze the latest valid candidate produced within the
budget. Choose by time/order, not evaluator score. If no valid candidate exists,
record a budget-exhaustion failure. Mechanical validation and artifact export
are permitted after the boundary, but additional LLM repair is not.

Record overshoot explicitly. A limit that can only be checked after a request
finishes is a soft budget. If usage is exposed only at turn completion, current
CLI logs support post-hoc accounting but cannot prove strict live enforcement.

Each valid candidate needs a generation-completion event, exact code/artifact
association and cumulative-usage watermark. Existing watcher round timestamps
alone do not establish tokens consumed when the candidate was generated.
Do not call a retrospective prefix/snapshot analysis a hard-budget experiment.

## Cost and latency

| Quantity | Definition |
| --- | --- |
| End-to-end latency | Task dispatch to validated submitted RGB artifact |
| First-valid latency | Task dispatch to the first candidate passing format/ABI validation |
| Model-request latency | Wall time per API request, including remote/network waiting; collected at the request boundary |
| Tool time | Measured local code execution and inspection/export time; preserve overlap rather than blindly summing concurrent intervals |
| API cost | Sum of billable input, cached input, cache writes, output and other provider charges at a frozen price schedule |
| Cost per generated video second | Total run API cost divided by output duration |
| Replay/render latency | Fresh execution of the already authored final program on fixed hardware |

Do not count official evaluation, webpage publication or human analysis as
generation latency. Report failed/recovery attempt cost separately and include
it in aggregate experiment cost. Cost per completed case should identify
whether recovery attempts are included. If actual billing is unavailable,
label price-based estimates and record the rate source/date. Do not guess rates
for custom deployments.

Report medians and P90 latency across matched cases, plus completion rate and
quality. Use controlled concurrency for latency experiments and disclose
provider/hardware conditions. TTFT or model-internal decode time is reported
only where directly observable.

Paper presentation: prioritize quality-vs-token and quality-vs-cost in the main
text. Put API-dependent first-valid/end-to-end wall latency and its variability
in the appendix unless serving efficiency is itself a central claim. Local
program replay throughput on fixed hardware is a separate, more controlled
measurement. API latency reflects deployment, queueing and network conditions
as well as the model; it is not an intrinsic model-speed ranking.

## Two meanings of FPS

- Output FPS f is the prescribed sampling rate of the generated video.
- Agent effective throughput is N / T_end_to_end frames per wall-clock second.
- Program rendering throughput is N / T_render frames per wall-clock second.
- Real-time factor is T_end_to_end / D, where D is generated video duration.

These are different measurements. A 5-fps video is not necessarily generated
at 5 frames per wall-clock second. A fast replay of an already authored program
is not real-time first-time agent generation.

## Output scaling design

Hold source cases, prompts, model, Track, budget, duration and tool environment
fixed; vary resolution and prescribed FPS. Preserve source aspect ratio.

Initial grid, as an example for five-second 16:9 diagnostic cases:

| Experiment | Values | Other factors |
| --- | --- | --- |
| Generation budget | 8k, 16k, 32k, 64k assistant tokens | 256x144, 4 fps |
| Resolution | 128x72, 256x144, 512x288 | Fixed selected budget, 4 fps |
| Output FPS | 2, 4, 8 fps | Fixed selected budget, 256x144 |

Specify and freeze the selected budget before the scaling study. With baseline
conditions shared, this is eight unique configurations rather than a 36-cell
full Cartesian product. Use a preselected representative case set and paired
comparisons. Expand only after a smoke test and budget accounting validation.

For each condition, N=D*f, and output size is H*W*N RGB pixels. A five-second
4-fps clip uses 20 frames displayed for 0.25 seconds each. Keep timestamps
consistent and preserve the same source scene; frame0 must match that
condition's prescribed conditioning image.

Run two separately labelled scaling studies if desired:

1. Fresh-agent scaling: the agent is tasked with each resolution/FPS and may
   adapt its program under the same budget. This measures generation capability.
2. Frozen-program scaling: an existing program is replayed at new settings if
   it supports them, without a model call. This measures program scalability;
   it is not evidence that the agent understood a higher-resolution input.

## Scoring under sampling changes

Higher FPS can expose short contacts and motion that low FPS misses; resolution
also changes perception and evaluator behavior. Compare against dedicated
generator outputs/reference degradation controls on the same sampling grid,
outside agent context, to distinguish sampling effects from agent quality.
Preserve each official evaluator's expected conversion and alignment rules.

Budget/FPS/resolution sweeps are labelled controlled scaling experiments unless
they match the official benchmark's submission contract. Do not place adapted
scores directly on a native-protocol leaderboard. Always report output
specifications alongside scores.

## Figures and tables

1. Quality vs token budget, with completion rate and paired uncertainty.
2. Quality vs USD cost and quality vs end-to-end latency; Pareto frontiers.
3. Quality, cost and latency vs output resolution and FPS.
4. Agent end-to-end throughput vs program replay throughput.
5. First valid candidate vs submitted final candidate under each budget.

A quality-preserving cost or latency reduction is a useful conclusion. A fast
invalid output is not counted as successful throughput. Report every budget
condition's failures and valid-but-weak outputs; do not filter them away.
