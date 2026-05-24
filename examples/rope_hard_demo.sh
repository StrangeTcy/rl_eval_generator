#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRACE="$ROOT/examples/rope_hard_reference_human_trace.jsonl"
EPISODE="rope_hard_reference"
PATCH_OFFSET="$ROOT/examples/rope_hard_patch_offset_only.patch"
PATCH_PAIRING="$ROOT/examples/rope_hard_patch_pairing.patch"
PATCH_FREQ="$ROOT/examples/rope_hard_patch_frequency.patch"
PATCH_ATTENTION_CACHE="$ROOT/examples/rope_hard_patch_attention_cache.patch"

cd "$ROOT"
rm -rf ".episodes/$EPISODE"
: > "$TRACE"

compact_json() {
  python -c 'import json,sys; print(json.dumps(json.load(sys.stdin), ensure_ascii=False))'
}

record_reset() {
  python env_runner.py reset \
    --env rope \
    --episode-id "$EPISODE" \
    --difficulty hard,hard,hard,hard,hard,hard,hard \
    --seed 1 \
    --max-steps 40 | compact_json >> "$TRACE"
}

step() {
  python env_runner.py step --episode "$EPISODE" --action "$1" | compact_json >> "$TRACE"
}

patch_action() {
  local patch_file="$1"
  python - <<PY
import json
from pathlib import Path
patch = Path("$patch_file").read_text()
print(json.dumps({"type": "apply_patch", "patch": patch}))
PY
}

record_reset
step '{"type":"read_file","path":"prompt.md"}'
step '{"cmd":"ls -R . /tools/"}'
step '{"type":"read_file","path":"rope.py"}'
step '{"cmd":"grep -n theta_table rope.py; grep -n \"positions =\" rope.py; grep -n \"def _phase_shift\" rope.py; grep -n \"half =\" rope.py"}'
step '{"cmd":"python /tools/extract_pdf.py paper_excerpt.pdf --out paper_excerpt.md"}'
step '{"cmd":"python /tools/read_paper.py index"}'
step '{"cmd":"python /tools/read_paper.py rotary_derivation"}'
step '{"cmd":"cat .rope_tool_state.json"}'

# First plausible but incomplete repair: use absolute positions for chunks.
step "$(patch_action "$PATCH_OFFSET")"
step '{"cmd":"grep -n \"positions =\" rope.py"}'

# The index showed a missing appendix, so retry extraction until it appears.
step '{"cmd":"python /tools/extract_pdf.py paper_excerpt.pdf --out paper_excerpt.md"}'
step '{"cmd":"python /tools/extract_pdf.py paper_excerpt.pdf --out paper_excerpt.md"}'
step '{"cmd":"python /tools/read_paper.py index"}'
step '{"cmd":"python /tools/read_paper.py appendix_incremental"}'

# Second repair: adjacent real coordinates are the complex pairs.
step "$(patch_action "$PATCH_PAIRING")"
step '{"cmd":"grep -n \"0::2\" rope.py; grep -n \"1::2\" rope.py; grep -n \"def _phase_shift\" rope.py"}'

# Third repair: propagate offsets through cache and attention.
step "$(patch_action "$PATCH_ATTENTION_CACHE")"
step '{"cmd":"grep -n \"position_offset\" cache.py attention.py; grep -n \"tokens_seen +=\" cache.py; grep -n \"cache.position_offset\" attention.py"}'

# Final hard-mode repair: long-context drift comes from wrong frequency scaling.
step "$(patch_action "$PATCH_FREQ")"
step '{"cmd":"grep -n theta_table rope.py"}'
step '{"cmd":"python -m py_compile rope.py attention.py cache.py model.py"}'
step '{"cmd":"python - <<\u0027PY\u0027\nfrom pathlib import Path\nrope = Path(\u0027rope.py\u0027).read_text()\nattention = Path(\u0027attention.py\u0027).read_text()\ncache = Path(\u0027cache.py\u0027).read_text()\nchecks = {\n    \u0027frequency_denominator_dim\u0027: \u0027/ dim))\u0027 in rope,\n    \u0027offset_used_in_rope\u0027: \u0027torch.arange(offset, offset + seq_len\u0027 in rope,\n    \u0027even_odd_rotation\u0027: \u00270::2\u0027 in rope and \u00271::2\u0027 in rope,\n    \u0027cache_advances\u0027: \u0027self.tokens_seen += chunk_len\u0027 in cache,\n    \u0027attention_reads_cache_offset\u0027: \u0027cache.position_offset()\u0027 in attention,\n}\nprint(checks)\nassert all(checks.values())\nPY"}'

if [ "${RUN_TORCH_DIAGNOSTICS:-0}" = "1" ]; then
  step '{"cmd":"pytest visible_tests.py -v"}'
  step '{"cmd":"python /tools/run_train.py all"}'
  step '{"cmd":"python /tools/run_eval.py"}'
  step '{"cmd":"python /tools/inspect_logs.py"}'
fi

echo "wrote $TRACE"
