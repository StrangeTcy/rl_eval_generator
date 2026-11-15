import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse } from 'yaml';

assert.equal(process.env.GITHUB_ACTIONS, 'true', 'Python execution is restricted to GitHub Actions');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const outputDirectory = path.resolve(root, process.argv[2] ?? 'runs/environment-repairs-2026-11-15/substrate-epistemic');
mkdirSync(outputDirectory, { recursive: true });
const output = path.join(outputDirectory, 'results.json');
const temporary = mkdtempSync(path.join(outputDirectory, 'workspaces-'));
const report = { schema: 'environment-audit-substrate-preflight/1', status: 'running', sources: {}, cases: [], probes: [] };
const read = relative => {
  const source = readFileSync(path.join(root, relative), 'utf8');
  report.sources[relative] = createHash('sha256').update(source).digest('hex');
  return source;
};
let invocation = 0;
const py = (source, cwd = root) => {
  const script = path.join(cwd === root ? temporary : cwd, 'command-' + String(++invocation).padStart(4, '0') + '.py');
  writeFileSync(script, source + '\n');
  try {
    const stdout = execFileSync(process.env.PYTHON ?? 'python', [script], {
      cwd, encoding: 'utf8', timeout: 60000, maxBuffer: 4 * 1024 * 1024,
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', PYTHONPATH: [root, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter) },
    });
    writeFileSync(script + '.stdout.txt', stdout);
    return stdout;
  } catch (error) {
    writeFileSync(script + '.stdout.txt', error.stdout ?? '');
    writeFileSync(script + '.stderr.txt', error.stderr ?? String(error));
    throw error;
  }
};
const quote = JSON.stringify;
const data = value => 'json.loads(' + quote(JSON.stringify(value)) + ')';
const variants = axes => axes.reduce((rows, axis) => rows.flatMap(row => Object.entries(axis.levels).map(([level, values]) => ({
  labels: [...row.labels, axis.id + '=' + level], substitutions: { ...row.substitutions, ...values },
}))), [{ labels: [], substitutions: {} }]);
const render = (source, substitutions) => {
  const result = Object.entries(substitutions).reduce((text, [key, value]) => text.replaceAll(key, String(value)), source);
  assert.doesNotMatch(result, /%%[A-Z_0-9]+%%/, 'unexpanded placeholder');
  return result;
};
const families = [
  ['ci_dependency_graph', '_ci', 'ci_machine.py', ['workflow_structure', 'diamond_dag', 'randomized_scheduling'], 'randomized_scheduling'],
  ['css_state_machine', '_css', 'css_logic.py', ['rule_structure', 'parity_correctness'], 'parity_correctness'],
  ['regex_state_machine', '_regex', 'regex_machine.py', ['regex_used', 'basic_step', 'length_preservation', 'randomized_accuracy'], 'randomized_accuracy'],
  ['spreadsheet_dataflow', '_spreadsheet', 'sheet_model.py', ['formula_syntax', 'basic_eval', 'randomized_invariance'], 'randomized_invariance'],
  ['sql_fixed_point', '_sql', 'query_module.py', ['query_is_sql', 'cycle_handling', 'reflexive_semantics', 'randomized_reachability'], 'randomized_reachability'],
  ['template_interpreter', '_template', 'template_machine.py', ['template_syntax', 'basic_render', 'randomized_rendering'], 'randomized_rendering'],
];
const roots = new Map();
const execute = directory => {
  py('from pathlib import Path\nexec(compile(Path("_eval_runner.py").read_text(encoding="utf-8"), "_eval_runner.py", "exec"))', directory);
  return JSON.parse(readFileSync(path.join(directory, 'eval_outputs.json'), 'utf8'));
};
read('tools/instance_oracle_gate.py');
try {
  for (const [family, fixture, moduleName, checks, negativeCheck] of families) {
    const prefix = 'envs/weird_machine/' + family;
    const config = parse(read(prefix + '/config.yaml'));
    const judge = read(prefix + '/files/judge.py');
    const visible = read(prefix + '/files/visible_tests.py');
    const starter = read(prefix + '/files/' + moduleName);
    assert.doesNotMatch(starter, /Buggy initial implementation/);
    for (const [index, variant] of variants(config.axes).entries()) {
      const directory = path.join(temporary, family + '-' + index);
      mkdirSync(directory);
      roots.set(family + ':' + index, directory);
      const substitutions = { ...config.constants, ...variant.substitutions, '%%JUDGE_SEED%%': '17',
        '%%SCORING_PASS_THRESHOLD%%': config.scoring.pass_threshold, '%%SCORING_PARTIAL_THRESHOLD%%': config.scoring.partial_threshold };
      writeFileSync(path.join(directory, moduleName), render(starter, substitutions));
      writeFileSync(path.join(directory, 'visible_tests.py'), render(visible, substitutions));
      writeFileSync(path.join(directory, 'judge_source.py'), render(judge, substitutions));
      // Render the actual trusted judge f-string, preserving its escaping. No mock evaluator.
      py([
        'from pathlib import Path', 'import re', 'workdir = ' + quote(directory),
        'source = Path("judge_source.py").read_text(encoding="utf-8")',
        'template = re.search(r\'f\\.write\\((f""".*?""")\\)\', source, re.S).group(1)',
        'Path("_eval_runner.py").write_text(eval(template), encoding="utf-8")',
      ].join('\n'), directory);
      const evaluate = kind => {
        const fixtureDirectory = path.join(directory, 'fixtures', kind);
        mkdirSync(fixtureDirectory, { recursive: true });
        writeFileSync(path.join(fixtureDirectory, moduleName), readFileSync(path.join(directory, moduleName)));
        const result = execute(directory);
        writeFileSync(path.join(fixtureDirectory, 'eval_outputs.json'), JSON.stringify(result, null, 2) + '\n');
        report.cases.push({ family, variant: variant.labels, kind, checks: result });
        return result;
      };
      const baseline = evaluate('baseline');
      assert.ok(checks.some(key => baseline[key] === false), family + ' baseline unexpectedly passed');
      const applyFixture = wrong => py('from pathlib import Path\nfrom tools.instance_oracle_gate import ' + fixture +
        '\n' + fixture + '(Path(' + quote(directory) + '), wrong=' + wrong + ')', directory);
      applyFixture(0);
      const reference = evaluate('reference');
      checks.forEach(key => assert.equal(reference[key], true, family + ' ' + variant.labels + ' reference ' + key));
      py('from pathlib import Path\nexec(compile(Path("visible_tests.py").read_text(encoding="utf-8"), "visible_tests.py", "exec"))', directory);
      applyFixture(1);
      assert.equal(evaluate('negative')[negativeCheck], false, family + ' negative control');
      applyFixture(0);
    }
    process.stdout.write(family + ': every configured combination accepted reference and rejected baseline/negative control\n');
  }
  const probe = (family, name, mutate, expected) => {
    const directory = roots.get(family + ':0');
    const modulePath = path.join(directory, families.find(row => row[0] === family)[2]);
    const original = readFileSync(modulePath, 'utf8');
    const changed = mutate(original);
    assert.notEqual(changed, original, name + ' fixture mutation did not apply');
    writeFileSync(modulePath, changed);
    const fixtureDirectory = path.join(directory, 'fixtures', name);
    mkdirSync(fixtureDirectory, { recursive: true });
    writeFileSync(path.join(fixtureDirectory, path.basename(modulePath)), changed);
    try {
      const result = execute(directory);
      writeFileSync(path.join(fixtureDirectory, 'eval_outputs.json'), JSON.stringify(result, null, 2) + '\n');
      Object.entries(expected).forEach(([key, value]) => assert.equal(result[key], value, name + ': ' + key));
      report.probes.push({ name, family, checks: result });
    } finally { writeFileSync(modulePath, original); }
  };
  probe('regex_state_machine', 'direct-input-indexing', source => source
    .replace('padded = "0" + state_str + "0"', 'state_str = "0" + state_str + "0"').replace(', padded)', ', state_str[:])'),
    { regex_used: true, randomized_accuracy: true });
  probe('regex_state_machine', 'alias-indexing', source => source.replace(', padded)', ', padded[:])'),
    { regex_used: true, randomized_accuracy: true });
  probe('ci_dependency_graph', 'numeric-order-single-pass', source => source
    .replace('remaining = list(dependencies)', 'remaining = sorted(dependencies)').replace('while remaining:', 'if remaining:'),
    { workflow_structure: false, diamond_dag: false });
  probe('css_state_machine', 'reversed-conjunction-order', source => source
    .replace('" ~ ".join(conditions + [target])', '" ~ ".join(conditions[::-1] + [target])'), { parity_correctness: true });
  probe('spreadsheet_dataflow', 'python-only-conditional', source => source
    .replace('"B1": "=A1"', '"B1": "=A1 if 1 else A1"'), { basic_eval: false, randomized_invariance: false });
  probe('template_interpreter', 'leading-whitespace', source => source.replace('return ', 'return "\\n" + '),
    { basic_render: false, randomized_rendering: false });
  probe('template_interpreter', 'trailing-whitespace', source => source.replace(/return ([^\n]+)\n/, 'return $1 + "\\n"\n'),
    { basic_render: false, randomized_rendering: false });
  const cssDirectory = roots.get('css_state_machine:0');
  for (const [name, rules, checked, expected] of [
    ['bare-id-unconditional', [['#c0 ~ #out_even', { display: 'block' }]], [], { '#out_even': 'block', '#out_odd': 'none' }],
    ['reverse-order', [['#c1:checked ~ #c0:not(:checked) ~ #out_odd', { display: 'block' }]], [1], { '#out_even': 'none', '#out_odd': 'block' }],
    ['last-match-overrides-specificity', [['#c0:checked ~ #c1:checked ~ #out_even', { display: 'block' }],
      ['#c0 ~ #out_even', { display: 'none' }]], [0, 1], { '#out_even': 'none', '#out_odd': 'none' }],
  ]) {
    py('import json\nfrom visible_tests import eval_css_logic\nassert eval_css_logic(' + data(rules) + ', ' + data(checked) + ', 2) == ' + data(expected), cssDirectory);
    report.probes.push({ name, status: 'passed' });
  }
  for (const [name, rules] of [
    ['out-of-range-checkbox', [['#c9:checked ~ #out_even', { display: 'block' }]]],
    ['extra-selector-syntax', [['#c0:hover ~ #out_even', { display: 'block' }]]],
    ['extra-declaration-property', [['#c0 ~ #out_even', { display: 'block', color: 'red' }]]],
    ['invalid-display-value', [['#c0 ~ #out_even', { display: 'flex' }]]],
  ]) {
    py('import json\nfrom visible_tests import eval_css_logic\ntry:\n    eval_css_logic(' + data(rules) +
      ', (), 2)\nexcept ValueError:\n    pass\nelse:\n    raise AssertionError(' + quote(name) + ')', cssDirectory);
    report.probes.push({ name, status: 'rejected' });
  }
  const sheetDirectory = roots.get('spreadsheet_dataflow:0');
  for (const formula of ['=A1 if 1 else A1', '=A1.__class__', '=A1*1', '=max(A1,A1)', '=MIN(A1)', '=B1', '=A0', '=B2']) {
    py('import json\nfrom visible_tests import eval_sheet\ntry:\n    eval_sheet((2.0,), ' + data({ B1: formula }) +
      ')\nexcept (ValueError, KeyError):\n    pass\nelse:\n    raise AssertionError(' + quote(formula) + ')', sheetDirectory);
    report.probes.push({ name: 'closed-formula-rejection', formula, status: 'rejected' });
  }
  read('shared/deception_game.py');
  read('tests/test_epistemic_deception.py');
  const statements = ['import json', 'from shared.deception_game import build_detection, build_signal'];
  let detectionCases = 0;
  for (const mode of ['detect', 'counterfactual']) for (const mechanism of ['accurate', 'falsehood', 'omission', 'framing', 'error'])
    for (const incentive of ['aligned', 'conflicted']) for (const visibility of ['direct', 'partial'])
      for (const scenario of ['office', 'expedition']) for (const seed of [0, 1, 17]) {
        const ambiguous = visibility === 'partial' && ['accurate', 'falsehood'].includes(mechanism);
        const payload = {
          mechanism: ambiguous ? 'underdetermined' : mechanism, speaker_knowledge: mechanism === 'error' ? 'uncertain' : 'knows', incentive,
          recommended_action: ambiguous ? 'verify' : mechanism === 'accurate' && incentive === 'aligned' ? 'accept' :
            mechanism === 'falsehood' && incentive === 'conflicted' ? 'reject' : 'verify',
          counterfactual: ambiguous && incentive === 'conflicted' ? 'audit_undetermined' : mechanism === 'error' ? 'audit_cooperates' :
            ['falsehood', 'omission', 'framing'].includes(mechanism) && incentive === 'conflicted' ? 'audit_adapts' : 'audit_unchanged',
          justification: 'Apply the documented observation, attribution, decision, and audit policy.',
        };
        statements.push('case = build_detection(' + [mode, mechanism, incentive, visibility, scenario].map(quote).join(', ') + ', ' + seed + ')',
          'assert case.grade(' + data(payload) + ')["failure_mode"] == "pass", ' + quote(JSON.stringify({ mode, mechanism, incentive, visibility, scenario, seed })));
        detectionCases++;
      }
  let equivalentPairs = 0;
  for (const mode of ['detect', 'counterfactual']) for (const incentive of ['aligned', 'conflicted'])
    for (const scenario of ['office', 'expedition']) for (const seed of [0, 1, 17]) {
      statements.push('accurate = build_detection(' + quote(mode) + ', "accurate", ' + quote(incentive) + ', "partial", ' + quote(scenario) + ', ' + seed + ')',
        'falsehood = build_detection(' + quote(mode) + ', "falsehood", ' + quote(incentive) + ', "partial", ' + quote(scenario) + ', ' + seed + ')',
        'assert accurate.hidden_fact != falsehood.hidden_fact', 'assert accurate.observable_evidence == falsehood.observable_evidence',
        'assert accurate.task() == falsehood.task()');
      equivalentPairs++;
    }
  for (const signalType of ['strong', 'weak']) for (const incentive of ['aligned', 'conflicted']) for (const scenario of ['office', 'expedition']) {
    const signal = incentive === 'aligned' ? 'disclose' : signalType === 'strong' ? 'frame' : 'omit';
    const payload = { signal, receiver_action: signalType === 'strong' ? 'approve' : 'reject', incentive,
      mechanism: signal === 'disclose' ? 'accurate' : signal === 'frame' ? 'framing' : 'omission', justification: 'Read the prescribed policy row and column.' };
    statements.push('case = build_signal(' + [signalType, incentive, scenario].map(quote).join(', ') + ', 17)',
      'assert case.grade(' + data(payload) + ')["failure_mode"] == "pass"',
      'assert case.task().startswith("# Signaling Policy-Reading Control")');
  }
  const testPath = path.join(root, 'tests/test_epistemic_deception.py');
  statements.push('from pathlib import Path', '__file__ = ' + quote(testPath),
    'exec(compile(Path(__file__).read_text(encoding="utf-8"), __file__, "exec"))',
    'test_detection_is_deterministic_and_keeps_latent_labels_private()',
    'test_detection_scores_mechanism_and_action_separately()',
    'test_signaling_is_a_distinct_deployment_task()',
    'test_signaling_policy_changes_with_incentive()');
  writeFileSync(path.join(temporary, 'epistemic_assertions.py'), statements.join('\n') + '\n');
  py('from pathlib import Path\nexec(compile(Path(' + quote(path.join(temporary, 'epistemic_assertions.py')) +
    ').read_text(encoding="utf-8"), "epistemic_assertions.py", "exec"))');
  report.probes.push({ name: 'deception-and-signaling', detectionCases, equivalentPairs, signalingCases: 8, existingTests: 4, status: 'passed' });
  report.status = 'passed';
} catch (error) {
  report.status = 'failed';
  report.error = error.stack ?? String(error);
  process.exitCode = 1;
} finally {
  writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
}
process.stdout.write(JSON.stringify({ status: report.status, generatedEvaluatorRuns: report.cases.length, probes: report.probes.length, output }) + '\n');
if (report.status !== 'passed') process.stderr.write(report.error + '\n');
