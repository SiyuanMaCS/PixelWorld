# Release checklist

- [ ] `pytest -q` passes in a fresh Python 3.11 environment.
- [ ] `pixelworld doctor --config ...` is green.
- [ ] A fresh case passes every enabled Track before a full matrix.
- [ ] No credentials, local absolute paths, generated runs, references, masks, or scores are tracked.
- [ ] Physics-IQ evaluator commit, dataset revision, prompt hash, FPS, duration, and resolution are unchanged or the protocol version is bumped.
- [ ] Public examples contain environment-variable names only.
- [ ] Generated outputs and official data remain in ignored directories.
- [ ] The visual site is tested for playback and Trace links.
