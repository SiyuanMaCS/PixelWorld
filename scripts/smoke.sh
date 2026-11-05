#!/usr/bin/env bash
set -euo pipefail
config=${1:-configs/smoke.local.json}
pixelworld matrix run --config "$config"
pixelworld matrix status --config "$config"
pixelworld web build --config "$config" --output site-smoke
