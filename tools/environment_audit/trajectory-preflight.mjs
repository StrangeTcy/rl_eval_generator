import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

const root = process.cwd();
const output = path.resolve(process.argv[2] ?? 'runs/environment-audit/trajectory');
const python = process.env.PYTHON ?? 'python';
fs.mkdirSync(output, {recursive: true});
const rows = [];
const env = {...process.env, PYTHONDONTWRITEBYTECODE: '1', PYTHONPYCACHEPREFIX: path.join(output, 'cache')};
function run(args, cwd = root, extra = {}) {
  const result = spawnSync(python, args, {cwd, env: {...env, ...extra}, encoding: 'utf8', timeout: 120000});
  if (result.error) throw result.error;
  return result;
}
function patchFile(before, after) {
  const oldLines = before.replace(/\r\n/g, '\n').trimEnd().split('\n');
  const newLines = after.trimEnd().split('\n');
  return `--- a/solution.py\n+++ b/solution.py\n@@ -1,${oldLines.length} +1,${newLines.length} @@\n`
    + oldLines.map(line => '-' + line).join('\n') + '\n'
    + newLines.map(line => '+' + line).join('\n') + '\n';
}
// These are solver entry points, separate from all agent-readable templates.
const stepBody = String.raw`    pattern = r'(?:^-\s+' + re.escape(template) + r'\(payload\)\s*->\s*|template\s+' + re.escape(template) + r'\(payload\):\s*\n\s*emit_source\(")([^()\s]+)\((payload|flip\(payload\)|[^()\s]+)\)'
    target, expression = re.search(pattern, spec_text, re.M).groups()
    if expression == "flip(payload)":
        payload = 1 - payload
    elif expression != "payload":
        first, second = re.search(r'^payloads:\s*([^,]+),\s*(.+)$', spec_text, re.M).groups()
        if expression == first.strip():
            payload = 0
        elif expression == second.strip():
            payload = 1
        else:
            raise ValueError("undeclared payload")
`;
const references = {
  one_step: 'import re\n\ndef solve(spec_text, template, payload):\n' + stepBody + '    return target, payload\n',
  trajectory: 'import re\n\ndef solve(spec_text, template, payload, horizon):\n'
    + '    if horizon == 0:\n        return template, payload\n'
    + stepBody + '    return solve(spec_text, target, payload, horizon - 1)\n',
  parse_only: String.raw`import re

def solve(spec_text, query):
    pattern = r'(?:^-\s+[^()\s]+\(payload\)\s*->\s*|template\s+[^()\s]+\(payload\):\s*\n\s*emit_source\(")([^()\s]+)\((payload|flip\(payload\)|[^()\s]+)\)'
    matches = re.finditer(pattern, spec_text, re.M)
    next(matches)
    next(matches)
    expression = next(matches).group(2)
    if expression == "payload":
        return "same"
    return expression
`,
};
const formatFailure = 'def solve(spec_text, template, payload):\n    if spec_text.startswith("#"):\n        return "noisy_wrong", 0\n    return "clean_wrong", 0\n';

for (const track of Object.keys(references)) {
  for (const witness of ['valid', 'broken']) {
    for (const representation of ['flat', 'reflective']) {
      for (const seed of [3, 41]) {
        const id = `${track}-${witness}-${representation}-${seed}`;
        const instance = path.join(output, id);
        const generated = run(['generate_env.py', '--env', `ts_${track}`, '--name', instance,
          '--difficulty', `${witness},${representation}`, '--seed', String(seed)]);
        fs.writeFileSync(path.join(output, id + '.generation.log'), generated.stdout + generated.stderr);
        assert.equal(generated.status, 0, `generation failed: ${id}: ${generated.stderr}`);
        const workspace = path.join(instance, 'agent', 'workspace');
        const judge = path.join(instance, 'judge');
        const compile = run(['-m', 'compileall', '-q', instance]);
        assert.equal(compile.status, 0, `compile failed: ${id}: ${compile.stdout}${compile.stderr}`);
        const before = fs.readFileSync(path.join(workspace, 'solution.py'), 'utf8');
        const variants = {
          baseline: before.trimEnd() + '\n# Baseline behavior control.\n',
          reference: references[track],
          ...(track === 'one_step' ? {format_failure: formatFailure} : {}),
          ...(track === 'parse_only' ? {constant_same: 'def solve(spec_text, query):\n    return "same"\n'} : {}),
          ...(track === 'trajectory' ? {one_step_only: references.one_step.replace(
            'def solve(spec_text, template, payload):', 'def solve(spec_text, template, payload, horizon):')} : {}),
        };
        for (const [variant, source] of Object.entries(variants)) {
          const patch = path.join(output, `${id}-${variant}.patch`);
          fs.writeFileSync(patch, patchFile(before, source));
          const verdict = run(['judge.py'], judge, {JUDGE_PATCH_PATH: patch, JUDGE_ORIGINALS_DIR: workspace});
          fs.writeFileSync(path.join(output, `${id}-${variant}.stdout`), verdict.stdout);
          fs.writeFileSync(path.join(output, `${id}-${variant}.stderr`), verdict.stderr);
          const result = JSON.parse(verdict.stdout);
          assert.equal(result.checks.sources_valid, true, `${id}/${variant}: source validation failed`);
          assert.equal(result.failure_mode, variant === 'reference' ? 'pass' : 'underfit', `${id}/${variant}: ${JSON.stringify(result)}`);
          assert.equal(result.verdict, variant === 'reference' ? 'PASS' : 'FAIL', `${id}/${variant}`);
          if (variant === 'format_failure') assert.equal(result.checks.same_result_under_format_noise, false);
          if (variant === 'constant_same') {
            assert.equal(result.checks.heldout_flat_constant, false);
            assert.equal(result.checks.heldout_reflective_constant, false);
            assert.equal(result.checks.heldout_flip, false);
          }
          if (variant === 'reference') assert.equal(result.score, 1);
          rows.push({id, variant, verdict: result.verdict, score: result.score, checks: result.checks});
          fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify({rows}, null, 2) + '\n');
          console.log(`${id}/${variant}: ${result.verdict} (${result.passed_checks}/${result.total_checks})`);
        }
      }
    }
  }
}
console.log(`Verified ${rows.length} trajectory solver controls.`);
