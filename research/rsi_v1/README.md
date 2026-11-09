# RSI exploration v1: produce a candidate before local precision work

This is an exploratory task-prompt intervention. It does not change or replace
the frozen native baseline at `a5be771`.

The initial diagnostic is the existing RoboJudge shared50 task0000,
GPT-6.1-Sol/Vision-Agent, identical100k budget, inputs, tools, environment and
media settings. Its native-baseline job is already in the full queue and will
not be regenerated. The RSI job has a separate fresh context/output directory.

Motivation comes from the observed DeepSeek task0001 traces: both50k runs spent
their allowance on input analysis/mask preparation before saving any video.
Text had drafted generator code when execution was cut; Vision iterated masks
without reaching a runnable video. This does not establish that every model or
task has the same failure, or that early candidates improve final quality.

The variant adds a general candidate-first priority. It supplies no region,
trajectory, solution code, reference continuation, mask or evaluation feedback.
The hypothesis is earlier valid delivery with less token expenditure and no
material loss in final physical/semantic/visual quality. If quality declines,
report the tradeoff; do not declare an improvement from speed alone.

Compare exact saved RGB candidates, first-valid and final tokens/latency, actual
tools/images, and the original9B PA/IA results after generation. One case is a
diagnostic, not a benchmark ranking or evidence of a universal improvement.
Further variants and test cases must be recorded separately; tuned exploratory
cases must not be presented as an untouched full test suite.
