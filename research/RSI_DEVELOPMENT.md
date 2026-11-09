# Independent harness development

Baseline generation runs from immutable commit
`a5be7711aa3f0011562524d150c0f31df65f43e1`, while development overrides live
under `research/` and use independent clean contexts/output directories.
Generation never receives an evaluator score or reference continuation.

Two prompt-only development probes have generated validated RGB submissions.
The measurements below describe individual runs, not repeated-trial estimates.
Original9B development scoring is pending; no full-benchmark RSI improvement
is claimed.

| Development task | Variant | First saved candidate (s) | Final wall time (s) | Reported output tokens |
|---|---|---:|---:|---:|
| shared0000 | Native accepted retry | 310.1 | 554.2 | 17,489 |
| shared0000 | Candidate-first v1 | 221.1 | 740.1 | 22,795 |
| shared0002 | Native | 260.4 | 357.2 | 13,328 |
| shared0002 | Scene-structure v2 | 340.6 | 576.9 | 18,902 |

Earlier saving is not the same as cheaper final generation. V1 reduced time
to the first candidate but increased final time and tokens. V2 increased both.
API waiting affects wall time, so token use and actual candidate counts must
also be inspected.

For shared0000 the initial native attempt produced pixels but was rejected by
the frozen directory audit: a relative-parent path string was a label, not the
actual image read. Its unchanged failed state and trace are kept. The accepted
retry's cost is reported separately, not substituted for total case cost.

Reading the shared0002 source shows that both programs introduced hidden arm
geometry. The native program used a left-side shoulder; v2 used an offscreen
right-side shoulder and regenerated long links. Constant link lengths alone
do not establish correct source geometry or image continuity. The next
[observed-pose probe](rsi_v3/README.md) targets this issue without adding a
case-specific solution or exposing another program to generation.

The [public comparison](https://siyuanmacs.github.io/physics-iq-pixel-preview/rsi_comparison.html)
contains final playback, every saved candidate, actual inspection images and
tool traces. Single-case PA/IA scores will be labelled as development scores,
distinct from full shared50 means or published generator leaderboard values.
