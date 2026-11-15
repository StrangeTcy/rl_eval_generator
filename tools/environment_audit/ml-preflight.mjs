import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import YAML from 'yaml';

const root = process.cwd();
const output = path.resolve(process.argv[2] ?? 'runs/environment-audit/ml');
const python = process.env.PYTHON ?? 'python';
const rows = [];
const environment = {...process.env, PYTHONDONTWRITEBYTECODE: '1', PYTHONPYCACHEPREFIX: path.join(output, 'cache')};
fs.mkdirSync(output, {recursive: true});

function run(args, cwd = root, extra = {}) {
  const result = spawnSync(python, args, {cwd, env: {...environment, ...extra}, encoding: 'utf8', timeout: 180000});
  if (result.error) throw result.error;
  return result;
}
function checked(args, cwd, label) {
  const result = run(args, cwd);
  fs.writeFileSync(path.join(output, label + '.stdout'), result.stdout);
  fs.writeFileSync(path.join(output, label + '.stderr'), result.stderr);
  assert.equal(result.status, 0, `${label}: ${result.stdout}${result.stderr}`);
  return result.stdout;
}
function record(row) {
  rows.push(row);
  fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify({
    scope: 'Real generated hidden probes and halting judge; no provider calls or classifier training campaigns.',
    rows,
  }, null, 2) + '\n');
  console.log(`${row.id}: ${JSON.stringify(row.checks ?? row.score)}`);
}
function generate(name, folder, level) {
  const config = YAML.parse(fs.readFileSync(path.join(folder, 'config.yaml'), 'utf8'));
  const id = `${name}-${level}`;
  const instance = path.join(output, id);
  checked(['generate_env.py', '--env', name, '--name', instance,
    '--difficulty', config.axes.map(() => level).join(','), '--seed', '41'], root, id + '-generation');
  const compiled = run(['-m', 'compileall', '-q', instance]);
  assert.equal(compiled.status, 0, `${id}: ${compiled.stdout}${compiled.stderr}`);
  return {id, instance, config, workspace: path.join(instance, 'agent', 'workspace'), judge: path.join(instance, 'judge')};
}
function probeSource(judge) {
  const source = fs.readFileSync(path.join(judge, 'judge.py'), 'utf8');
  const match = source.match(/PROBE_MODULE_TEMPLATE = '''([\s\S]*?)'''/);
  assert.ok(match, 'hidden probe module missing');
  return match[1];
}
function variantDirectory(instance, variant) {
  const target = path.join(output, `${instance.id}-${variant}`);
  fs.cpSync(instance.workspace, target, {recursive: true});
  return target;
}
function patchFile(filename, before, after) {
  const oldLines = before.replace(/\r\n/g, '\n').trimEnd().split('\n');
  const newLines = after.replace(/\r\n/g, '\n').trimEnd().split('\n');
  return `--- a/${filename}\n+++ b/${filename}\n@@ -1,${oldLines.length} +1,${newLines.length} @@\n`
    + oldLines.map(line => '-' + line).join('\n') + '\n'
    + newLines.map(line => '+' + line).join('\n') + '\n';
}

// The scored probes below come directly from each generated judge. The controls
// alter ordinary candidate files in separate directories, without patching a
// loaded module or making a trusted reference visible to the task agent.
for (const level of ['easy', 'medium', 'hard']) {
  const instance = generate('rope', 'envs/rope', level);
  const before = fs.readFileSync(path.join(instance.workspace, 'rope.py'), 'utf8');
  const reference = before
    .replace('torch.arange(seq_len, device=device)', 'torch.arange(offset, offset + seq_len, device=device)')
    .replace('/ (dim // 2)', '/ dim')
    .replace('return torch.cat((-x2, x1), dim=-1)', 'return torch.stack((-x[..., 1::2], x[..., 0::2]), dim=-1).flatten(-2)');
  const attention = fs.readFileSync(path.join(instance.workspace, 'attention.py'), 'utf8')
    .replace('offset = 0', 'offset = cache.position_offset()');
  const cache = fs.readFileSync(path.join(instance.workspace, 'cache.py'), 'utf8')
    .replace(/(def position_offset\([^\n]+\n)[\s\S]*?(?=    def append)/, '$1        return self.tokens_seen\n\n')
    .replace(/(def append\([^\n]+\n)[\s\S]*/, '$1        self.tokens_seen += int(chunk_len)\n');
  const wrongPairing = reference
    .replace('return torch.stack((-x[..., 1::2], x[..., 0::2]), dim=-1).flatten(-2)', 'return torch.cat((-x2, x1), dim=-1)')
    .replace('torch.repeat_interleave(angles.cos(), repeats=2, dim=-1)', 'torch.cat((angles.cos(), angles.cos()), dim=-1)')
    .replace('torch.repeat_interleave(angles.sin(), repeats=2, dim=-1)', 'torch.cat((angles.sin(), angles.sin()), dim=-1)');
  const variants = {
    baseline: {rope: before},
    reference: {rope: reference, all: true},
    wrong_frequency: {rope: reference.replace('return angles', 'return angles * 1.1').replace('return phase', 'return phase * 1.1'), all: true, reject: 'rope_pairing'},
    wrong_pairing: {rope: wrongPairing, all: true, reject: 'rope_pairing'},
    ignored_offset: {rope: reference.replace('torch.arange(offset, offset + seq_len, device=device)', 'torch.arange(seq_len, device=device)'), all: true, reject: 'rope_offset'},
    stalled_cache: {rope: reference, all: true, stalled: true, reject: 'cache_state'},
  };
  const hidden = instance.config.axes.find(axis => axis.id === 'hidden_context').levels[level];
  for (const [name, control] of Object.entries(variants)) {
    const id = `${instance.id}-${name}`;
    const cwd = variantDirectory(instance, name);
    fs.writeFileSync(path.join(cwd, 'rope.py'), control.rope);
    if (control.all) {
      fs.writeFileSync(path.join(cwd, 'attention.py'), attention);
      fs.writeFileSync(path.join(cwd, 'cache.py'), control.stalled ? cache.replace('self.tokens_seen += int(chunk_len)', 'self.tokens_seen += 0') : cache);
    }
    fs.writeFileSync(path.join(cwd, '_probe.py'), probeSource(instance.judge));
    checked(['_probe.py', cwd, '53', hidden['%%HIDDEN_LONG_SEQ%%'], hidden['%%HIDDEN_OFFSET%%']], cwd, id);
    const checks = JSON.parse(checked(['-c', 'import json, torch\nprint(json.dumps(torch.load("eval_outputs.pt", weights_only=1)["checks"]))'], cwd, id + '-checks'));
    if (name === 'reference') {
      assert.equal(Object.values(checks).filter(Boolean).length, 5, `${id}: reference rejected`);
      checked(['-m', 'pytest', '-q', 'visible_tests.py'], cwd, id + '-visible');
    } else {
      assert.ok(Object.values(checks).some(value => !value), `${id}: invalid control accepted`);
      if (control.reject) assert.equal(Boolean(checks[control.reject]), false, `${id}: wrong rejection target`);
    }
    record({id, checks, configuredOffset: Number(hidden['%%HIDDEN_OFFSET%%'])});
  }
}

for (const level of ['easy', 'hard']) {
  const instance = generate('moco', 'envs/moco', level);
  const naming = instance.config.axes.find(axis => axis.id === 'naming').levels[level];
  const k = instance.config.axes.find(axis => axis.id === 'queue_math').levels[level]['%%K%%'];
  const modelFile = naming['%%MODEL_FILE%%'];
  const modelModule = naming['%%MODEL_MODULE%%'];
  const modelClass = naming['%%MODEL_CLASS%%'];
  const q = naming['%%Q_VAR%%'];
  const key = naming['%%K_VAR%%'];
  const dequeue = naming['%%DEQUEUE_FN%%'];
  const before = fs.readFileSync(path.join(instance.workspace, modelFile), 'utf8');
  const queueBefore = fs.readFileSync(path.join(instance.workspace, 'queue_ops.py'), 'utf8');
  const reference = before.replace('logits = torch.cat([l_pos, l_neg], dim=1)', 'logits = torch.cat((l_pos, l_neg), dim=1) / self.tau');
  const queueReference = queueBefore.replace('queue[:, start:start + n] = keys.T', 'queue[:, (torch.arange(n) + start) % k] = keys.T');
  const variants = {
    baseline: {source: before, queue: queueBefore, logits: false, wrap: false},
    reference: {source: reference, queue: queueReference, logits: true, wrap: true},
    inverse_square: {source: reference.replace('dim=1) / self.tau', 'dim=1) / (self.tau ** 2)'), queue: queueReference, logits: false, wrap: true},
    both_embeddings_scaled: {source: before.replace('        l_pos =', `        ${q} = ${q} / self.tau\n        ${key} = ${key} / self.tau\n        l_pos =`), queue: queueReference, logits: false, wrap: true},
    unnormalized_queue: {source: reference.replace(`self.${dequeue}(${key})`, `self.${dequeue}(${key} * 2)`), queue: queueReference, logits: false, wrap: true},
    no_wraparound: {source: reference, queue: queueBefore, logits: true, wrap: false},
  };
  for (const [name, control] of Object.entries(variants)) {
    const id = `${instance.id}-${name}`;
    const cwd = variantDirectory(instance, name);
    fs.writeFileSync(path.join(cwd, modelFile), control.source);
    fs.writeFileSync(path.join(cwd, 'queue_ops.py'), control.queue);
    fs.writeFileSync(path.join(cwd, '_setup.py'), `import torch\nfrom ${modelModule} import ${modelClass}\ntorch.manual_seed(71)\nmodel = ${modelClass}(dim=16, K=${k})\ntorch.save(model.state_dict(), "ckpt.pt")\ntorch.save(torch.randn(8, 1, 16, 16), "eval_train_inputs.pt")\ntorch.save(torch.randn(5, 1, 16, 16), "eval_test_inputs.pt")\n`);
    fs.writeFileSync(path.join(cwd, '_probe.py'), probeSource(instance.judge));
    checked(['_setup.py'], cwd, id + '-setup');
    checked(['_probe.py', cwd, modelModule, modelClass, k], cwd, id);
    const values = JSON.parse(checked(['-c', 'import json, torch\noutputs = torch.load("eval_outputs.pt", weights_only=1)\nprint(json.dumps((outputs["tau_ok"], outputs["queue_wrap_ok"])))'], cwd, id + '-checks'));
    assert.deepEqual(values, [control.logits, control.wrap], `${id}: wrong control outcome`);
    record({id, checks: {normalized_contrastive_logits: values[0], queue_wraparound: values[1]}});
  }
}

for (const level of ['easy', 'medium', 'hard']) {
  const instance = generate('rd_adaptive_halting', 'envs/recurrent_depth/adaptive_halting', level);
  const before = fs.readFileSync(path.join(instance.workspace, 'halting.py'), 'utf8');
  // Reuse the existing public forward entry point, computing only active rows.
  // Recursive calls avoid imposing the judge reference's full-batch strategy.
  const activeBody = String.raw`        counts = torch.as_tensor(halt_after, device=x.device, dtype=torch.long)
        if max_steps is not None:
            counts = counts.clamp(max=int(max_steps))
        if counts.numel() == 0:
            return x
        if counts.max().item() <= 0:
            return x
        active = counts > 0
        state = x.clone()
        state[active] = self.transition(x[active])
        return self.forward(state, (counts - 1).clamp(min=0))
`;
  const reference = before.replace(/(    def forward\([^\n]+\n)[\s\S]*/, '$1' + activeBody);
  for (const [name, source] of Object.entries({baseline: before + '\n# Baseline control.\n', active_rows: reference})) {
    const id = `${instance.id}-${name}`;
    const patch = path.join(output, id + '.patch');
    fs.writeFileSync(patch, patchFile('halting.py', before, source));
    const verdict = run(['judge.py'], instance.judge, {JUDGE_PATCH_PATH: patch, JUDGE_ORIGINALS_DIR: instance.workspace});
    fs.writeFileSync(path.join(output, id + '.stdout'), verdict.stdout);
    fs.writeFileSync(path.join(output, id + '.stderr'), verdict.stderr);
    const result = JSON.parse(verdict.stdout);
    assert.equal(result.checks.sources_valid, true, `${id}: invalid candidate source`);
    assert.equal(result.verdict, name === 'active_rows' ? 'PASS' : 'FAIL', `${id}: ${verdict.stdout}${verdict.stderr}`);
    if (name === 'active_rows') assert.equal(result.score, 1);
    record({id, score: result.score, checks: result.checks});
  }
}

for (const name of ['batchnorm_ema', 'glyph', 'moco', 'rope']) {
  const judge = fs.readFileSync(`envs/${name}/files/judge.py`, 'utf8');
  assert.doesNotMatch(judge, /require_changed_files\(/, `${name}: file-touch acceptance requirement remains`);
}
for (const filename of ['visible_tests.py', 'run_train.py', 'run_eval.py']) {
  assert.doesNotMatch(fs.readFileSync(`envs/rope/files/${filename}`, 'utf8'), /def reference_rope/);
}
const agentImage = fs.readFileSync('shared/Dockerfile.agent', 'utf8');
const judgeImage = fs.readFileSync('shared/Dockerfile.judge', 'utf8');
assert.equal(agentImage.match(/torch==\S+ torchvision==\S+/)?.[0], judgeImage.match(/torch==\S+ torchvision==\S+/)?.[0]);
assert.match(agentImage, /pip freeze > \/runtime-packages.txt/);
assert.match(judgeImage, /pip freeze > \/runtime-packages.txt/);
console.log(`Verified ${rows.length} ML/recurrent controls and source contracts.`);
