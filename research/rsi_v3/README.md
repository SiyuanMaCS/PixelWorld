# RSI v3: observed-pose continuation

This is a development prompt experiment. It does not modify the frozen native
baseline. The task override is recorded in each run's input provenance.

The preceding shared-task 0002 programs preserved constant link lengths while
inventing different hidden shoulder locations. A connected arm can still have
an incorrect image-space starting geometry. V3 therefore asks for continuation
from the observed pose with minimal hidden-geometry assumptions, rather than
adding a more detailed scene reconstruction checklist.

Predeclared next probe: RoboJudge shared task `common50_0003`, GPT-6.1-Sol,
Vision-Agent, high reasoning effort, cumulative100k reported output tokens,
width256 with source aspect ratio,4FPS and20frames. Use a fresh context, the
same frozen generation checkout and support files, and a separate output root.
Reuse the original accepted native baseline for the comparison. Do not send
reference continuations, scores, baseline programs or other cases to the agent.

Save every candidate and raw trace. Compare candidate and final video quality,
PA/IA using the same original9B evaluator, cost, and first saved candidate time.
One development pair cannot establish general improvement; an adverse outcome
is retained. This probe was started before receiving either earlier RSI pair's
9B scores. No quality gain has yet been demonstrated.
