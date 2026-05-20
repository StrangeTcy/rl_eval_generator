#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="%%ENV_NAME%%"
JUDGE_SEED="%%JUDGE_SEED%%"
AGENT_IMAGE="${ENV_NAME}_agent"
JUDGE_IMAGE="${ENV_NAME}_judge"
SUBMISSION_VOL="${ENV_NAME}_submission"

echo "=== Building agent image ==="
docker build -t "$AGENT_IMAGE" -f agent/Dockerfile agent/

echo "=== Building judge image ==="
docker build -t "$JUDGE_IMAGE" -f judge/Dockerfile .

echo "=== Creating submission volume ==="
docker volume create "$SUBMISSION_VOL" >/dev/null

echo "=== Starting agent sandbox ==="
echo "Edit files in /workspace, run python /tools/submit.py, then exit."
docker run --rm -it \
  --read-only \
  --network none \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 256 \
  --ulimit nofile=1024:1024 \
  --memory 4g \
  --cpus 2 \
  --tmpfs /workspace:size=512m \
  --tmpfs /tmp:size=256m \
  -v "${SUBMISSION_VOL}:/submission" \
  "$AGENT_IMAGE"

echo "=== Running judge ==="
docker run --rm \
  --read-only \
  --network none \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 256 \
  --ulimit nofile=1024:1024 \
  --memory 6g \
  --cpus 2 \
  --tmpfs /tmp:size=1g \
  -e "JUDGE_SEED=${JUDGE_SEED}" \
  -v "${SUBMISSION_VOL}:/submission:ro" \
  "$JUDGE_IMAGE"

docker volume rm "$SUBMISSION_VOL" >/dev/null
