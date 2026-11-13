# Physics-IQ resolution and Seedance comparison

Verified against the pinned official README, actual reference/generated video
streams, and the Seedance leaderboard submission on 2026-11-13.

| Condition | Resolution | Native FPS | Evaluated duration / frames |
|---|---:|---:|---:|
| Official recorded reference | 3840×2160 | 30 | 5 seconds / 150 |
| Existing local Seedance 2.5 normalized comparison | 1280×720 | 24 | 5 seconds / 120 |
| PixelWorld high-resolution cohort currently running | 512×288 | 24 | 5 seconds / 120 |

The official reference recording specifications are not a requirement that a
generator emit 4K at 30 FPS. The original evaluator prepares references at the
submitted frame rate. Keep actual generation resolution/FPS in result metadata.

## Next conditions proposed, not launched

- 1280×720 / 24 FPS / 120 frames: compare output resolution at the current FPS;
  this has 6.25 times the pixel count of 512×288 / 24 FPS.
- 1280×720 / 30 FPS / 150 frames: a separate temporal sampling comparison using
  the reference recording's true frame rate; 7.8125 times the current pixel count.
- 60 FPS may test rendering throughput and smoothness, but does not add measured
  temporal information to the 30 FPS reference recordings.

For output-only scaling, retain the current conditioning information. The
existing 512×288 inputs enlarge the canonical 256×144 image with LANCZOS. For an
end-to-end high-quality condition, downsample the original official 4K switch
image directly to 720p instead. This changes both input detail and output
resolution, so report it as a distinct condition. Neither proposal modifies
already-generated images or videos.

## Seedance temporal alignment

[Official leaderboard PR 85](https://github.com/google-deepmind/physics-IQ-benchmark/pull/85)
states native 24 FPS evaluation with 120 frames, four independent runs, and
removal of Seedance's repeated conditioning frame: generated frames 1–120 were
evaluated from a 121-frame output. The PR text inspected did not establish the
Seedance output resolution; the 720p measurement above belongs to our local copy.

Our local normalized Seedance copy trims the first five seconds and preserves
resolution. It therefore retains frames 0–119, while the public submission used
frames 1–120. PixelWorld's existing 120-frame output also includes its mandatory
conditioning frame 00. Do not equate these temporal conventions or silently
rewrite existing submissions. Preserve raw clips and verify exact alignment
before a quantitative comparison. The local Seedance collection contains 197
successful clips and one rejected task, so it is a qualitative comparison pool,
not an independently complete official 198-case baseline.

Source: [official benchmark README](https://github.com/google-deepmind/physics-IQ-benchmark#key-features).
