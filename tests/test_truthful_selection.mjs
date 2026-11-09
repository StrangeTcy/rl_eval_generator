import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { SelectionTask, SelectionFamily, Ratio } from '../arena/inquiry/selection_laws.mjs';
import { SelectionStudy } from '../tools/truthful_selection_study.mjs';

// Independent reference: build a uniform finite sample space of concrete
// selection tickets, then retain tickets carrying the observed message.
// It imports no posterior method or engine rational arithmetic.
class TicketOracle {
  static divisor(a, b) { return b === 0 ? a : this.divisor(b, a % b); }
  static fraction(n, d) { const common = this.divisor(n, d); return d === common ? String(n / common) : `${n / common}/${d / common}`; }
  static posterior(spec) {
    const sizes = spec.weights.map(row => row.reduce((sum, weight) => sum + weight, 0));
    const commonSize = sizes.reduce((product, size) => product * size, 1);
    const tickets = spec.weights.flatMap((row, world) => Array.from({ length: spec.prior[world] * commonSize / sizes[world] }, () => row.flatMap((count, message) => Array.from({ length: count }, () => ({ world, message })))).flat());
    const observed = tickets.filter(ticket => ticket.message === spec.observed);
    return spec.prior.map((_, world) => this.fraction(observed.filter(ticket => ticket.world === world).length, observed.length));
  }
}

test('a literally identical message reverses the optimal decision under selection laws', () => {
  const first = new SelectionTask(SelectionFamily.create(9, 'favors-0'));
  const second = new SelectionTask(SelectionFamily.create(9, 'favors-1'));
  assert.deepEqual(first.posterior().map(String), ['9/10', '1/10']);
  assert.deepEqual(second.posterior().map(String), ['1/10', '9/10']);
  assert.equal(first.answer(), 'answer 0 9/10 1/10');
  assert.equal(second.answer(), 'answer 1 1/10 9/10');
  assert.equal(JSON.parse(first.view()).observedMessage, JSON.parse(second.view()).observedMessage);
  assert.deepEqual(JSON.parse(first.view()).truthMasks, JSON.parse(second.view()).truthMasks);
});

test('content-only inference has hand-derived excess and decision regret', () => {
  const task = new SelectionTask(SelectionFamily.create(9, 'favors-1'));
  const score = task.submit(task.answer('content'));
  assert.equal(score.expectedBrier, '1/2');
  assert.equal(score.bayesBrier, '9/50');
  assert.equal(score.forecastExcess, '8/25');
  assert.equal(score.decisionRegret, '4/5');
  assert.equal(score.expectedDecisionLoss, '9/10');
  assert.equal(score.literalFalsehoodProbability, '0');
});

test('selection rows are separately normalized even when their totals differ', () => {
  const spec = { prior: [2, 1], truthMasks: [3, 1, 2], weights: [[1, 9, 0], [1, 0, 1]], observed: 0 };
  assert.deepEqual(new SelectionTask(spec).posterior().map(String), ['2/7', '5/7']);
  assert.deepEqual(TicketOracle.posterior(spec), ['2/7', '5/7']);
});

test('distinct sincere priors preserve disagreement with identical public evidence', () => {
  const left = new SelectionTask(SelectionFamily.create(9, 'favors-0', 'observer-0'));
  const right = new SelectionTask(SelectionFamily.create(9, 'favors-0', 'observer-1'));
  assert.deepEqual(left.posterior().map(String), ['18/19', '1/19']);
  assert.deepEqual(right.posterior().map(String), ['9/11', '2/11']);
  const leftPublic = JSON.parse(left.view()), rightPublic = JSON.parse(right.view());
  assert.deepEqual(leftPublic.selectionWeights, rightPublic.selectionWeights);
  assert.deepEqual(leftPublic.truthMasks, rightPublic.truthMasks);
  assert.equal(leftPublic.observedMessage, rightPublic.observedMessage);
});

test('uninformative selection is a true null for every declared prior', () => {
  ['common', 'observer-0', 'observer-1'].map(prior => {
    const task = new SelectionTask(SelectionFamily.create(9, 'uninformative', prior));
    assert.equal(task.answer('content'), task.answer());
    assert.equal(task.submit(task.answer('content')).forecastExcess, '0');
  });
});

test('all 63 prospective cases agree with an independent concrete-ticket oracle', () => {
  const cases = SelectionStudy.execute(SelectionStudy.design());
  assert.equal(cases.length, 63);
  cases.map(item => {
    assert.deepEqual(item.policies.find(policy => policy.policy === 'selection').score.posterior, TicketOracle.posterior(item.spec));
    assert.equal(item.policies.find(policy => policy.policy === 'selection').score.forecastExcess, '0');
    assert.equal(item.policies.find(policy => policy.policy === 'selection').score.decisionRegret, '0');
  });
});

test('false messages, empty laws and impossible observations are rejected', () => {
  const spec = SelectionFamily.create(3);
  assert.throws(() => new SelectionTask({ ...spec, weights: [[3, 0, 1], [1, 0, 3]] }), /truthful/);
  assert.throws(() => new SelectionTask({ ...spec, weights: [[0, 0, 0], [1, 0, 3]] }), /truthful/);
  assert.throws(() => new SelectionTask({ ...spec, weights: [[0, 4, 0], [0, 0, 4]] }), /positive probability/);
  assert.throws(() => new SelectionTask({ ...spec, privateWorld: 0 }), /closed/);
});

test('malformed answers are atomic and tied decisions receive zero regret', () => {
  const task = new SelectionTask(SelectionFamily.create(3, 'uninformative'));
  const before = task.view();
  ['answer 0 1/2 1/3', 'answer 0 NaN 0', 'answer 0 1/0 0', 'answer 0 .5 .5', 'answer 0 2 -1', 'answer 2 1/2 1/2', 'answer 0 1/2 1/2\n', 'answer 0 1/2 1/2 extra'].map(action => assert.throws(() => task.submit(action)));
  assert.equal(task.view(), before);
  assert.equal(task.submit('answer 1 1/2 1/2').decisionRegret, '0');
  assert.throws(() => task.submit('answer 0 1/2 1/2'), /already scored/);
});

test('literal-only singleton evidence yields certainty and zero optimal risk', () => {
  const spec = SelectionFamily.create(4);
  const task = new SelectionTask({ ...spec, observed: 1 });
  assert.deepEqual(task.posterior().map(String), ['1', '0']);
  assert.equal(task.submit('answer 0 1 0').expectedBrier, '0');
});

test('three-world selection is supported with exact proper scoring', () => {
  const spec = { prior: [1, 1, 1], truthMasks: [7, 1, 2, 4], weights: [[1, 3, 0, 0], [2, 0, 2, 0], [3, 0, 0, 1]], observed: 0 };
  const task = new SelectionTask(spec);
  assert.deepEqual(task.posterior().map(String), ['1/6', '1/3', '1/2']);
  assert.deepEqual(TicketOracle.posterior(spec), ['1/6', '1/3', '1/2']);
  assert.equal(task.submit('answer 2 1/6 1/3 1/2').expectedBrier, '11/18');
});

test('task identity is stable across key order and input mutations', () => {
  const spec = SelectionFamily.create(4), task = new SelectionTask(spec);
  const reordered = { observed: spec.observed, weights: spec.weights, truthMasks: spec.truthMasks, prior: spec.prior };
  assert.equal(task.id, new SelectionTask(reordered).id);
  spec.weights[0][0] = 0;
  assert.deepEqual(task.posterior().map(String), ['4/5', '1/5']);
  const packet = JSON.parse(task.view());
  assert.equal(Object.hasOwn(packet, 'posterior'), false);
  assert.equal(Object.hasOwn(packet, 'score'), false);
});

test('unequal row totals can be answered exactly beyond six-digit denominators', () => {
  const task = new SelectionTask({
    prior: [1, 1, 1, 1], truthMasks: [15, 1, 2, 4, 8],
    weights: [[1, 96, 0, 0, 0], [1, 0, 88, 0, 0], [1, 0, 0, 82, 0], [1, 0, 0, 0, 78]], observed: 0,
  });
  const answer = task.answer();
  assert.match(answer, /\/[0-9]{7,}/);
  assert.equal(task.submit(answer).forecastExcess, '0');
});

test('study persists all cases, replays scores, rejects resealed semantic corruption', () => {
  const parent = mkdtempSync(join(tmpdir(), 'selection-regression-'));
  const directory = join(parent, 'evidence');
  const result = SelectionStudy.run(directory);
  assert.equal(result.scoredAnswers, 126);
  assert.deepEqual(result.replay, { status: 'passed', casesChecked: 63, answersChecked: 126 });
  assert.equal(result.selectionLawDecisionReversals, 20);
  assert.equal(result.priorDisagreementPairs, 21);
  const record = JSON.parse(readFileSync(join(directory, 'records.json'), 'utf8'));
  record.cases[0].policies[0].score.forecastExcess = '1';
  const modified = JSON.stringify(record, null, 2) + '\n';
  writeFileSync(join(directory, 'records.json'), modified);
  writeFileSync(join(directory, 'records.sha256'), SelectionStudy.hash(modified) + '\n');
  assert.throws(() => SelectionStudy.replay(directory), /divergence/);
  assert.throws(() => SelectionStudy.run(directory), /EEXIST/);
});

test('exact arithmetic keeps signed differences and rejects invalid fractions', () => {
  assert.equal(String(new Ratio(1, 3).minus(new Ratio(2, 3))), '-1/3');
  assert.equal(String(new Ratio(2, 3).times(new Ratio(3, 4))), '1/2');
  assert.throws(() => Ratio.parse('1.0'), /fraction/);
  assert.throws(() => Ratio.parse('1/0'), /fraction/);
  assert.throws(() => new Ratio(1).over(new Ratio(0)), /divisor/);
});
