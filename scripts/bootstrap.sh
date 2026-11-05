#!/usr/bin/env bash
set -euo pipefail
uv venv --python 3.11 .venv
. .venv/bin/activate
uv pip install -e '.[dev]'
pixelworld doctor --config configs/benchmark.example.json
