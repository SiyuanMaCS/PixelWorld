# Independent harness development

Baseline generation runs from immutable commit
`a5be7711aa3f0011562524d150c0f31df65f43e1`, while development overrides live
under `research/` and use independent clean contexts/output directories.
Generation never receives an evaluator score or reference continuation.

Three prompt-only development probes have generated validated RGB submissions.
The measurements below describe individual runs, not repeated-trial estimates.
All three pairs have now been scored by the original9B evaluator. No
full-benchmark RSI improvement is claimed.

| Development task | Variant | First saved candidate (s) | Final wall time (s) | Reported output tokens |
|---|---|---:|---:|---:|
| shared0000 | Native accepted retry | 310.1 | 554.2 | 17,489 |
| shared0000 | Candidate-first v1 | 221.1 | 740.1 | 22,795 |
| shared0002 | Native | 260.4 | 357.2 | 13,328 |
| shared0002 | Scene-structure v2 | 340.6 | 576.9 | 18,902 |
| shared0003 | Native | 210.8 | 487.4 | 15,336 |
| shared0003 | Observed-pose v3 | 259.0 | 528.4 | 13,993 |

Earlier saving is not the same as cheaper final generation. V1 reduced time
to the first candidate but increased final time and tokens. V2 increased both.
API waiting affects wall time, so token use and actual candidate counts must
also be inspected.

V3 used about9% fewer output tokens on its development task, but saved its
first candidate later and increased final wall time by about8%. It retained
four distinct RGB candidates versus three for the native program. This is a
mixed cost result; PA decreased by one point and no general benefit is inferred.

| Development task | Native PA / IA | RSI PA / IA | Interpretation |
|---|---:|---:|---|
| shared0000 | 3 / 3 | 4 / 3 | V1 has a one-point PA gain on this probe, with higher cost per accepted execution. |
| shared0002 | 4 / 4 | 2 / 3 | V2 worsens both axes while increasing time and tokens. |
| shared0003 | 4 / 3 | 3 / 3 | V3 reduces tokens slightly but worsens PA and increases time. |

These are model scores on development videos, not human labels or full50 means.
The judge rationales identify contact and transfer ambiguities. Semantic
completion remains partial: the requested fruit set, actual toasting, or sorting
all products is not clearly completed. Rationales are model statements; frame
evidence is needed before asserting a causal error.

For shared0000 the initial native attempt produced pixels but was rejected by
the frozen directory audit: a relative-parent path string was a label, not the
actual image read. Its unchanged failed state and trace are kept. The accepted
retry's cost is reported separately, not substituted for total case cost. The
two native executions together used35,276 output tokens, compared with22,795
for the singleV1 execution. Thus a higher accepted-attempt cost is compatible
with lower case-delivery cost when the control incurred an audit retry. This
does not establish that the V1 prompt is generally more efficient.

Reading the shared0002 source shows that both programs introduced hidden arm
geometry. The native program used a left-side shoulder; v2 used an offscreen
right-side shoulder and regenerated long links. Constant link lengths alone
do not establish correct source geometry or image continuity. This is a
two-arm task specifying the left gripper: image-side position alone does not
prove manipulator identity. The completed [observed-pose probe](rsi_v3/README.md)
targets continuation without receiving another program; its lower PA score
shows that this added hint alone is insufficient.

The [public comparison](https://siyuanmacs.github.io/physics-iq-pixel-preview/rsi_comparison.html)
contains final playback, every saved candidate, actual inspection images and
tool traces. Single-case PA/IA scores will be labelled as development scores,
distinct from full shared50 means or published generator leaderboard values.
