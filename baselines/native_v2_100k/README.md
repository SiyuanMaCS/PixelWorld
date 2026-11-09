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
