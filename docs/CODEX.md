# Codex integration

PixelWorld uses `codex exec --json` as a subprocess. It does not call a model API directly. This preserves the coding-agent loop—reasoning, shell/Python, file edits, and optional visual inspection—while making model/provider identity replaceable.

PixelWorld never installs Codex. The executable is resolved from
`PIXELWORLD_CODEX` when set, otherwise from `PATH`. Users keep their own Codex
version, authentication, and model access; `pixelworld doctor` reports the
resolved binary and version before a run.

For a complete collaborator-facing checklist, including where outputs should be
stored and how monitoring pages are published, see
[ADD_MODEL_RUNBOOK.md](ADD_MODEL_RUNBOOK.md).

## Model routing

`provider.type = builtin` selects the CLI's built-in provider with `--model MODEL`.
New clean runs ignore the user's config, so a custom gateway configured only in
the user's default profile is not implicitly inherited. Use an explicit
`responses` provider for those models; use environment-based authentication for
the built-in provider.

`provider.type = responses` constructs an invocation-local provider:

```text
-c model_provider="gateway"
-c model_providers.gateway.name="Gateway"
-c model_providers.gateway.base_url="https://api.example.com/v1"
-c model_providers.gateway.wire_api="responses"
-c model_providers.gateway.env_key="GATEWAY_API_KEY"
```

The secret stays in the parent process environment. `shell_environment_policy.inherit=none` keeps it out of model-generated shell commands.

If an API offers only Chat Completions, Anthropic Messages, or Gemini `generateContent`, expose it through a Codex-supported provider/Responses adapter first. PixelWorld does not silently translate protocols because adapters can change tool-calling and image semantics.

## Clean context

Each case uses:

- a new CLI session with a fresh per-run home;
- `--ignore-user-config`: no user instructions/provider side effects/plugins;
- `--ignore-rules`: no inherited exec policy;
- `project_doc_max_bytes=0`: no inherited `AGENTS.md`;
- `skills.bundled.enabled=false`: no bundled/system skill catalog;
- a fresh per-run `CODEX_HOME`: no user skill, memory, plugin, or session files;
- a new workspace containing only the fixed rules/helpers and the case inputs;
- no inherited session, fork, memory, skill, or nested subagent.

New v2 runs intentionally retain the full CLI rollout **outside** the model's
workspace to record returned images, code/tool messages and usage for analysis
and SFT candidates. Persistence records this run; it does not load an old
context. Legacy ephemeral launch settings are retained where configured.
An explicitly recorded infrastructure recovery may resume the **same case's**
own session and outputs after an interrupted request. It carries the original
usage forward and supplies no reference/score feedback; it never imports another
case's session. Preserve the failed execution evidence and recovery provenance.

The API credential store is not copied into the workspace.
For Responses providers, authentication comes from the named parent-process
environment variable, so the isolated home needs no auth file. For the builtin
provider, use environment-based OpenAI authentication or prepare an externally
isolated credential mechanism; do not copy a readable auth file into the case
workspace.

## Track enforcement

New configurations default to Text and Vision-Agent. Vision-Agent autonomously
decides whether and how often to inspect or refine outputs. Vision-Input remains
available only when explicitly requested by a legacy configuration; named v1
configurations preserve their historical defaults.

The initial attachment and `view_image` feature gate are command-level differences. JSONL audit is the second layer. Do not implement Tracks by changing prose only.

Codex capabilities evolve. `pixelworld doctor` checks the installed version and
`view_image` feature. Current live validation uses separately installed Codex
**0.167.0**, with successful Text and Vision-Agent runs through an explicit
Responses provider. Historical 0.166.0 runs remain valid legacy artifacts;
other versions should rerun checks and a smoke in every enabled Track.

For API-backed providers, an optional `model_catalog_json` is copied into a
per-run immutable snapshot outside the workspace. The command refers to that
snapshot, not a changing user menu. `stream_idle_timeout_ms` can accommodate
queue latency. Client request/stream retries are explicitly zero: any transparent
adapter retry must be justified and recorded, such as an explicit pre-sampling
queue rejection with the same request context.

## Runtime budget

New non-legacy configurations default to a 100,000 cumulative API output-token
threshold, monitored outside the agent. No fixed review count or 15-minute wall
deadline is imposed. Recovery attempts share the case allowance. Because usage
is reported after requests, overshoot is recorded; this is not an exact request
cap. See [TOKEN_RUNTIME_BUDGET.md](TOKEN_RUNTIME_BUDGET.md).

Legacy v1 settings remain unchanged unless explicitly configured. The separate
20-minute stalled-file-change recovery is for local execution failure, not an
equal-time model budget.
