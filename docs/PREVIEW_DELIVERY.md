# Preview delivery with exact media

The stable preview remains at <https://siyuanmacs.github.io/pixelworld/>. Source pages and all original pixel/media artifacts stay on `main` in `SiyuanMaCS/SiyuanMaCS.github.io`. The small, generated **`pixelworld-pages`** branch serves GitHub Pages.

The previous Pages artifact approached 1 GiB and deployments repeatedly reached the platform timeout. The delivery artifact contains HTML, CSS, JS and small metadata. PixelWorld PNGs, compressed RGB tensors, input MP4s and downloadable binary artifacts are fetched from **the same repository at the exact source commit**. The initial artifact is about **27.6 MB**, while the media remain unchanged on `main`.

`tools/prepare_pages_site.py` builds this artifact. It rewrites media references in existing pages and player JSON without regenerating or resampling pixels. It reads committed Git blobs, so unrelated unstaged edits in the personal site are not published. The personal homepage and other site sections retain their committed contents.

The publisher's optional `--delivery-repo` points to a **dedicated, publisher-owned Git checkout**. The publisher initializes it on `pixelworld-pages`, records ownership under `.git`, publishes the small tree and retries failed pushes. Do not point it at a development checkout.

```bash
python -m tools.sync_stable_pixelworld_pages \
  --run-root /path/to/experiment \
  --heavy-web /path/to/preview-staging \
  --stable-repo /path/to/SiyuanMaCS.github.io \
  --status /path/to/experiment/publication_status.json \
  --delivery-repo /path/to/dedicated-pages-checkout \
  --core-only --interval 300
```

For a new deployment, first publish the generated branch, then set the existing site's **Settings → Pages → Deploy from a branch → `pixelworld-pages`, `/`**. The REST equivalent is `PUT /repos/{owner}/{repo}/pages` with `{"build_type":"legacy","source":{"branch":"pixelworld-pages","path":"/"}}`. A manual `POST /repos/{owner}/{repo}/pages/builds` can request the first build.

Source commits and publication commits are separate and recorded in the publisher status. The deployed `pixelworld-publication.json` records the exact media revision. The deployment guard covers Pages jobs on every branch and defers publication while a deployment is active. The publisher attempts bounded updates every five minutes; the browser pages refresh every minute when no video is playing.

Model galleries expose a detail link only when its render receipt matches the current run **and** the detail is already committed or included in the current publication batch. A locally prepared but uncommitted preview is labelled as syncing instead of producing a public 404. Old attempts and original media stay in the source repository and experiment records.

This delivery layer changes hosting only. Generation prompts, models, input clips, tensor values, FPS, resolution, evaluation scope and evaluator pins are unchanged.
