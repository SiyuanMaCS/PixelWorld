# Benchmark service recovery

Generation tasks, candidate history, budgets and successful submissions remain
unchanged. Service recovery operates outside agent workspaces.

Run the service chain from an explicit local specification:

```bash
python tools/watch_benchmark_services.py --spec path/to/benchmark_services.json
```

The specification lists each service's command, working directory, PID file,
log, exact command-line identity, dependencies, and optional pause marker.
Credentials are read from environment files; do not place their contents in the
specification or commit the local specification. The watchdog checks actual
process identity, rejects zombie/reused PIDs, and holds a single-instance lock.

The current approved service chain covers Physics-IQ, RoboJudge and
PCVE-RigidBench: the loopback model API relay, failed-case retry watcher,
benchmark evaluators, and GitHub Pages publisher. Completed groups are reused.
Explicit VBench/PhyGenBench generation and evaluation pause markers are retained.

Failed-case retry monitoring preserves all attempts and uses the existing
two-attempt, 100k-token retry windows with a 300-second cooldown. It skips groups
already reported complete, updates its heartbeat between configurations, and
locks manager creation to prevent duplicate restarts. Model-visible prompts
and generation rules are unaffected.

Recovery may enable `prioritize_less_attempted_cases` in the local scheduling
limits. A repeatedly failing early case then cannot occupy every new slot while
later cases have never been attempted. Existing attempts stay recorded, failed
cases remain eligible for retry, and no continuation prompt or evaluation
feedback is added to the agent conversation.

Final-video previews use `quick.html`, with the same RGB tensor player as the
rich review pages. They can be published before detailed candidate/trace pages
finish rendering. Failed/unvalidated submissions cannot receive these previews.
Preview receipts are invalidated if the submitted tensor or contract changes.
Final video and rich trace publication progress are recorded separately.
Rich pages render in at most two detached local workers into staging; publication
consumes ready pages and does not wait for a long candidate/trace render.

Paused benchmark trace backlogs do not block currently active suites. A local
`preview_priority.json` may temporarily prioritize unfinished groups during
recovery; its deadline restores completed-group trace catchup automatically.
Only changed case directories and overview files are staged for core refreshes.

A detached watchdog survives terminal closure, but not an entire host reboot.
Use the host's available process manager to restart it, or a durable TRAE task
that runs recovery when the owning daemon/session is restored. TRAE recurring
tasks have a seven-day lifetime; they are not an unconditional OS boot service.
