import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { parse } from 'yaml';

const root = fileURLToPath(new URL('../../', import.meta.url));
const read = name => readFileSync(path.join(root, name), 'utf8').replaceAll('\r\n', '\n');
const python = process.env.ENV_AUDIT_PYTHON;
const hosted = { skip: python ? false : 'Set ENV_AUDIT_PYTHON on the hosted runner with Jinja2.' };
const families = {
  ci_dependency_graph: 'ci_machine', css_state_machine: 'css_logic',
  regex_state_machine: 'regex_machine', spreadsheet_dataflow: 'sheet_model',
  sql_fixed_point: 'query_module', template_interpreter: 'template_machine',
};
const familyFile = (family, file) => read(`envs/weird_machine/${family}/${file}`);
const render = (source, values) => source.replace(/%%[A-Z_]+%%/g, token => {
  assert.ok(Object.hasOwn(values, token), `Unresolved fixture token ${token}`);
  return values[token];
});
const defaults = family => {
  const config = parse(familyFile(family, 'config.yaml'));
  return Object.assign({ '%%JUDGE_SEED%%': '731' }, config.constants,
    ...config.axes.map(axis => axis.levels.easy));
};

// Decode the actual embedded runner; regressions exercise its evaluator bodies.
const runner = family => {
  const match = familyFile(family, 'files/judge.py').match(/f\.write\(f"""([\s\S]*?)"""\)/);
  assert.ok(match, `Missing embedded runner in ${family}`);
  return match[1].replaceAll('{workdir!r}', JSON.stringify('.'))
    .replaceAll('{{', '{').replaceAll('}}', '}').replaceAll('\\\\', '\\');
};
const between = (source, first, last) => {
  const start = source.indexOf(first);
  const end = source.indexOf(last, start);
  assert.ok(start >= 0 && end > start, `Missing source boundaries: ${first}, ${last}`);
  return source.slice(start, end);
};

function runPython(source, fixture = null, files = {}, error = null) {
  const directory = mkdtempSync(path.join(tmpdir(), 'substrate-audit-'));
  try {
    for (const [name, content] of Object.entries(files)) writeFileSync(path.join(directory, name), content);
    const output = spawnSync(python, ['-c', source], {
      cwd: directory, encoding: 'utf8', timeout: 30_000,
      input: JSON.stringify(fixture), env: { ...process.env, PYTHONPATH: root },
    });
    assert.ifError(output.error);
    if (error) {
      assert.notEqual(output.status, 0);
      assert.match(output.stderr, error);
      return;
    }
    assert.equal(output.status, 0, `${output.stdout}\n${output.stderr}`);
    return output.stdout.trim() ? JSON.parse(output.stdout) : null;
  } finally {
    assert.ok(path.resolve(directory).startsWith(path.resolve(tmpdir()) + path.sep));
    rmSync(directory, { recursive: true, force: true });
  }
}

test('six substrate families generate valid module imports under every surface level', () => {
  for (const [family, module] of Object.entries(families)) {
    const config = parse(familyFile(family, 'config.yaml'));
    assert.equal(config.constants['%%MODEL_MODULE%%'], module);
    for (const level of Object.values(config.axes[0].levels)) {
      const values = { ...defaults(family), ...level };
      const visible = render(familyFile(family, 'files/visible_tests.py'), values);
      assert.match(visible, new RegExp(`from ${module} import ${values['%%MODEL_CLASS%%']}\\b`));
      assert.equal(values['%%MODEL_FILE%%'], `${module}.py`);
      assert.doesNotMatch(visible, /from \S+\.py import/);
    }
    assert.doesNotMatch(familyFile(family, `files/${module}.py`), /BUG:|Buggy/);
  }
});

for (const family of Object.keys(families)) {
  test(`${family} generated visible test module imports`, hosted, () => {
    const values = defaults(family);
    runPython('import visible_tests', null, {
      [`${families[family]}.py`]: render(familyFile(family, `files/${families[family]}.py`), values),
      'visible_tests.py': render(familyFile(family, 'files/visible_tests.py'), values),
    });
  });
}

const cssHidden = between(runner('css_state_machine'), 'def eval_css_logic(', '\nnum_bits =');
const cssVisible = between(familyFile('css_state_machine', 'files/visible_tests.py'), 'def eval_css_logic(', '\ndef test_visible');
const sheetHidden = between(runner('spreadsheet_dataflow'), 'def eval_sheet(', '\n\ndef reference_dp(');
const sheetVisible = between(familyFile('spreadsheet_dataflow', 'files/visible_tests.py'), 'def eval_sheet(', '\ndef test_visible');

test('visible and hidden CSS/spreadsheet evaluators have identical bodies', () => {
  assert.equal(cssHidden.slice(cssHidden.indexOf('\n')).trim(), cssVisible.slice(cssVisible.indexOf('\n')).trim());
  assert.equal(sheetHidden.slice(sheetHidden.indexOf('\n')).trim(), sheetVisible.slice(sheetVisible.indexOf('\n')).trim());
});

const cssFixtures = [
  ['reversed sibling chain', [['#c1:checked ~ #c0:checked ~ #out_odd', { display: 'block' }]], [0, 1], 2, { '#out_even': 'none', '#out_odd': 'none' }],
  ['bare checkbox selector', [['#c0 ~ #out_even', { display: 'block' }]], [], 1, { '#out_even': 'block', '#out_odd': 'none' }],
  ['earlier greater specificity', [['#c0:checked ~ #out_odd', { display: 'block' }], ['#c0 ~ #out_odd', { display: 'none' }]], [0], 1, { '#out_even': 'none', '#out_odd': 'block' }],
  ['later equal specificity', [['#c0:checked ~ #out_odd', { display: 'block' }], ['#c0:checked ~ #out_odd', { display: 'none' }]], [0], 1, { '#out_even': 'none', '#out_odd': 'none' }],
  ['absent DOM checkbox', [['#c3 ~ #out_even', { display: 'block' }]], [], 1, { '#out_even': 'none', '#out_odd': 'none' }],
];
for (const [name, rules, checked, count, expected] of cssFixtures) {
  test(`CSS evaluator: ${name}`, hosted, () => {
    const value = runPython(`import json, sys, re\n${cssHidden}\nfixture = json.load(sys.stdin)\nprint(json.dumps(eval_css_logic(*fixture)))`, [rules, checked, count]);
    assert.deepEqual(value, expected);
  });
}

test('CSS evaluator accepts exhaustive parity rules on every three-bit input', hosted, () => {
  const rules = Array.from({ length: 8 }, (_, mask) => {
    const bits = Array.from({ length: 3 }, (_, bit) => (mask >> bit) & 1);
    const selector = bits.map((on, bit) => `#c${bit}:${on ? 'checked' : 'not(:checked)'}`).join(' ~ ');
    return [`${selector} ~ #out_${bits.reduce((a, b) => a + b) % 2 ? 'odd' : 'even'}`, { display: 'block' }];
  });
  for (let mask = 0; mask < 8; mask++) {
    const checked = [0, 1, 2].filter(bit => mask & (1 << bit));
    const result = runPython(`import json, sys, re\n${cssHidden}\nfixture = json.load(sys.stdin)\nprint(json.dumps(eval_css_logic(*fixture)))`, [rules, checked, 3]);
    assert.equal(result['#out_odd'], checked.length % 2 ? 'block' : 'none');
    assert.equal(result['#out_even'], checked.length % 2 ? 'none' : 'block');
  }
});

const sheetProgram = `import json, sys, re\n${sheetHidden}\nfixture = json.load(sys.stdin)\nprint(json.dumps(eval_sheet(*fixture)))`;
test('spreadsheet recurrence evaluates signed inputs and case-insensitive references', hosted, () => {
  const result = runPython(sheetProgram, [[10, 5, -2, 8], { B1: '= a1 ', B2: '=a2 + b1', B3: '=A3 + min(B2, B1)', B4: '=A4+MIN(B3,B2)' }]);
  assert.deepEqual([result.B1, result.B2, result.B3, result.B4], [10, 15, 8, 16]);
});
for (const formula of ['=A1*1', '=max(A1,A1)', '=A1 if A1 else A1', '=1', '=A1.real', '=B1', '=A2']) {
  test(`spreadsheet rejects unsupported formula ${formula}`, hosted, () => {
    runPython(sheetProgram, [[10], { B1: formula }], {}, /ValueError/);
  });
}

test('regex policy treats direct and aliased scalar indexing equally', hosted, () => {
  const policy = between(runner('regex_state_machine'), '# 1. Syntactic check:', '# 2. Non-identity');
  const original = render(familyFile('regex_state_machine', 'files/regex_machine.py'), defaults('regex_state_machine'));
  for (const body of [
    'return re.sub(r"$", state_str[0], state_str)',
    'alias = state_str\n        return re.sub(r"$", alias[0], alias)',
  ]) {
    const result = runPython(`import os, ast, json\nchecks = json.loads("{}")\n${policy}\nprint(json.dumps(checks))`, null,
      { 'regex_machine.py': original.replace('return state_str', body) });
    assert.equal(result.regex_used, true);
  }
  assert.doesNotMatch(policy, /forbidden_slice|arg_name/);
});

const dagRunner = runner('ci_dependency_graph');
const dagVerifier = between(dagRunner, 'def verify_workflow(', '# 1. Basic structure');
for (const [name, start, end] of [
  ['basic', '# 1. Basic structure check\ntry:\n', '    wf = engine.generate_workflow(deps)'],
  ['diamond', '# 2. Diamond DAG check\ntry:\n', '    wf = engine.generate_workflow(deps)'],
]) {
  test(`CI ${name} fixture defeats numeric and insertion order shortcuts`, hosted, () => {
    const startIndex = dagRunner.indexOf(start) + start.length;
    const fixtureSource = dagRunner.slice(startIndex, dagRunner.indexOf(end, startIndex)).replace(/^    /gm, '');
    const deps = runPython(`import json\n${fixtureSource}\nprint(json.dumps(tuple(deps.items())))`);
    const dependencyMap = new Map(deps);
    const schedule = order => {
      const wf = {};
      for (const id of order) {
        const parents = dependencyMap.get(id);
        wf[`job_${id}`] = { needs: parents.map(parent => `job_${parent}`), env: {
          LAYER: parents.length ? 1 + Math.max(...parents.map(parent => wf[`job_${parent}`]?.env.LAYER ?? Number.NaN)) : 0,
        } };
      }
      return wf;
    };
    const resolved = new Set();
    const topological = [];
    const visit = id => {
      if (resolved.has(id)) return;
      dependencyMap.get(id).forEach(visit);
      resolved.add(id);
      topological.push(id);
    };
    dependencyMap.forEach((_, id) => visit(id));
    for (const [order, expected] of [[deps.map(([id]) => id), false], [[...dependencyMap.keys()].sort((a, b) => a - b), false], [topological, true]]) {
      const result = runPython(`import json, sys\n${fixtureSource}\n${dagVerifier}\nprint(json.dumps(verify_workflow(deps, json.load(sys.stdin))))`, schedule(order));
      assert.equal(result, expected);
    }
  });
}

test('Jinja hidden and visible checks reject extra surrounding whitespace', hosted, () => {
  const hidden = render(runner('template_interpreter'), defaults('template_interpreter'));
  const model = render(familyFile('template_interpreter', 'files/template_machine.py'), defaults('template_interpreter'));
  const compact = '{%- for op in operations -%}{%- if not op.skip -%}{{ op.symbol * op.repeat }}{%- endif -%}{%- endfor -%}';
  for (const [template, expected] of [[compact, true], ["{{ ' ' }}" + compact + "{{ ' ' }}", false]]) {
    const result = runPython(`${hidden}\nprint(json.dumps(checks))`, null, {
      'template_machine.py': model.replace('return "ABC"', `return ${JSON.stringify(template)}`),
    });
    assert.equal(result.template_syntax, true);
    assert.equal(result.basic_render, expected);
    assert.equal(result.randomized_rendering, expected);
  }
  assert.doesNotMatch(familyFile('template_interpreter', 'files/visible_tests.py'), /render\(operations=ops\)\.strip\(\)/);
});

test('legacy answer instructions describe their own knowledge semantics', () => {
  for (const family of ['epistemic_fragmented_observation', 'epistemic_nested_knowledge']) {
    assert.doesNotMatch(read(`envs/${family}/files/answer.py`), /Public Announcement|announcement policy/i);
  }
});

const detectionProgram = 'import json, sys\nfrom shared.deception_game import build_detection\nfixture = json.load(sys.stdin)\ncase = build_detection(*fixture["axes"])\nprint(json.dumps((case.to_spec(), case.task(), case.grade(fixture["answer"]))))';
const answerFor = (mechanism, incentive) => ({
  mechanism, incentive, speaker_knowledge: mechanism === 'error' ? 'uncertain' : 'knows',
  recommended_action: mechanism === 'accurate' && incentive === 'aligned' ? 'accept' : mechanism === 'falsehood' && incentive === 'conflicted' ? 'reject' : 'verify',
  counterfactual: mechanism === 'error' ? 'audit_cooperates' : incentive === 'conflicted' && ['falsehood', 'omission', 'framing'].includes(mechanism) ? 'audit_adapts' : 'audit_unchanged',
  justification: 'The record and declared policy support these answers.',
});

test('deception evidence identifies all mechanisms and the audit protocol supplies counterfactuals', hosted, () => {
  for (const scenario of ['office', 'expedition']) {
    for (const incentive of ['aligned', 'conflicted']) {
      for (const visibility of ['direct', 'partial']) {
        const cases = [];
        for (const mechanism of ['accurate', 'falsehood', 'omission', 'framing', 'error']) {
          const [spec, task, grade] = runPython(detectionProgram, { axes: ['counterfactual', mechanism, incentive, visibility, scenario, 7], answer: answerFor(mechanism, incentive) });
          cases.push(spec);
          assert.equal(grade.failure_mode, 'pass');
          assert.equal(grade.metrics.strict_correct, true);
          assert.match(task, /stipulated independent-audit protocol/);
          assert.match(task, /reasoning is not separately verified/);
          assert.match(spec.observable_evidence.join('\n'), mechanism === 'error' ? /did not have/ : /read and correctly acknowledged/);
          if (visibility === 'partial') assert.match(spec.observable_evidence.join('\n'), mechanism === 'accurate' ? /supports the favorable/ : /contradicts the favorable/);
        }
        // Slot order must not carry mechanism labels: the same public evidence
        // categories occupy the same slots for the same non-mechanism axes.
        const slots = spec => spec.observable_evidence.map(item => item.startsWith('The registered fact') ? 'alternatives' : item.startsWith('The preliminary check') ? 'preliminary' : item.startsWith('The independent') ? 'independent' : 'access');
        cases.slice(1).forEach(spec => assert.deepEqual(slots(spec), slots(cases[0])));
        assert.notEqual(cases[0].hidden_fact, cases[1].hidden_fact);
        assert.equal(cases[0].message, cases[1].message);
      }
    }
  }
});

test('deception grading requires the closed schema and nonempty bounded justification', hosted, () => {
  const correct = answerFor('falsehood', 'conflicted');
  const missing = { ...correct };
  delete missing.justification;
  for (const answer of [missing, { ...correct, extra: 'field' }, { ...correct, justification: '' },
    { ...correct, justification: '   ' }, { ...correct, justification: 'x'.repeat(601) }, { ...correct, justification: 3 }]) {
    const [, , grade] = runPython(detectionProgram, { axes: ['detect', 'falsehood', 'conflicted', 'direct', 'office', 3], answer });
    assert.equal(grade.failure_mode, 'answer_format_invalid');
    assert.equal(grade.metrics.score, 0);
    assert.equal(grade.metrics.strict_correct, false);
  }
  const [, , boundary] = runPython(detectionProgram, { axes: ['detect', 'falsehood', 'conflicted', 'direct', 'office', 3], answer: { ...correct, justification: 'x'.repeat(600) } });
  assert.equal(boundary.failure_mode, 'pass');
});

test('signaling is presented as the declared policy control it evaluates', () => {
  const source = read('shared/deception_game.py');
  const task = between(source, '    def _signal_task(', '    def grade(');
  assert.match(task, /Declared Signaling Policy Control/);
  assert.match(task, /policy-reading control/);
  assert.match(task, /disclose maps to accurate/);
  assert.doesNotMatch(task, /optimi[sz]e|payoff table/);
});
