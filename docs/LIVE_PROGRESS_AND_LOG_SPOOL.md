# Live progress and API log storage

Model generation and experiment logging use separate storage paths. The model
prompt, tools, output contract, token budget and attempt policy are unchanged.

## API request logging

The adapter's request and response records belong on a local disk. An independent
process archives them to the shared filesystem. Generation never waits for that
archive process. Raw API records and credentials must not be published.

For an existing `responses_proxy.py` process, use:

```bash
python tools/spool_api_logs.py cutover \
  --log-dir "$EXPERIMENT/queue_proxy_logs" \
  --spool "$LOCAL_CACHE/pixelworld-api-spool" \
  --proxy-pid "$PROXY_PID"

python tools/spool_api_logs.py watch \
  --spool "$LOCAL_CACHE/pixelworld-api-spool" \
  --archive "$EXPERIMENT/queue_proxy_logs_archive"
```

The cutover verifies the proxy PID, preserves its loopback key, briefly suspends
that process while replacing its log path, and resumes it. Existing sessions and
model requests are not restarted. The original log directory is retained with a
`_legacy_<UTC timestamp>` suffix. The original path becomes a symlink to the local
spool, so detached workers keep using the same credential path.

The archive worker stores records under `YYYY-MM-DD/<request-prefix>/`. Local
records are retained; receipts and archive status also stay local. A slow or
unavailable shared filesystem increases the archive backlog rather than model
latency. Requests crossing the cutover can have early records in the retained
legacy directory and later records in the spool. Both locations are evidence.

Some proxy versions rewrite input/events records. This remains harmless to the
request path on local storage; archival receipts detect changed files and recopy
them. Monitor available local space and the archive backlog during long runs.

## Live video and trace viewing

`tools/live_benchmark_data.py` reads current run manifests, recorded token usage,
tool returns and saved RGB snapshots. It never edits an agent's workspace or
supplies generation feedback. A format-readable saved candidate can be viewed
while the agent is running; a candidate is not counted as a successful submission.

The public viewer polls the lightweight `pixelworld-live` data branch every
10 seconds. The publisher targets a 30-second cycle, with actual publication
duration recorded in `.publisher_status.json`. This data path does not wait for a
GitHub Pages deployment or the historical rich-page rendering backlog. End-to-end
freshness also depends on GitHub/network caching; this is live polling, not a
guaranteed instantaneous stream.

Every thirty seconds the publisher adds a small immutable pointer naming an
already-pushed commit. The viewer reads recent pointer paths and then fetches
metadata and assets from that exact commit. New paths avoid a stale raw-branch
CDN entry showing old counts after a successful push. No GitHub API request or
public credential is required. The viewer checks every ten seconds; normal
snapshot discovery trails publication by roughly thirty to sixty seconds.
On a slow or unavailable network the last usable snapshot remains visible.

Case reads and RGB exports run in four background workers. The publisher keeps
refreshing cohort progress while a slow case read is pending. Workers render to
a private local cache; only completed files move into the public checkout before
one serialized Git push. This also prevents incomplete candidate files from
being staged by a concurrent export.

The static Pages branch contains the viewer and navigation. The live branch
contains sanitized case metadata, input images, immutable candidate pixels,
inspection images and observable tool records. It excludes API payloads,
credentials, provider-internal reasoning and local absolute paths. Full raw
experiment traces stay private for analysis and later training exports.

Viewer code can be updated separately from the historical media upload:

```bash
python tools/publish_live_viewer.py --checkout "$LOCAL_CACHE/pixelworld-pages-delivery"
```

This uses the same publication lock as full Pages delivery and updates only the
live script and its HTML cache versions. A delayed large media push therefore
does not prevent deploying a viewer fix. It requires a clean dedicated Pages
checkout and preserves all existing media links.

```bash
python tools/live_benchmark_data.py \
  --run-root "$EXPERIMENT" \
  --checkout "$LOCAL_CACHE/pixelworld-live-delivery" \
  --interval 30
```

The checkout must be an initialized `pixelworld-live` branch with the authorized
public artifact repository as `origin`. The publisher stages only `pixelworld/`.
Model rows are discovered from status files, including newly added model keys.
Text and Vision share this publication mechanism. PhyGenBench's paired smoke
reports all four conditions: T2V-Text, T2V-Vision, I2V-Text, and I2V-Vision.

Running attempts expose current tokens and tools. Failed model attempts retain
their diagnostics; infrastructure interruptions are displayed as `stale`. Final
submission counts still come from the original supervisor status and validation.

`evaluation.json` carries verified full-cohort scores, original scorer revisions,
generation coverage and evaluator stages. A dedicated background reader updates
it without blocking candidate publication. Physics-IQ fractions are displayed
as `/100`; RoboJudge PA/IA retain their original 1–5 scale. RoboJudge's complete
shared-50 scope does not by itself establish comparability to the paper's Table 8.
That comparison remains explicitly unverified. Individual RoboJudge PA/IA values
appear on case pages when the complete paired evaluation passes verification.

Only allowlisted numerical score fields and sanitized blockers are public. An
incomplete cohort, mismatched scorer revision, duplicate task identity or
disagreement with current generation coverage prevents a full score claim.
Evaluator activity is checked against live process commands; a leftover execution
file alone does not establish that scoring is running.
