PixelWorld generation and publication recovery
============================================

Keep the frozen generation configurations and their code roots intact when
recovering a stopped machine. Do not delete successful submissions or failed
attempt directories. `tools/watch_benchmark_services.py` supervises only services
explicitly listed in its JSON specification, checking both PID ownership and
command identity before restarting a service. A stop marker in that specification
preserves an intentional pause.

The current recovery scope is Physics-IQ, RoboJudge and PCVE. VBench and
PhyGenBench video generation remain paused. Initial-image preparation has a
separate authorization and does not resume their video experiments.

Trace rendering can run independently of the publisher:

```bash
python -u tools/watch_preview_rendering.py \
  --run-root runs/bench_codex_20261109 \
  --web-root /path/to/the/existing/web/root \
  --workers 4 --interval 60
```

Register this command in the existing service specification to restart it after
a process exit. It prepares terminal attempts in `preview_render_jobs`, placing
rendered pages in the existing web root. It does not alter agent workspaces,
candidate histories, budgets or evaluation inputs. The existing publisher consumes
ready pages and publishes them to GitHub Pages. `build_one_preview.py` holds an
output lock so the publisher and renderer can discover the same attempt safely.

Monitor `preview_renderer_status.json` for rendering progress and
`stable_pixelworld_refresh_status.json` for completed publication. A prepared
page is not yet a deployed page. Validate a public detail URL and fetch and
decompress its RGB payload before claiming its resources are usable.

GPU readiness and dependency downloads are separate from generation progress.
Preserve the evaluator's model names and precision. Retry interrupted downloads
with their existing cache, preserving logs. A live scheduler is not evidence that
inference has completed; use evaluator summaries and prediction files for scores.
