# Paired PhyGenBench initial conditions

PhaseLock's [Appendix E](https://arxiv.org/html/2606.06361v2#A5) adapts the original
160-prompt T2V PhyGenBench to I2V using FLUX-schnell and
`gemini-2.5-flash-image-preview`. Its published T2I construction example is:

```text
Original Prompt + ", static scene immediately before the action."
```

The public main/gh-pages branches, release page and linked galleries were
checked. No complete 160-case first-frame package or input manifest was found.
The paper does not specify complete T2I sampling parameters or per-case image
selection. A locally regenerated set is a new input version, rather than the
exact images behind the paper's I2V baseline scores.

The user-authorized local construction is `phygen_i2v_qwen21_v1`:

- Original captions: OpenGVLab/PhyGenBench revision
  `f8642cb796f3bcb01f0b7c1b2ec53b75d357c739`, all 160 rows in original order.
- Initializer: `Qwen/Qwen-Image-2.1`, revision
  `d26bb61231c349cf6b7896fa83353113880e1ba3`.
- Diffusers revision: `0905b667fe3f37f43b6ef9c6e05ad20636206938`.
- Image output: RGB, 1024 x 576, 40 steps, bfloat16; three seeds per task.
- Video prompt: the original caption, byte-for-byte unchanged.
- Image prompt: the original caption, the PhaseLock static-state suffix, and a
  shared photographic/initial-state instruction documented in the run manifest.
- Sampling seeds: `20261111 + 100 * source_index + candidate_index`.

Only captions enter the initializer task files. Physical-law answers,
evaluation questions, reference continuations and scores remain outside them.

Four tasks covering mechanics, optics, thermal and material are generated first.
Actual image inspection must verify object identity/count, scene match, framing,
photographic appearance and the state before the event. Full construction
follows this smoke review. Preserve all candidates, prompts, seeds, timings,
image hashes, selected candidate IDs and selection reasons. Do not claim a
visual review from a numeric check or an uninspected contact sheet.

The initial images are constructed separately from the PixelWorld coding agent.
All generation artifacts remain in the shared repository run directory; the
SSH worker supplies GPU computation. Existing PhyGenBench T2V video runs remain
paused and their protocols/results are not replaced by this initialization.
