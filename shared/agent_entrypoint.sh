#!/usr/bin/env bash
set -euo pipefail

# /workspace is mounted as writable tmpfs by run_eval.sh when the container is
# started read-only. Populate it from immutable originals baked into the image.
cp -a /originals/. /workspace/
cd /workspace
exec /bin/bash
