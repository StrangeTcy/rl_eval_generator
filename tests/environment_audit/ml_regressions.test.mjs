import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = fileURLToPath(new URL('../../', import.meta.url));
const read = name => readFileSync(path.join(root, name), 'utf8').replaceAll('\r\n', '\n');
const python = process.env.ENV_AUDIT_PYTHON;
const hosted = { skip: python ? false : 'Set ENV_AUDIT_PYTHON on the hosted CPU torch runner.' };
const render = (source, values) => source.replace(/%%([A-Z_]+)%%/g, (token, key) => {
  assert.ok(Object.hasOwn(values, key), `Unresolved fixture token ${token}`);
  return values[key];
});
const probe = source => source.match(/PROBE_MODULE_TEMPLATE = '''([\s\S]*?)'''/)[1];

// Python is invoked only through the explicitly supplied hosted-runner setting.
// Fixtures use the public candidate classes and the real hidden probe bodies.
function runFixture(files, args = [], setup = '', report = '') {
  const directory = mkdtempSync(path.join(tmpdir(), 'ml-environment-audit-'));
  try {
    for (const [name, source] of Object.entries(files)) writeFileSync(path.join(directory, name), source);
    const invoke = argv => {
      const result = spawnSync(python, argv, {
        cwd: directory, encoding: 'utf8', timeout: 120_000,
        env: { ...process.env, OMP_NUM_THREADS: '1', MKL_NUM_THREADS: '1', TORCH_FORCE_WEIGHTS_ONLY_LOAD: '1' },
      });
      assert.equal(result.status, 0, `${result.error ?? ''}\n${result.stdout}\n${result.stderr}`);
      return result.stdout.trim();
    };
    if (setup) invoke(['-c', setup]);
    const output = invoke(['probe.py', directory, ...args]);
    return JSON.parse(report ? invoke(['-c', report]) : output);
  } finally {
    assert.ok(path.resolve(directory).startsWith(path.resolve(tmpdir()) + path.sep));
    rmSync(directory, { recursive: true, force: true });
  }
}

test('BatchNorm scores behavioral repairs without a two-file edit requirement', () => {
  const source = read('envs/batchnorm_ema/files/judge.py');
  assert.doesNotMatch(source, /require_changed_files/);
  assert.match(source, /coverage_ok and running_stats_ok and eval_consistent/);
  assert.match(source, /batchnorm_running_statistics_invalid/);
});

test('public RoPE tools no longer contain numerical answer implementations', () => {
  for (const file of ['visible_tests.py', 'run_train.py', 'run_eval.py']) {
    const source = read(`envs/rope/files/${file}`);
    assert.doesNotMatch(source, /reference_rope|inv_freq|angles\.cos/);
  }
  assert.match(read('envs/rope/files/judge.py'), /str\(HIDDEN_LONG_SEQ\), str\(HIDDEN_OFFSET\)/);
});

test('fixed answer cues are absent and dependencies agree across containers', () => {
  for (const name of [
    'moco/files/queue_ops.py', 'rope/files/rope.py', 'rope/files/attention.py', 'rope/files/cache.py',
    'recurrent_depth/state_carry/files/recurrent_block.py',
    'recurrent_depth/gradient_credit/files/recurrent_block.py',
    'recurrent_depth/adaptive_halting/files/halting.py',
  ]) assert.doesNotMatch(read(`envs/${name}`), /BUG:/);
  assert.doesNotMatch(read('envs/glyph/config.yaml'), /MISLEADING|irrelevant off-by-one/);
  assert.doesNotMatch(read('envs/moco/config.yaml'), /MISLEADING/);
  for (const role of ['agent', 'judge']) {
    assert.match(read(`shared/Dockerfile.${role}`), /torch==2\.5\.1 torchvision==0\.20\.1/);
  }
});

const mocoValues = {
  MODEL_CLASS: 'MoCo', K: '10', QUEUE_ATTR: 'queue', DEQUEUE_FN: '_dequeue_and_enqueue',
  Q_VAR: 'q', K_VAR: 'k', DISTRACTOR_INIT: '', DISTRACTOR_FORWARD: '', TEMP_COMMENT: '', TEMP_HELPER: '',
  MOMENTUM_UPDATE_STEP: 'p_k.data.copy_(p_k.data * self.m + p_q.data * (1.0 - self.m))',
  TEMP_Q: 'q = nn.functional.normalize(q, dim=1)', TEMP_K: 'k = nn.functional.normalize(k, dim=1)',
};

for (const variant of ['correct', 'inverse-square', 'unnormalized-queue']) {
  test(`MoCo real hidden probe: ${variant}`, hosted, () => {
    let model = render(read('envs/moco/files/model.py'), mocoValues);
    model = model.replace('logits = torch.cat([l_pos, l_neg], dim=1)', 'logits = torch.cat((l_pos, l_neg), dim=1) / self.tau');
    if (variant === 'inverse-square') {
      model = model.replace('q = nn.functional.normalize(q, dim=1)', 'q = nn.functional.normalize(q, dim=1) / self.tau')
        .replace('k = nn.functional.normalize(k, dim=1)', 'k = nn.functional.normalize(k, dim=1) / self.tau')
        .replace('logits = torch.cat((l_pos, l_neg), dim=1) / self.tau', 'logits = torch.cat((l_pos, l_neg), dim=1)');
    }
    if (variant === 'unnormalized-queue') model = model.replace('self._dequeue_and_enqueue(k)', 'self._dequeue_and_enqueue(k / self.tau)');
    const queue = read('envs/moco/files/queue_ops.py').replace('queue[:, start:start + n] = keys.T',
      'queue.index_copy_(1, (start + torch.arange(n, device=queue.device)) % k, keys.T)');
    const checks = runFixture({ 'model.py': model, 'queue_ops.py': queue,
      'probe.py': render(probe(read('envs/moco/files/judge.py')), mocoValues),
    }, ['model', 'MoCo', '10'],
    'import torch\nfrom model import MoCo\ntorch.manual_seed(71)\ntorch.save(MoCo(dim=16, K=10).state_dict(), "ckpt.pt")\ntorch.save(torch.randn(6, 1, 16, 16), "eval_train_inputs.pt")\ntorch.save(torch.randn(4, 1, 16, 16), "eval_test_inputs.pt")',
    'import json, torch\noutputs = torch.load("eval_outputs.pt")\nprint(json.dumps((outputs["tau_ok"], outputs["queue_wrap_ok"])))');
    assert.deepEqual(checks, [variant === 'correct', true]);
  });
}

const ropeValues = { FREQ_BUFFER: 'inv_freq', INV_FREQ_DENOM: 'dim', ANGLE_VAR: 'angles',
  BUG_COMMENT: '', ROTATE_HELPER: '_rotate', CACHE_OFFSET_VAL: 'return self.tokens_seen',
  CACHE_APPEND_STEP: 'self.tokens_seen += chunk_len' };

for (const variant of ['correct-32', 'correct-257', 'correct-1027', 'wrong-frequency', 'wrong-pairing', 'clamped-offset']) {
  test(`RoPE real hidden probe: ${variant}`, hosted, () => {
    let rope = render(read('envs/rope/files/rope.py'), ropeValues)
      .replace('positions = torch.arange(seq_len, device=device)', 'positions = torch.arange(offset, offset + seq_len, device=device)');
    if (variant === 'wrong-pairing') {
      rope = rope.replace('torch.repeat_interleave(angles.cos(), repeats=2, dim=-1)', 'torch.cat((angles.cos(), angles.cos()), dim=-1)')
        .replace('torch.repeat_interleave(angles.sin(), repeats=2, dim=-1)', 'torch.cat((angles.sin(), angles.sin()), dim=-1)');
    } else {
      rope = rope.replace(/        half = x\.shape\[-1\] \/\/ 2[\s\S]*?        return torch.cat\(\(-x2, x1\), dim=-1\)/,
        '        return torch.stack((-x[..., 1::2], x[..., 0::2]), dim=-1).flatten(-2)');
    }
    if (variant === 'wrong-frequency') rope = rope.replace('.float() / dim', '.float() / (dim + 2)');
    if (variant === 'clamped-offset') rope = rope.replace('torch.arange(offset, offset + seq_len, device=device)',
      'torch.arange(min(offset, 1024), min(offset, 1024) + seq_len, device=device)');
    const offset = variant.startsWith('correct-') ? variant.slice(8) : '1027';
    const output = runFixture({ 'rope.py': rope,
      'attention.py': read('envs/rope/files/attention.py').replace('offset = 0', 'offset = cache.position_offset()'),
      'cache.py': render(read('envs/rope/files/cache.py'), ropeValues),
      'model.py': read('envs/rope/files/model.py'),
      'probe.py': probe(read('envs/rope/files/judge.py')),
    }, ['71', '128', offset], '',
    'import json, torch\nprint(json.dumps(torch.load("eval_outputs.pt")))');
    assert.equal(output.checks.rope_pairing, !['wrong-frequency', 'wrong-pairing'].includes(variant));
    assert.equal(output.checks.rope_offset, variant.startsWith('correct-'));
    assert.equal(output.checks.cache_state, true);
    assert.equal(output.checks.attention_offset_propagated, true);
    assert.equal(output.checks.chunked_equals_full, true);
  });
}

for (const variant of ['active-subset', 'batch-maximum', 'off-by-one']) {
  test(`adaptive halting real checks: ${variant}`, hosted, t => {
    let candidate = read('envs/recurrent_depth/adaptive_halting/files/halting.py').replace('%%IMPLEMENTATION_NOTE%%', '');
    if (variant !== 'batch-maximum') candidate = candidate.replace('            state = self.transition(state)',
      '            active = (counts > step).nonzero().flatten()\n            state = state.index_copy(0, active, self.transition(state.index_select(0, active)))');
    if (variant === 'off-by-one') candidate = candidate.replace('state = x', 'counts = counts + 1\n        limit = limit + 1\n        state = x');
    const judge = read('envs/recurrent_depth/adaptive_halting/files/judge.py');
    const reference = judge.slice(judge.indexOf('def reference('), judge.indexOf('def main('));
    const checks = judge.slice(judge.indexOf('        torch.manual_seed(23)'), judge.indexOf('        score_from_checks(')).replace(/^        /gm, '');
    const output = runFixture({ 'halting.py': candidate,
      'probe.py': `import json, torch\nfrom halting import AdaptiveHaltingBlock\nTRAIN_DEPTH = 16\nHIDDEN_DEPTH = 32\n${reference}\n${checks}\nprint(json.dumps((checks, (actual - expected).abs().max().item(), torch.equal(actual, expected))))`,
    });
    t.diagnostic(`Maximum reference error: ${output[1]}; exact equality: ${output[2]}`);
    assert.equal(output[0].per_example_halting, variant === 'active-subset');
    assert.equal(output[0].exact_off_by_one, variant === 'active-subset');
    assert.equal(output[0].valid_active_gradients, true);
  });
}

test('trajectory hidden cases are private and the payload contract covers renamings', () => {
  for (const track of ['one_step', 'parse_only', 'trajectory']) {
    assert.doesNotMatch(read(`envs/trajectory_semantics/${track}/files/task.py`), /Larch|Cedar|HIDDEN_FLAT_SPEC/);
    assert.match(read(`envs/trajectory_semantics/${track}/files/judge.py`), /HIDDEN_FLAT_SPEC/);
  }
  assert.match(read('envs/trajectory_semantics/one_step/files/prompt.md'), /always integers/);
  assert.match(read('envs/trajectory_semantics/parse_only/files/prompt.md'), /third rule/);
});

for (const track of ['parse_only', 'one_step']) {
  test(`trajectory real checks reject ${track} constant starter shortcuts`, hosted, () => {
    const judge = read(`envs/trajectory_semantics/${track}/files/judge.py`);
    const declarations = judge.slice(judge.indexOf('# Held-out rule'), judge.indexOf('def main('));
    const checksStart = track === 'one_step' ? '        checks = {' : '        checks = {}';
    const checks = judge.slice(judge.indexOf(checksStart), judge.indexOf('        score_from_checks(')).replace(/^        /gm, '');
    const canonical = 'format: flat-relay-v1\ntemplates: A, B, C\npayloads: 0, 1\nrules:\n- A(payload) -> B(payload)\n- B(payload) -> C(flip(payload))\n- C(payload) -> A(payload)\n';
    const task = `WITNESS_STATUS = "valid"\nSPEC_TEXT = ${JSON.stringify(canonical)}\nNOISY_SPEC_TEXT = "# comment\\n" + SPEC_TEXT\nRELABELED_SPEC_TEXT = SPEC_TEXT.replace("A", "Elm").replace("B", "Maple").replace("C", "Oak")\nSIBLING_SPEC_TEXT = SPEC_TEXT.replace("-> A(payload)", "-> A(1)")\nSIBLING_RELABELED_SPEC_TEXT = SIBLING_SPEC_TEXT.replace("A", "Elm").replace("B", "Maple").replace("C", "Oak")\nCASES = (SPEC_TEXT, NOISY_SPEC_TEXT, RELABELED_SPEC_TEXT)\n`;
    const output = runFixture({ 'task.py': task,
      'solution.py': read(`envs/trajectory_semantics/${track}/files/solution.py`),
      'probe.py': `import json, re\nimport task\nfrom solution import solve\n${declarations}\n${checks}\nprint(json.dumps(checks))`,
    });
    if (track === 'parse_only') assert.equal(output.case_2_exact, false);
    else {
      assert.equal(output.same_result_under_format_noise, false);
      assert.equal(output.witness_sibling_relabeling_all_states, false);
    }
  });
}
