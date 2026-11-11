# PhyGenBench official evaluation audit

The existing 160 PixelWorld generation captions match the official
`PhyGenBench/prompts.json` exactly, in the same order. This was checked against
[OpenGVLab/PhyGenBench revision f8642cb](https://github.com/OpenGVLab/PhyGenBench/tree/f8642cb796f3bcb01f0b7c1b2ec53b75d357c739).
Existing generation inputs and output protocols remain unchanged.

The published main leaderboard is an ensemble of hierarchical evaluators, not
a single interchangeable VLM rating:

1. Key phenomena: VQAScore `clip-flant5-xxl`, with CLIP retrieval.
2. Order: GPT-4o-0513 and LLaVA-Interleave-dpo-7B.
3. Naturalness: GPT-4o-0513 and InternVideo2-Stage2_1B-224p-f4.

The [official README](https://github.com/OpenGVLab/PhyGenBench/blob/f8642cb796f3bcb01f0b7c1b2ec53b75d357c739/README.md)
specifies GPT-4o-0513 and reports an A100-80G evaluation environment.
The current API guide does not identify a configured `gpt-4o-2024-05-13` route;
no replacement judge has been selected.

The [original aggregation code](https://github.com/OpenGVLab/PhyGenBench/blob/f8642cb796f3bcb01f0b7c1b2ec53b75d357c739/PhyGenEval/overall.py)
rounds each three-stage branch average, then takes the floored average of the
closed and open branch scores. The resulting 0–3 per-case score is normalized by
3 for the reported 0–1 mean. Preserve this rounding and aggregation when
reproducing the main leaderboard.

As a check, the released 160-case Kling result gives 0.4875 for the ensemble,
matching the reported 0.49. Its open-only mean is 0.5604, so an open-only result
must not be compared directly to the ensemble column. Do not replace the
specified GPT-4o version with a newer model and call the result an official
main-leaderboard score.

No baseline videos were downloaded or rerun during this audit. No PixelWorld
PhyGenBench score has been computed yet. Question files, evaluator weights and
results must stay outside generation workspaces.
