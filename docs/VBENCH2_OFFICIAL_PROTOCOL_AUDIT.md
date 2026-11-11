# VBench-2.0 selected-dimension sampling audit

The pinned official source requires **three independent videos per prompt** in
standard mode for Mechanics, Material, Motion_Rationality,
Dynamic_Spatial_Relationship and Instance_Preservation.

Source: [VBench2 input validation at the pinned revision](https://github.com/Vchitect/VBench/blob/fd18b3d055cb0fc6f066ca90fe2c3c8cbb698490/VBench-2.0/vbench2/__init__.py).
`build_full_info_json` sets `num=3` for non-Diversity dimensions, looks for video
indices `-0`, `-1`, `-2`, and raises when a required video is missing.
`check_dimension_requires_extra_info` also rejects `custom_input` mode for all
five selected dimensions.

The ongoing PixelWorld experiment has one generated video per dimension prompt:
291 dimension rows per model/track, or 2,910 videos across five models and two
tracks. Its current artifacts are not a complete standard VBench-2.0 submission.
Completing the standard selected-dimension sampling would require 873 videos per
model/track, or 8,730 in total without cross-dimension deduplication.

Keep existing generation inputs, budgets and outputs unchanged. Do not copy one
video into three filenames or silently patch the evaluator to ignore missing
samples. Additional independent generations require the experiment owner's
decision. A directly adapted single-sample metric run must be labeled as a
nonstandard sampling setting, not a standard or full VBench-2.0 result.

Selecting five dimensions also remains distinct from the complete 18-dimension
VBench-2.0 score. The standard three-video requirement is separate from
Physics-IQ's four-run aggregation option.
