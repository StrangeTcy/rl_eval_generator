import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = fileURLToPath(new URL('../../', import.meta.url));
const read = name => readFileSync(path.join(root, name), 'utf8').replaceAll('\r\n', '\n');
const category = name => `envs/cat_theo/${name}`;
const python = process.env.ENV_AUDIT_PYTHON;
const hosted = { skip: python ? false : 'Set ENV_AUDIT_PYTHON on the hosted CPU torch runner.' };
const sources = new Map([
  ['architecture_naturality', 'converter.py'], ['categorical_lenses', 'lenses.py'],
  ['compositional_optimizer', 'optimizer.py'], ['equivariant_diagram', 'layers.py'],
  ['functorial_augmentation', 'dataset.py'], ['monadic_reward', 'agent_code.py'],
  ['tensor_functor', 'model.py'], ['stochastic_monad', 'monad.py'],
  ['tokenizer_adjunction', 'detokenizer.py'], ['transformer_ssm_lift', 'lifter.py'],
  ['semiring_unification', 'semirings.py'], ['semiring/gnn_message_passing', 'gnn.py'],
  ['semiring/neuro_symbolic_parser', 'parser.py'], ['semiring/ssm_parallel_scan', 'ssm.py'],
  ['sheaf/sheaf_invariant_gluing', 'pipeline.py'], ['sheaf/sheaf_physical_constraints', 'route.py'],
  ['sheaf/sheaf_schema_sync', 'migration.py'],
]);
const defaults = {
  MODEL_CLASS: 'AuditCandidate', ARITH_CLASS: 'Arithmetic', TROP_CLASS: 'Tropical', BOOL_CLASS: 'Boolean',
  CHECK_DIM: 'dim=1', STRICT_LAWS: '1e-5', LR_VAL: '1e-3', SYMMETRY_DIM: 'shift_h=1, shift_w=2',
  AUG_PARAM: '3', SIDE_EFFECT_CHECK: 'True', SIGMA_VAL: '1e-3', UNICODE_SUPPORT: '  café 世界  🚀  ',
  TOLERANCE: '1e-5', JUDGE_SEED: '71', DEFER_CONSTRAINTS: '', GLOBAL_CAP: '150.0',
  DIM_CHECK: 'self.size = 4', RIGID_SLICE: 'x[:, :, :self.size, :self.size]',
  INF_VAL: 'float("inf")', THRESHOLD: '1000.0',
  SCORING_PASS_THRESHOLD: '0.85', SCORING_PARTIAL_THRESHOLD: '0.60',
};
const render = (source, values = {}) => source.replace(/%%([A-Z_]+)%%/g, (token, key) => {
  assert.ok(Object.hasOwn({ ...defaults, ...values }, key), `Unresolved fixture token ${token}`);
  return { ...defaults, ...values }[key];
});
const replace = (source, before, after) => {
  assert.ok(source.includes(before), `Missing fixture anchor: ${before}`);
  return source.replace(before, after);
};

// Run the real generated judge body against files copied into an isolated directory.
// Python is used only when the caller explicitly supplies the hosted interpreter setting.
const runProbe = (env, candidate, values = {}, extra = '') => {
  const directory = mkdtempSync(path.join(tmpdir(), 'category-environment-audit-'));
  try {
    const files = path.join(root, category(`${env}/files`));
    for (const file of readdirSync(files).filter(name => name.endsWith('.py') && !['judge.py', 'visible_tests.py'].includes(name))) {
      const source = file === sources.get(env) && candidate !== undefined ? candidate : read(category(`${env}/files/${file}`));
      writeFileSync(path.join(directory, file), render(source, values));
    }
    const judge = read(category(`${env}/files/judge.py`));
    const match = judge.match(/f\.write\(f"""([\s\S]*?)"""\)/);
    assert.ok(match, `${env} has an emitted evaluation body`);
    const body = render(match[1], values).replaceAll('{workdir!r}', JSON.stringify(directory))
      .replaceAll('{{', '{').replaceAll('}}', '}');
    writeFileSync(path.join(directory, 'probe.py'), `import torch\ntorch.manual_seed(71)\n${body}\n${extra}\nimport json\nprint(json.dumps(checks))\n`);
    const result = spawnSync(python, ['probe.py'], {
      cwd: directory, encoding: 'utf8', timeout: 120_000,
      env: { ...process.env, OMP_NUM_THREADS: '1', MKL_NUM_THREADS: '1', PYTHONDONTWRITEBYTECODE: '1' },
    });
    assert.equal(result.status, 0, `${env}: ${result.error ?? ''}\n${result.stdout}\n${result.stderr}`);
    return JSON.parse(result.stdout.trim().split('\n').at(-1));
  } finally {
    assert.ok(path.resolve(directory).startsWith(path.resolve(tmpdir()) + path.sep));
    rmSync(directory, { recursive: true, force: true });
  }
};
const allPassed = checks => Object.values(checks).every(value => value === true || value === 1);
const starter = env => read(category(`${env}/files/${sources.get(env)}`));

test('all 17 original category sources omit repair diagnoses', () => {
  assert.equal(sources.size, 17);
  for (const [env, file] of sources) {
    assert.doesNotMatch(read(category(`${env}/files/${file}`)), /BUG:|Buggy implementation|Buggy non-associative|zero should be|one should be|Replace this with|This collapses|This causes all composed/);
  }
  assert.doesNotMatch(read(category('semiring_unification/files/prompt.md')), /The Bug|standard zero instead of infinity/);
});

test('each repaired semantic axis reaches executable probe code', () => {
  const axes = new Map([
    ['architecture_naturality', 'CHECK_DIM'], ['categorical_lenses', 'STRICT_LAWS'],
    ['compositional_optimizer', 'LR_VAL'], ['equivariant_diagram', 'SYMMETRY_DIM'],
    ['functorial_augmentation', 'AUG_PARAM'], ['semiring/neuro_symbolic_parser', 'TOLERANCE'],
    ['stochastic_monad', 'SIGMA_VAL'], ['tokenizer_adjunction', 'UNICODE_SUPPORT'],
  ]);
  for (const [env, axis] of axes) {
    const executable = read(category(`${env}/files/judge.py`)).split('\n').filter(line => !line.trim().startsWith('#')).join('\n');
    assert.ok(executable.includes(`%%${axis}%%`), `${env} consumes ${axis}`);
    assert.match(read(category(`${env}/config.yaml`)), new RegExp(`evaluator_state:\\n      placeholders: \\[${axis}\\]`));
  }
  assert.match(starter('compositional_optimizer'), /class %%MODEL_CLASS%%/);
  assert.match(read(category('monadic_reward/config.yaml')), /presentation-only control; all safety checks run/);
  assert.match(read(category('monadic_reward/files/prompt.md')), /%%SIDE_EFFECT_CHECK%%/);
});

test('category specifications disclose the evaluated operators and supported domains', () => {
  assert.match(read(category('semiring/gnn_message_passing/files/prompt.md')), /A @ self\.proj\(X\)/);
  assert.match(read(category('semiring/ssm_parallel_scan/files/prompt.md')), /reverse order is also associative/);
  assert.match(read(category('semiring/ssm_parallel_scan/files/prompt.md')), /batched diagonal coefficients/);
  assert.match(read(category('sheaf/sheaf_physical_constraints/files/prompt.md')), /largest common scale/);
  assert.match(read(category('compositional_optimizer/files/prompt.md')), /repeats updates/);
  assert.match(read(category('tokenizer_adjunction/files/prompt.md')), /supported domain excludes/);
  assert.match(read(category('transformer_ssm_lift/files/prompt.md')), /unnormalized linear-attention/);
  assert.match(read(category('monadic_reward/config.yaml')), /"monad", "ast"/);
  assert.match(read(category('functorial_augmentation/files/prompt.md')), /deterministic C4/);
  assert.doesNotMatch(read(category('sheaf/sheaf_schema_sync/files/judge.py')), /require_changed_files/);
  assert.match(read(category('sheaf/sheaf_schema_sync/files/prompt.md')), /empty patch is allowed/);
});

const repairs = new Map([
  ['architecture_naturality', source => replace(source, 'self.scale * x[:, :8, :]', 'self.scale * x')],
  ['categorical_lenses', source => replace(source, 'return (a, 0.0)', 'return (a, s[1])')],
  ['compositional_optimizer', source => replace(source, '        pass', '        self.state = self.state.copy()')],
  ['equivariant_diagram', source => replace(source, 'kernel_size=3, padding=1)', 'kernel_size=3, padding=1, padding_mode="circular")')],
  ['functorial_augmentation', source => replace(source, 'return self.transform(x)', 'return torch.rot90(x, quarter_turns, (-2, -1))')],
  ['tensor_functor', source => source.slice(0, source.indexOf('        x_sliced =')) + '        return self.proj(x.movedim(-3, -1)).movedim(-1, -3)\n'],
  ['stochastic_monad', source => replace(source, '        val = self.sample_fn()\n        return %%MODEL_CLASS%%(lambda: f(val).sample_fn())', '        return %%MODEL_CLASS%%(lambda: f(self.sample_fn()).sample_fn())')],
  ['tokenizer_adjunction', source => replace(source, 'return "".join(tokens)', 'return "".join(tokens).replace("Ġ", " ")')],
  ['transformer_ssm_lift', source => source.slice(0, source.indexOf('        B, T, D =')) + '        return K.transpose(-1, -2) @ V\n'],
  ['semiring_unification', source => replace(replace(source, 'class %%TROP_CLASS%%:\n    zero = 0.0\n    one = 1.0', 'class %%TROP_CLASS%%:\n    zero = float("inf")\n    one = 0.0').replace(/(class %%TROP_CLASS%%:[\s\S]*?)return x \* y/, '$1return x + y'), '    zero = True\n    one = False', '    zero = 0\n    one = 1')],
  ['semiring/gnn_message_passing', source => source.slice(0, source.indexOf('        h =')) + '        return adj @ self.proj(x)\n'],
  ['semiring/neuro_symbolic_parser', source => replace(source, 'torch.minimum(x, y).detach()', '-self.temp * torch.logaddexp(-x / self.temp, -y / self.temp)')],
  ['semiring/ssm_parallel_scan', source => replace(source, 'u_out = M1 * u2 + u1', 'u_out = M2 * u1 + u2')],
  ['sheaf/sheaf_invariant_gluing', source => replace(replace(source, 'return math.tanh(x)', 'return 0.0 if math.isnan(x) else math.tanh(x)'), 'bucket = int((x + 1.0) / 2.0 * 100)', 'bucket = min(99, max(0, int((x + 1.0) / 2.0 * 100)))')],
  ['sheaf/sheaf_physical_constraints', source => replace(source, '        return allocations', `        a = allocations.get("route_A", 0.0)
        b = allocations.get("route_B", 0.0)
        c = allocations.get("route_C", 0.0)
        scale = min(1.0, self.local_capacity / max(a + b, a + c, b + c, 1e-30), self.global_capacity / max(a + b + c, 1e-30))
        allocations["route_A"] = a * scale
        allocations["route_B"] = b * scale
        allocations["route_C"] = c * scale
        return allocations`)],
  ['sheaf/sheaf_schema_sync', source => replace(source, '        cursor.execute("INSERT INTO addresses', '        cursor.execute("PRAGMA defer_foreign_keys = ON;")\n        cursor.execute("INSERT INTO addresses')],
]);

test('all category reference fixtures render before hosted execution', () => {
  for (const [env, repair] of repairs) {
    const baseline = starter(env);
    const candidate = repair(baseline);
    assert.notEqual(candidate, baseline, `${env} fixture must modify the starter`);
    assert.doesNotMatch(render(candidate), /%%[A-Z_]+%%/);
    assert.doesNotMatch(render(read(category(`${env}/files/judge.py`))), /%%[A-Z_]+%%/);
  }
});

for (const [env, repair] of repairs) {
  test(`${env}: actual hidden probe accepts repair and rejects starter`, hosted, () => {
    const baseline = runProbe(env, starter(env));
    assert.equal(allPassed(baseline), false, `Starter unexpectedly passed: ${JSON.stringify(baseline)}`);
    const repaired = runProbe(env, repair(starter(env)));
    assert.equal(allPassed(repaired), true, `Repair failed: ${JSON.stringify(repaired)}`);
  });
}

for (const tolerance of ['1e-5', '1e-4']) {
  test(`soft-min values reject constant offsets at tolerance ${tolerance}`, hosted, () => {
    const env = 'semiring/neuro_symbolic_parser';
    const candidate = repairs.get(env)(starter(env)).replace('return -self.temp', 'return 0.5 - self.temp');
    const checks = runProbe(env, candidate, { TOLERANCE: tolerance });
    assert.equal(checks.basic_run, 0);
    assert.equal(checks.gradient_flow_ok, 1);
  });
}

test('SSM reverse chronology is associative and fails the sequential reference', hosted, () => {
  const checks = runProbe('semiring/ssm_parallel_scan');
  assert.equal(checks.associativity_commutes, true);
  assert.equal(checks.basic_run, false);
});

test('GNN residual is equivariant but violates the disclosed exact operator', hosted, () => {
  const env = 'semiring/gnn_message_passing';
  const candidate = repairs.get(env)(starter(env)).replace('return adj @ self.proj(x)', 'return self.proj(x) + adj @ self.proj(x)');
  const checks = runProbe(env, candidate);
  assert.equal(checks.permutation_equivariance, true);
  assert.equal(checks.basic_run, false);
});

for (const width of ['0', '7']) {
  test(`deterministic C4 coverage at width increment ${width}`, hosted, () => {
    const env = 'functorial_augmentation';
    const repaired = runProbe(env, repairs.get(env)(starter(env)), { AUG_PARAM: width });
    assert.equal(allPassed(repaired), true);
    const identity = runProbe(env, starter(env).replace('return self.transform(x)', 'return x'), { AUG_PARAM: width });
    assert.equal(identity.basic_run, 1);
    assert.equal(identity.symmetry_preserved, 0);
  });
}

for (const sigma of ['1e-5', '1e-2']) {
  test(`seeded stochastic laws remain scale-aware at sigma ${sigma}`, hosted, () => {
    const env = 'stochastic_monad';
    assert.equal(allPassed(runProbe(env, repairs.get(env)(starter(env)), { SIGMA_VAL: sigma })), true);
    assert.equal(runProbe(env, starter(env), { SIGMA_VAL: sigma }).right_identity, 0);
  });
}

test('tokenizer enforces the marker-free domain and reconstructs boundary inputs', hosted, () => {
  const env = 'tokenizer_adjunction';
  const extra = `assert detok.detokenize(tokenize("")) == ""
assert detok.detokenize(tokenize("  café\\t世界  ")) == "  café\\t世界  "
try:
    tokenize("literal Ġ marker")
except ValueError:
    checks["reserved_marker_rejected"] = 1
else:
    checks["reserved_marker_rejected"] = 0`;
  assert.equal(allPassed(runProbe(env, repairs.get(env)(starter(env)), {}, extra)), true);
});

test('deferred circular-schema baseline passes without a cosmetic edit', hosted, () => {
  const checks = runProbe('sheaf/sheaf_schema_sync', undefined, { DEFER_CONSTRAINTS: 'DEFERRABLE INITIALLY DEFERRED' });
  assert.equal(allPassed(checks), true);
});

for (const scenario of ['deferred-empty', 'immediate-empty', 'deferred-missing', 'deferred-malformed']) {
  test(`schema generated judge entry point: ${scenario}`, hosted, () => {
    const directory = mkdtempSync(path.join(tmpdir(), 'schema-judge-integration-'));
    try {
      for (const child of ['judge', 'originals', 'workspace', 'submission', 'tmp']) mkdirSync(path.join(directory, child));
      const values = {
        DEFER_CONSTRAINTS: scenario.startsWith('deferred') ? 'DEFERRABLE INITIALLY DEFERRED' : '',
        PATCHABLE_FILES: '("migration.py",)', EXTRA_ALLOWED_IMPORTS: '"sqlite3"',
      };
      for (const file of ['judge_lib.py', 'patch_validator.py', 'source_validator.py']) {
        writeFileSync(path.join(directory, 'judge', file), render(read(`shared/${file}`), values));
      }
      writeFileSync(path.join(directory, 'judge', 'judge.py'), render(read(category('sheaf/sheaf_schema_sync/files/judge.py')), values));
      for (const file of ['migration.py', 'prompt.md', 'visible_tests.py']) {
        const source = render(read(category(`sheaf/sheaf_schema_sync/files/${file}`)), values);
        writeFileSync(path.join(directory, 'originals', file), source);
        writeFileSync(path.join(directory, 'workspace', file), source);
      }
      const patchPath = path.join(directory, 'submission', 'agent.patch');
      if (scenario.endsWith('empty')) {
        // Bind the generated interactive submit script's deployment paths to this fixture.
        const submit = render(read('shared/submit.py'), values)
          .replaceAll('"/workspace"', JSON.stringify(path.join(directory, 'workspace')))
          .replaceAll('"/originals"', JSON.stringify(path.join(directory, 'originals')))
          .replaceAll('"/submission/agent.patch"', JSON.stringify(patchPath))
          .replaceAll('"/submission"', JSON.stringify(path.join(directory, 'submission')));
        writeFileSync(path.join(directory, 'submit.py'), submit);
        const submitted = spawnSync(python, ['submit.py'], { cwd: directory, encoding: 'utf8', timeout: 30_000 });
        assert.ifError(submitted.error);
        assert.equal(submitted.status, 0, `${submitted.stdout}\n${submitted.stderr}`);
        assert.equal(readFileSync(patchPath, 'utf8'), '');
      } else if (scenario.endsWith('malformed')) {
        writeFileSync(patchPath, 'not a unified patch\n');
      }
      const result = spawnSync(python, [path.join(directory, 'judge', 'judge.py')], {
        cwd: directory, encoding: 'utf8', timeout: 120_000,
        env: {
          ...process.env, JUDGE_PATCH_PATH: patchPath,
          JUDGE_ORIGINALS_DIR: path.join(directory, 'originals'),
          TMPDIR: path.join(directory, 'tmp'), TMP: path.join(directory, 'tmp'), TEMP: path.join(directory, 'tmp'),
          PYTHONDONTWRITEBYTECODE: '1', OMP_NUM_THREADS: '1', MKL_NUM_THREADS: '1',
        },
      });
      assert.ifError(result.error);
      const verdict = JSON.parse(result.stdout);
      assert.equal(result.status, scenario === 'deferred-empty' ? 0 : 1, `${result.stdout}\n${result.stderr}`);
      if (scenario.endsWith('empty')) {
        assert.equal(verdict.checks.patch_found, true);
        assert.equal(verdict.checks.patch_valid, true);
        assert.equal(verdict.checks.sources_valid, true);
        assert.equal(verdict.stage_outcomes.patch_validation.code, 'empty_patch_accepted');
        assert.equal(verdict.stage_outcomes.source_validation.code, 'trusted_originals');
        assert.equal(verdict.checks.global_gluing_ok, scenario === 'deferred-empty');
        assert.equal(verdict.verdict, scenario === 'deferred-empty' ? 'PASS' : 'FAIL');
        if (scenario === 'deferred-empty') assert.equal(verdict.score, 1);
      } else {
        assert.equal(verdict.failure_mode, scenario.endsWith('missing') ? 'patch_missing' : 'patch_invalid');
        assert.equal(verdict.checks.patch_valid, false);
        assert.equal(verdict.stage_outcomes.patch_validation.status, 'failed');
      }
    } finally {
      assert.ok(path.resolve(directory).startsWith(path.resolve(tmpdir()) + path.sep));
      rmSync(directory, { recursive: true, force: true });
    }
  });
}

test('physical feasibility is reported separately from proportional utilization', hosted, () => {
  const env = 'sheaf/sheaf_physical_constraints';
  const candidate = replace(starter(env), '        return allocations', `        allocations["route_A"] = min(allocations.get("route_A", 0.0), 50.0)
        allocations["route_B"] = min(allocations.get("route_B", 0.0), 50.0)
        allocations["route_C"] = min(allocations.get("route_C", 0.0), 50.0)
        return allocations`);
  const checks = runProbe(env, candidate);
  assert.equal(checks.local_bounds_ok, 1);
  assert.equal(checks.local_proportional_ok, 0);
  assert.equal(checks.global_backbone_ok, 1);
  assert.equal(checks.global_proportional_ok, 0);
});
