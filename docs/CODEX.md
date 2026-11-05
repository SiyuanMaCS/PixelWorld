# Codex integration

PixelWorld uses `codex exec --json` as a subprocess. It does not call a model API directly. This preserves the coding-agent loop—reasoning, shell/Python, file edits, and optional visual inspection—while making model/provider identity replaceable.

PixelWorld never installs Codex. The executable is resolved from
`PIXELWORLD_CODEX` when set, otherwise from `PATH`. Users keep their own Codex
version, authentication, and model access; `pixelworld doctor` reports the
resolved binary and version before a run.

## Model routing

`provider.type = builtin` passes only `--model MODEL`. Authentication and availability come from the local Codex installation.

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

- `--ephemeral`: no persisted session;
- `--ignore-user-config`: no user instructions/provider side effects/plugins;
- `--ignore-rules`: no inherited exec policy;
- `project_doc_max_bytes=0`: no inherited `AGENTS.md`;
- `skills.bundled.enabled=false`: no bundled/system skill catalog;
- a fresh per-run `CODEX_HOME`: no user skill, memory, plugin, or session files;
- a new workspace containing only the fixed rules/helpers and the case inputs;
- no resume, fork, memory, skill, or subagent.

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

Codex capabilities evolve. `pixelworld doctor` checks the installed version and `view_image` feature. The validated baseline is 0.166.0; newer versions should rerun unit tests and a smoke in every enabled Track.

## Runtime budget

PixelWorld does not cap reasoning or review count. The only watchdog is a 20-minute recovery for a proven local `file_change` that remains in progress with no new JSONL event. API latency, ordinary reasoning, and repeated review are not capped by that watchdog.
