#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root. Each generated directory is a normal target
# environment; complete an ANSWER assignment before submitting to the judge.
python generate_env.py \
  --env epistemic_reasoning \
  --name epistemic_event_demo \
  --difficulty event_sparse,compact \
  --seed 42

python generate_env.py \
  --env epistemic_reasoning \
  --name epistemic_announcement_demo \
  --difficulty announcement_checked,expanded \
  --seed 17

python epistemic_event_demo/agent/workspace/visible_tests.py
python epistemic_announcement_demo/agent/workspace/visible_tests.py

printf '\nGenerated examples:\n  epistemic_event_demo/\n  epistemic_announcement_demo/\n'
printf 'Read each prompt.md and task.json, edit answer.py, then run its run_eval.sh.\n'
