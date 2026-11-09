# Native Codex baseline v2 / 100k

The generation code is frozen at commit
`a5be7711aa3f0011562524d150c0f31df65f43e1`. File hashes and the protocol are
in [protocol.json](protocol.json). Later RSI changes belong in separate
checkouts and run directories.

This baseline uses the user's existing Codex (validated with 0.167.0), Text
and Vision-Agent, fresh per-case context, autonomous inspection/revision,
and an externally monitored cumulative100,000 reported output-token allowance.
Reasoning is not counted twice. Request-end reporting can overshoot the limit.
No evaluator/reference feedback enters generation.

The [runtime profile](runtime_profile.json) records the validated Codex entrypoint,
normalized launch flags, common image/math package versions, prepared input
inventories, and hashes of one actual native task, compiled system messages
and tool schemas. The raw system/requests and credentials remain private.
`tools/record_baseline_provenance.py` can record another installation without
calling a model. It verifies the frozen source hashes and refuses an RSI task
override as a native-baseline sample.

`workspace-write` confines writes. It does not provide an OS boundary that
confines all reads to the case directory. Network/image-tool restrictions,
fresh context, disabled inherited instructions/skills/memory, and the successful
outside-task read audit are recorded separately. Runtime path/date descriptions
can differ; raw run traces preserve them. Do not infer stricter filesystem
isolation or unobservable provider-internal prompts from this profile.

Physics-IQ uses198 official I2V/BPP inputs,256×144,4FPS,20frames/5seconds.
RoboJudge uses the complete50 released shared-task identities, width256 with
original aspect ratio,4FPS,20frames/5seconds, and the disclosed paper-prefix1.
The original9B judge is used. Matching this shared50 configuration does not
prove equivalence to the paper Table8's unpublished selection/multiplicity.

Keep previous successful runs. Label reused legacy protocols and50k results
explicitly; they are not new controlled100k experiments. A budget extension
carries the same case's earlier reported tokens rather than resetting them.

## Run another model

Install your own Codex and API access, then clone PixelWorld. Do not install
a repository-specific Codex distribution. Follow [the Codex guide](../../docs/CODEX.md)
and [official data/evaluation setup](../../docs/REPRODUCING_OFFICIAL_EVAL.md).

Create a JSON config using [the provider template](../../configs/gpt55-responses.example.json),
replace its model ID, gateway URL and environment-key name with your own,
and export that API key in the parent shell. Never put it into a case workspace.
Use an explicit Responses-compatible provider; user-global Codex profiles are
deliberately not inherited by clean runs.

```bash
git worktree add --detach /path/to/pixelworld-native-baseline a5be7711aa3f0011562524d150c0f31df65f43e1
python -m pixelworld.cli doctor --config /path/to/my-config.json
python -m pixelworld.cli run-case --config /path/to/my-config.json --model my-model --track text --case 0001
```

Run the smoke from the frozen worktree, in every enabled Track, before the full
matrix. Use separate input inventories/output directories for each benchmark.

The current main branch supplies an external restartable supervisor:

```bash
python tools/manage_matrix.py --config /path/to/my-config.json \
  --code-root /path/to/pixelworld-native-baseline \
  --state /path/to/manager-state.json --resume
```

Launch this supervisor through your OS process manager/tmux/nohup, with stdin
detached. The supervisor uses the fixed checkout for generation, detects existing
live work, skips completed cases and preserves exhausted cases. `STOP` files are
explicit stops. It does not reset unknown or exhausted token budgets.

For Physics-IQ, use the original full evaluator watcher described in the setup
guide. For RoboJudge, run `tools/evaluate_robojudge_shared50.py prepare`, then
`run`, with generation/evaluation directories separated. Full means require
all50 actual paired PA/IA predictions; partial smoke must be explicitly labelled.

An interrupted stream has unknown final usage unless independent native records
close that uncertainty. `tools/prove_transport_accounting.py` accepts only an
explicit connection-stage rejection with no output and matching completed
request reports. Timeouts/disconnections remain unknown. Operational recoveries
must preserve the original failure, add this evidence outside the workspace,
carry the cumulative counter, and disclose their lineage. A completed video is
never regenerated to obtain a better score.
