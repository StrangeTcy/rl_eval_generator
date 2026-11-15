import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import YAML from 'yaml';

const root = process.cwd();
const output = path.resolve(process.argv[2] ?? 'runs/environment-audit/generation');
const python = process.env.PYTHON ?? 'python';
fs.mkdirSync(output, {recursive: true});
const environment = {...process.env, PYTHONDONTWRITEBYTECODE: '1', PYTHONPYCACHEPREFIX: path.join(output, 'cache')};
const registry = YAML.parse(fs.readFileSync('envs/registry.yaml', 'utf8')).environments;
const omitted = new Set(['epistemic_games', 'epistemic_announcements', 'epistemic_silence', 'epistemic_type_games']);
const rows = [];
const sources = {};
function run(args, cwd = root) {
  const result = spawnSync(python, args, {cwd, env: environment, encoding: 'utf8', timeout: 120000});
  if (result.error) throw result.error;
  return result;
}
function files(directory) {
  return fs.readdirSync(directory, {withFileTypes: true}).flatMap(entry => {
    const target = path.join(directory, entry.name);
    return entry.isDirectory() ? files(target) : [target];
  });
}
for (const [name, configPath] of Object.entries(registry)) {
  if (name.startsWith('recursive_') || omitted.has(name)) continue;
  const config = YAML.parse(fs.readFileSync(configPath, 'utf8'));
  sources[configPath] = createHash('sha256').update(fs.readFileSync(configPath)).digest('hex');
  for (const file of files(path.join(path.dirname(configPath), 'files'))) {
    sources[path.relative(root, file).replaceAll('\\', '/')] = createHash('sha256').update(fs.readFileSync(file)).digest('hex');
  }
  const levels = config.axes.map(axis => Object.keys(axis.levels));
  const first = levels.map(axis => axis[0]);
  const hard = levels.map(axis => axis.at(-1));
  const vectors = new Set([first.join(','), hard.join(',')]);
  for (const [index, choices] of levels.entries()) {
    for (const choice of choices) {
      const vector = [...first];
      vector[index] = choice;
      vectors.add(vector.join(','));
    }
  }
  let index = 0;
  for (const vector of vectors) {
    const id = `${name}-${index++}`;
    const instance = path.join(output, id);
    const generated = run(['generate_env.py', '--env', name, '--name', instance, '--difficulty', vector, '--seed', '41']);
    fs.writeFileSync(path.join(output, id + '.log'), generated.stdout + generated.stderr);
    assert.equal(generated.status, 0, `${id}/${vector}: ${generated.stdout}${generated.stderr}`);
    const publicRoot = path.join(instance, 'agent');
    const publicFiles = files(publicRoot).filter(file => /\.(py|md)$/.test(file));
    for (const file of publicFiles) {
      const source = fs.readFileSync(file, 'utf8');
      assert.doesNotMatch(source, /^\s*from\s+\w+\.py\s+import/m, `filename imported as a module: ${file}`);
      if (name === 'rope') assert.doesNotMatch(source, /^def reference_rope/m, `public complete RoPE oracle: ${file}`);
      if (vector === hard.join(',')) assert.doesNotMatch(source, /BUG:|THIS NEEDS FIXING!!!/, `uncued diagnosis: ${file}`);
    }
    if (configPath.includes('weird_machine/')) {
      const visibleImport = run(['-c', 'import visible_tests'], path.join(instance, 'agent', 'workspace'));
      assert.equal(visibleImport.status, 0, `${id}: visible test import: ${visibleImport.stderr}`);
    }
    rows.push({name, vector, instance: id, generated: true, publicFilesChecked: publicFiles.length});
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify({rows, sources}, null, 2) + '\n');
    console.log(`${id}: generated and public boundary checked (${vector})`);
  }
}
const compiled = run(['-m', 'compileall', '-q', output]);
fs.writeFileSync(path.join(output, 'compile.log'), compiled.stdout + compiled.stderr);
assert.equal(compiled.status, 0, compiled.stdout + compiled.stderr);
console.log(`Verified ${rows.length} generated cases across ${new Set(rows.map(row => row.name)).size} repaired environments.`);
