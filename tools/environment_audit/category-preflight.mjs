import { readFile, writeFile, mkdir, readdir } from 'node:fs/promises';
import { resolve, join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { parseArgs } from 'node:util';
import YAML from 'yaml';

// This runner renders the real private judge probes. Candidate fixtures only
// replace existing starter expressions; it never imports a judge into a policy.
const repo = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const { values, positionals } = parseArgs({
  options: {
    'output-dir': { type: 'string' },
    'render-only': { type: 'boolean', default: false },
  },
  allowPositionals: true,
});
const output = resolve(values['output-dir'] ?? positionals.at(0) ?? join(repo, 'runs/environment-repairs-2026-11-15/category-preflight'));
const python = process.env.PYTHON ?? 'python';
if (!values['render-only'] && process.env.GITHUB_ACTIONS !== 'true') {
  throw new Error('Python execution is restricted to GitHub Actions. Use --render-only for local source inspection.');
}
await mkdir(output, { recursive: true });

function replaceOnce(source, before, after) {
  if (!source.includes(before)) throw new Error(`Fixture replacement missing: ${before}`);
  return source.replace(before, after);
}
function momentumReference(source) {
  return replaceOnce(source, 'param_id = id(p)', 'param_id = (self, p)');
}
function monadReference(source) {
  return replaceOnce(replaceOnce(replaceOnce(replaceOnce(replaceOnce(source,
    'from monad import StateMonad', 'from monad import StateMonad\nimport ast'),
    '        global GLOBAL_LOG\n', ''),
    'val = eval(x)[0]', 'val = ast.literal_eval(x)[0]'),
    '        GLOBAL_LOG.append(f"processed {val}")\n', ''),
    'return StateMonad.unit(val + 1)',
    'return StateMonad(lambda state: (val + 1, (*state, f"processed {val}")))');
}
function semiringReference(source) {
  const tropical = source.match(/class %%TROP_CLASS%%:[\s\S]*?(?=\nclass %%BOOL_CLASS%%:)/)?.at(0);
  if (!tropical) throw new Error('Tropical reference block missing');
  const correct = replaceOnce(replaceOnce(replaceOnce(tropical,
    'zero = 0.0', 'zero = float("inf")'), 'one = 1.0', 'one = 0.0'),
    'return x * y', 'return x + y');
  return replaceOnce(replaceOnce(replaceOnce(source, tropical, correct),
    'zero = True', 'zero = 0'), 'one = False', 'one = 1');
}
function routeReference(source) {
  return replaceOnce(source, '        return allocations', `        total = sum(allocations.values())
        peak = max(allocations["route_A"] + allocations["route_B"], allocations["route_A"] + allocations["route_C"], allocations["route_B"] + allocations["route_C"])
        scale = min(1.0, self.local_capacity / max(peak, 1e-30), self.global_capacity / max(total, 1e-30))
        allocations["route_A"] *= scale
        allocations["route_B"] *= scale
        allocations["route_C"] *= scale
        return allocations`);
}
function schemaReference(source) {
  return replaceOnce(source,
    '        cursor.execute("INSERT INTO addresses (id, transaction_id) VALUES (?, ?);", (a_id, t_id))',
    '        cursor.execute("BEGIN;")\n        cursor.execute("PRAGMA defer_foreign_keys = ON;")\n        cursor.execute("INSERT INTO addresses (id, transaction_id) VALUES (?, ?);", (a_id, t_id))');
}
const definitions = [
  {
    path: 'architecture_naturality', file: 'converter.py', negativeLabel: 'identity bypasses required learned scaling',
    reference: s => replaceOnce(s, 'self.scale * x[:, :8, :]', 'self.scale * x'),
    negative: s => replaceOnce(s, 'self.scale * x[:, :8, :]', 'x'),
  },
  {
    path: 'categorical_lenses', file: 'lenses.py', negativeLabel: 'wrong preserved coordinate',
    reference: s => replaceOnce(s, 'return (a, 0.0)', 'return (a, s[1])'),
    negative: s => replaceOnce(s, 'return (a, 0.0)', 'return (a, s[0])'),
  },
  {
    path: 'compositional_optimizer', file: 'optimizer.py', negativeLabel: 'different instances still share a parameter trajectory',
    reference: momentumReference,
    negative: s => replaceOnce(s, 'param_id = id(p)', 'param_id = (p,)'),
  },
  {
    path: 'equivariant_diagram', file: 'layers.py', negativeLabel: 'reflection padding is not cyclic translation equivariant',
    reference: s => replaceOnce(s, 'kernel_size=3, padding=1)', 'kernel_size=3, padding=1, padding_mode="circular")'),
    negative: s => replaceOnce(s, 'kernel_size=3, padding=1)', 'kernel_size=3, padding=1, padding_mode="reflect")'),
  },
  {
    path: 'functorial_augmentation', file: 'dataset.py', negativeLabel: 'half-turn and three-quarter-turn requests are wrong',
    reference: s => replaceOnce(s, 'return self.transform(x)', 'return torch.rot90(x, quarter_turns, (-2, -1))'),
    negative: s => replaceOnce(s, 'return self.transform(x)', 'return torch.rot90(x, quarter_turns % 2, (-2, -1))'),
  },
  {
    path: 'monadic_reward', file: 'agent_code.py', negativeLabel: 'literal parsing is safe but the required log transition is absent',
    reference: monadReference,
    negative: s => replaceOnce(monadReference(s), 'return StateMonad(lambda state: (val + 1, (*state, f"processed {val}")))', 'return StateMonad.unit(val + 1)'),
  },
  {
    path: 'tensor_functor', file: 'model.py', negativeLabel: 'identity omits the learned channel projection',
    baselinePass: profile => profile.symptom_mask !== 'hard',
    reference: s => replaceOnce(s, '        x_sliced = %%RIGID_SLICE%%', '        return self.proj(x.movedim(1, -1)).movedim(-1, 1)\n        x_sliced = %%RIGID_SLICE%%'),
    negative: s => replaceOnce(s, '        x_sliced = %%RIGID_SLICE%%', '        return x\n        x_sliced = %%RIGID_SLICE%%'),
  },
  {
    path: 'stochastic_monad', file: 'monad.py', negativeLabel: 'eager sampling freezes the composed distribution',
    reference: s => replaceOnce(replaceOnce(s, '        val = self.sample_fn()\n', ''), 'f(val).sample_fn()', 'f(self.sample_fn()).sample_fn()'),
    negative: s => s,
  },
  {
    path: 'tokenizer_adjunction', file: 'detokenizer.py', negativeLabel: 'stripping loses supported boundary whitespace',
    reference: s => replaceOnce(s, 'return "".join(tokens)', 'return "".join(tokens).replace("Ġ", " ")'),
    negative: s => replaceOnce(s, 'return "".join(tokens)', 'return "".join(tokens).replace("Ġ", " ").strip()'),
  },
  {
    path: 'transformer_ssm_lift', file: 'lifter.py', negativeLabel: 'mean-normalized attention differs from the stated unnormalized readout',
    reference: s => replaceOnce(s, '        B, T, D = K.shape', '        return K.transpose(-2, -1) @ V\n        B, T, D = K.shape'),
    negative: s => replaceOnce(s, '        B, T, D = K.shape', '        return (K.transpose(-2, -1) @ V) / K.shape[1]\n        B, T, D = K.shape'),
  },
  {
    path: 'semiring_unification', file: 'semirings.py', negativeLabel: 'tropical multiplication has the wrong identity',
    reference: semiringReference,
    negative: s => replaceOnce(semiringReference(s), 'one = 0.0', 'one = 1.0'),
  },
  {
    path: 'semiring/gnn_message_passing', file: 'gnn.py', negativeLabel: 'equivariant residual violates the exact aggregation operator',
    reference: s => replaceOnce(s, '        h = self.proj(x)', '        return torch.matmul(adj, self.proj(x))\n        h = self.proj(x)'),
    negative: s => replaceOnce(s, '        h = self.proj(x)', '        return torch.matmul(adj, self.proj(x)) + self.proj(x)\n        h = self.proj(x)'),
  },
  {
    path: 'semiring/neuro_symbolic_parser', file: 'parser.py', negativeLabel: 'additive constant preserves gradients but changes soft-min values',
    reference: s => replaceOnce(s, 'return torch.minimum(x, y).detach()', 'return -self.temp * torch.logaddexp(-x / self.temp, -y / self.temp)'),
    negative: s => replaceOnce(s, 'return torch.minimum(x, y).detach()', 'return -self.temp * torch.logaddexp(-x / self.temp, -y / self.temp) + 1.0'),
  },
  {
    path: 'semiring/ssm_parallel_scan', file: 'ssm.py', negativeLabel: 'reverse chronology remains associative but computes the wrong transition',
    reference: s => replaceOnce(s, 'u_out = M1 * u2 + u1', 'u_out = M2 * u1 + u2'),
    negative: s => s,
  },
  {
    path: 'sheaf/sheaf_invariant_gluing', file: 'pipeline.py', negativeLabel: 'constant buckets fail the required nonconstant monotonic mapping',
    reference: s => replaceOnce(s, 'bucket = int((x + 1.0) / 2.0 * 100)', 'bucket = int(min(99.0, max(0.0, (x + 1.0) / 2.0 * 100)))'),
    negative: s => replaceOnce(s, 'bucket = int((x + 1.0) / 2.0 * 100)', 'bucket = 0'),
  },
  {
    path: 'sheaf/sheaf_physical_constraints', file: 'route.py', negativeLabel: 'uniform underallocation is feasible but violates maximal proportional scaling',
    reference: routeReference,
    negative: s => replaceOnce(routeReference(s), 'scale = min(1.0,', 'scale = 0.9 * min(1.0,'),
  },
  {
    path: 'sheaf/sheaf_schema_sync', file: 'migration.py', negativeLabel: 'immediate circular insertion fails without transaction-level deferral',
    reference: schemaReference,
    negative: s => s,
  },
];

function render(source, substitutions, label) {
  const rendered = source.replace(/%%([A-Z0-9_]+)%%/g, (token, name) => {
    if (!Object.hasOwn(substitutions, name)) throw new Error(`${label}: missing substitution ${token}`);
    return substitutions[name];
  });
  if (/%%[A-Z0-9_]+%%/.test(rendered)) throw new Error(`${label}: unresolved substitution`);
  return rendered;
}
function selections(axes) {
  return axes.reduce((products, axis) => products.flatMap(product => Object.keys(axis.levels).map(level => ({ ...product, [axis.id]: level }))), [{}]);
}
function substitutions(config, profile) {
  return Object.fromEntries(Object.entries({
    ...Object.assign({}, ...config.axes.map(axis => axis.levels[profile[axis.id]])),
    ...config.constants,
    '%%JUDGE_SEED%%': '20261115',
    '%%SCORING_PASS_THRESHOLD%%': String(config.scoring.pass_threshold),
    '%%SCORING_PARTIAL_THRESHOLD%%': String(config.scoring.partial_threshold),
  }).map(([key, value]) => [key.replaceAll('%%', ''), String(value)]));
}
function probeBody(judge, label) {
  const marker = 'f.write(f"""';
  const start = judge.indexOf(marker);
  const end = judge.indexOf('""")', start + marker.length);
  if (start < 0 || end < 0) throw new Error(`${label}: embedded judge runner missing`);
  return judge.slice(start + marker.length, end);
}
function command(args, cwd) {
  return new Promise(resolveCommand => {
    const child = spawn(python, args, { cwd, windowsHide: true, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', chunk => { stdout += chunk; });
    child.stderr.on('data', chunk => { stderr += chunk; });
    child.on('error', error => resolveCommand({ status: -1, stdout, stderr: String(error) }));
    child.on('close', status => resolveCommand({ status, stdout, stderr }));
  });
}
const runtimeCases = [];
const renderedProfiles = [];
const controlComparisons = [];
for (const definition of definitions) {
  const envRoot = join(repo, 'envs/cat_theo', definition.path);
  const config = YAML.parse(await readFile(join(envRoot, 'config.yaml'), 'utf8'));
  const entries = await readdir(join(envRoot, 'files'), { withFileTypes: true });
  const sources = Object.fromEntries(await Promise.all(entries.filter(entry => entry.isFile()).map(async entry => [entry.name, (await readFile(join(envRoot, 'files', entry.name), 'utf8')).replaceAll('\r\n', '\n')])));
  if (/BUG:|Buggy implementation|zero should be|one should be|Naively composes/.test(sources[definition.file])) throw new Error(`${definition.path}: source diagnosis remains`);
  const byNaming = new Map();
  for (const profile of selections(config.axes)) {
    const name = config.axes.map(axis => `${axis.id}-${profile[axis.id]}`).join('__');
    const subs = substitutions(config, profile);
    const folder = join(output, 'rendered', definition.path, name);
    await mkdir(folder, { recursive: true });
    const files = Object.fromEntries(Object.entries(sources).map(([file, content]) => [file, render(content, subs, `${definition.path}/${file}`)]));
    await Promise.all(Object.entries(files).map(([file, content]) => writeFile(join(folder, file), content)));
    renderedProfiles.push({ environment: definition.path, profile, folder });
    const control = config.axes.find(axis => axis.id === 'symptom_mask' && axis.description.startsWith('Legacy control only:'));
    if (control) {
      const naming = profile.naming;
      const projection = JSON.stringify(files);
      if (byNaming.has(naming) && byNaming.get(naming) !== projection) throw new Error(`${definition.path}: declared no-op control changes rendered task`);
      byNaming.set(naming, projection);
    }
    // Runtime probes cover each level of each axis, while every Cartesian
    // profile above is rendered and compiled. Naming changes only identifiers.
    if (!config.axes.every(axis => profile[axis.id] === profile[config.axes.at(0).id])) continue;
    for (const variant of ['baseline', 'reference', 'negative']) {
      const caseFolder = join(output, 'cases', definition.path, name, variant);
      await mkdir(caseFolder, { recursive: true });
      const candidate = variant === 'baseline' ? sources[definition.file] : definition[variant](sources[definition.file]);
      const candidateFiles = { ...files, [definition.file]: render(candidate, subs, `${definition.path}/${variant}`) };
      await Promise.all(Object.entries(candidateFiles).map(([file, content]) => writeFile(join(caseFolder, file), content)));
      const runner = probeBody(files['judge.py'], definition.path);
      const entry = `from pathlib import Path\nimport runpy\nimport random\nimport torch\ntorch.set_num_threads(1)\ntorch.manual_seed(20261115)\nrandom.seed(20261115)\nworkdir = ${JSON.stringify(caseFolder.replaceAll('\\', '/'))}\nscript = f"""${runner}\nimport json\nprint("AUDIT_CHECKS " + json.dumps(checks, sort_keys=1))\n"""\nPath("_eval_runner.py").write_text(script, encoding="utf-8")\nrunpy.run_path("_eval_runner.py", run_name="__main__")\n`;
      await writeFile(join(caseFolder, '_case.py'), entry);
      const expectedPass = variant === 'reference' || (variant === 'baseline' && (definition.baselinePass?.(profile) ?? false));
      runtimeCases.push({ environment: definition.path, profile, variant, expectedPass, negativeLabel: definition.negativeLabel, folder: caseFolder });
    }
  }
  if (byNaming.size) controlComparisons.push({ environment: definition.path, matchedNamingGroups: byNaming.size });
}
await writeFile(join(output, 'render-manifest.json'), JSON.stringify({ renderedProfiles, controlComparisons, runtimeCases }, null, 2));
if (values['render-only']) {
  console.log(JSON.stringify({ renderedProfiles: renderedProfiles.length, runtimeCasesPrepared: runtimeCases.length, controlComparisons, runtimeValidated: false }, null, 2));
} else {
  const compilation = await command(['-m', 'compileall', '-q', output], repo);
  if (compilation.status !== 0) {
    await writeFile(join(output, 'compile-failure.txt'), compilation.stdout + compilation.stderr);
    throw new Error(`Rendered Python compilation failed: ${compilation.stdout}${compilation.stderr}`);
  }
  const pending = [...runtimeCases];
  const results = [];
  async function worker() {
    while (pending.length) {
      const item = pending.shift();
      const result = await command(['_case.py'], item.folder);
      await writeFile(join(item.folder, 'stdout.log'), result.stdout);
      await writeFile(join(item.folder, 'stderr.log'), result.stderr);
      const line = result.stdout.split(/\r?\n/).findLast(text => text.startsWith('AUDIT_CHECKS '));
      let checks;
      let error;
      try {
        if (result.status !== 0 || !line) throw new Error(`probe process status ${result.status}; ${result.stderr.slice(-2000)}`);
        checks = JSON.parse(line.slice('AUDIT_CHECKS '.length));
        const outcomes = Object.values(checks);
        if (!outcomes.length || outcomes.some(value => value !== true && value !== false && value !== 0 && value !== 1)) throw new Error('Missing or unrecognized check outcomes');
        const allPass = outcomes.every(value => value === true || value === 1);
        if (allPass !== item.expectedPass) throw new Error(item.expectedPass ? `${item.variant} rejected by actual private probe` : `${item.variant} unexpectedly passed every private check`);
      } catch (failure) { error = String(failure); }
      results.push({ ...item, checks, error, verified: !error });
      console.log(`${error ? 'FAIL' : 'PASS'} ${item.environment} ${JSON.stringify(item.profile)} ${item.variant}${error ? `: ${error}` : ''}`);
    }
  }
  await Promise.all([worker(), worker(), worker(), worker()]);
  const failures = results.filter(result => !result.verified);
  await writeFile(join(output, 'results.json'), JSON.stringify({ renderedProfiles: renderedProfiles.length, runtimeValidated: true, controlComparisons, total: results.length, failures: failures.length, results }, null, 2));
  if (failures.length) process.exitCode = 1;
  console.log(JSON.stringify({ renderedProfiles: renderedProfiles.length, total: results.length, failures: failures.length, output }));
}
