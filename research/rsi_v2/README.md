# RSI exploration v2: scene structure and targeted checks

The first v1 probe saved a video earlier but consumed more final tokens/time.
The paired contact sheet also showed visible background-fill and robot-motion
artifacts in both candidates. These observations come from generated pixels,
not hidden reference continuation or evaluator feedback.

v2 adds a general distinction between anchors, moving objects and connected
articulated parts. It supplies no case-specific masks, coordinates, trajectories
or solution code. The native baseline remains frozen at a5be771.

The next probe is the predeclared shared50 task0002, GPT-6.1-Sol/Vision-Agent,
100k budget, with identical inputs/tools/media and a fresh isolated output
directory. Its baseline is taken from the ongoing full queue. This is development
exploration; do not claim a full benchmark gain or an untouched test-set result.
Compare actual PA/IA and visual artifacts after generation, along with saved
RGB versions, timing and cost. Preserve negative outcomes.
