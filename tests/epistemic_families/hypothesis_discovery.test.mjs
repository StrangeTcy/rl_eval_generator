import test from 'node:test';
import assert from 'node:assert/strict';
import { create, reference, definition, baselines } from '../../arena/epistemic_families/hypothesis_discovery.mjs';
import { Ratio } from '../../arena/inquiry/selection_laws.mjs';

const finish = (game, steps = 0) => {
  assert.ok(steps < 10, 'finite episode');
  const result = game.submit(reference(game.view()));
  return game.done ? result : finish(game, steps + 1);
};

test('constructed-program reference succeeds at all independent axis levels and combined hard setting', () => {
  definition.axes.forEach(axis => Object.keys(axis.levels).forEach(level => {
    const game = create({ seed: 2, privateSeed: 19, axes: { [axis.id]: level } });
    const result = finish(game);
    assert.equal(result.metrics.reportingScore, '1', `${axis.id}:${level}`);
    assert.equal(result.metrics.expectedPredictiveBrier, result.metrics.finalPredictiveRisk);
    assert.equal(result.metrics.score, String(new Ratio(1).minus(Ratio.parse(result.metrics.finalPredictiveRisk).over(new Ratio(2)))));
    assert.equal(result.metrics.observedErrors, '0');
    assert.equal(result.metrics.unobservedForecastExcess, '0');
  }));
  const hard = Object.fromEntries(definition.axes.map(axis => [axis.id, 'hard']));
  const result = finish(create({ seed: 7, privateSeed: 1320, axes: hard }));
  assert.equal(result.metrics.reportingScore, '1');
  assert.equal(result.metrics.compatibleModels, '343');
  assert.ok(Ratio.parse(result.metrics.finalPredictiveRisk).compare(new Ratio(0)) > 0);
  assert.equal(result.metrics.finalPredictiveRisk, result.metrics.domainIrreduciblePredictiveRisk);
});

test('all axes alter operational bounds or accessible experiments', () => {
  definition.axes.forEach(axis => {
    const signatures = Object.keys(axis.levels).map(level => {
      const view = create({ axes: { [axis.id]: level } }).view();
      return JSON.stringify({ grammar: view.grammar, domain: view.experimentDomain, budget: view.budget });
    });
    assert.equal(new Set(signatures).size, 3, axis.id);
  });
});

test('hand-derived ambiguous linear law requires three equally likely predictions away from zero', () => {
  const game = create({ privateSeed: 4, axes: { observable_domain: 'hard' } });
  assert.deepEqual(game.submit({ kind: 'experiment', x: 0 }), { kind: 'observation', x: 0, y: 0 });
  const action = reference(game.view());
  assert.equal(action.kind, 'submit_model');
  assert.equal(action.identification, 'ambiguous');
  assert.deepEqual(action.predictions.find(item => item.x === 2).distribution, [
    { value: -2, probability: '1/3' }, { value: 0, probability: '1/3' }, { value: 2, probability: '1/3' },
  ]);
  const result = game.submit(action);
  assert.equal(result.metrics.reportingScore, '1');
  assert.equal(result.metrics.score, '5/7');
  assert.equal(result.metrics.finalPredictiveRisk, '4/7');
  assert.equal(result.metrics.domainIrreduciblePredictiveRisk, '4/7');
  assert.equal(result.metrics.remainingReduciblePredictiveRisk, '0');
  assert.equal(Object.hasOwn(result.metrics, 'regret'), false);
  assert.equal(result.metrics.compatibleModels, '3');
  assert.notEqual(result.metrics.hiddenModelAgreement, '1');
});

test('algebraically equivalent submitted syntax is accepted and the zero law is a null control', () => {
  const game = create({ privateSeed: 4 });
  game.submit({ kind: 'experiment', x: 3 });
  const action = reference(game.view());
  action.model = { op: 'add', left: { op: 'x' }, right: { op: 'mul', left: { op: 'const', value: -1 }, right: { op: 'x' } } };
  assert.equal(game.submit(action).metrics.score, '1');
  assert.deepEqual(game.audit().hiddenCoefficients, [0, 0]);
});

test('an in-sample fit receives an unobserved prediction penalty if it reports certainty', () => {
  const game = create({ privateSeed: 4, axes: { observable_domain: 'hard' } });
  game.submit({ kind: 'experiment', x: 0 });
  const action = reference(game.view());
  action.model = { op: 'const', value: 0 };
  action.predictions = game.view().evaluationDomain.map(x => ({ x, distribution: [{ value: 0, probability: '1' }] }));
  const result = game.submit(action);
  assert.equal(result.metrics.observedErrors, '0');
  assert.equal(result.metrics.observedForecastExcess, '0');
  assert.equal(result.metrics.unobservedForecastExcess, '2/3');
  assert.equal(result.metrics.reportingScore, '3/5');
  assert.equal(result.metrics.score, '3/7');
  assert.equal(result.metrics.expectedPredictiveBrier, '8/7');
});

test('skipping informative experiments is scored separately from calibration', () => {
  const game = create({ privateSeed: 6 });
  const result = game.submit(baselines.premature(game.view()));
  assert.equal(result.metrics.unobservedForecastExcess, '0');
  assert.equal(result.metrics.unfinishedDiscovery, '1');
  assert.equal(result.metrics.reportingScore, '1');
  assert.equal(result.metrics.score, String(Ratio.parse(result.metrics.predictiveScore).over(new Ratio(2))));
  assert.ok(Ratio.parse(result.metrics.score).compare(new Ratio(1, 2)) < 0);
});

test('candidate indices, unsafe ASTs, duplicate experiments, and malformed forecasts preserve state', () => {
  const game = create({ privateSeed: 1 }), before = game.view(), audit = game.audit();
  const prototype = baselines.premature(before);
  [
    { kind: 'submit_model', candidate: 0 },
    { ...prototype, model: 0 },
    { ...prototype, model: { op: 'call', value: 'process.exit' } },
    { ...prototype, model: { op: 'const', value: 99 } },
    { ...prototype, predictions: [] },
    { kind: 'experiment', x: 99 },
  ].forEach(action => {
    assert.throws(() => game.submit(action));
    assert.deepEqual(game.view(), before);
    assert.deepEqual(game.audit(), audit);
  });
  game.submit({ kind: 'experiment', x: 0 });
  const after = game.view();
  assert.throws(() => game.submit({ kind: 'experiment', x: 0 }));
  assert.deepEqual(game.view(), after);
});

test('public view contains grammar rather than candidate laws and does not depend on private coefficients', () => {
  const left = create({ seed: 8, privateSeed: 0 }), right = create({ seed: 8, privateSeed: 8 });
  assert.deepEqual(left.view(), right.view());
  assert.notDeepEqual(left.audit().hiddenCoefficients, right.audit().hiddenCoefficients);
  assert.doesNotMatch(JSON.stringify(left.view()), /privateSeed|hiddenCoefficients|compatibleCoefficients|candidate|oracle/);
  const snapshot = left.view(); snapshot.grammar.maxDegree = 99; snapshot.experimentDomain.push(999);
  assert.equal(left.view().grammar.maxDegree, 1);
  assert.ok(!left.view().experimentDomain.includes(999));
  assert.deepEqual(finish(left), finish(create({ seed: 8, privateSeed: 0 })));
});

test('all 81 combinations support a valid constructed expression and exact held-out predictions', () => {
  const settings = definition.axes.reduce((prefixes, axis) => prefixes.flatMap(prefix => Object.keys(axis.levels).map(level => ({ ...prefix, [axis.id]: level }))), [{}]);
  assert.equal(settings.length, 81);
  settings.forEach(axes => {
    const metrics = finish(create({ seed: 3, privateSeed: 414, axes })).metrics;
    assert.equal(metrics.reportingScore, '1', JSON.stringify(axes));
    assert.equal(metrics.forecastExcess, '0');
    assert.equal(metrics.score, String(new Ratio(1).minus(Ratio.parse(metrics.finalPredictiveRisk).over(new Ratio(2)))));
    if (metrics.compatibleModels === '1') {
      assert.equal(metrics.score, '1');
      assert.equal(metrics.finalPredictiveRisk, '0');
    } else {
      assert.ok(Ratio.parse(metrics.score).compare(new Ratio(1)) < 0);
      assert.ok(Ratio.parse(metrics.finalPredictiveRisk).compare(new Ratio(0)) > 0);
    }
  });
});

test('proper predictive quality distinguishes 37 unresolved laws from identification with equally calibrated reports', () => {
  const options = { seed: 1, privateSeed: 1200, axes: { degree: 'hard', coefficient_range: 'hard', experiment_budget: 'hard' } };
  const local = create(options), separated = create(options);
  [0, 1].forEach(x => assert.equal(local.submit({ kind: 'experiment', x }).y, 0));
  [3, -3].forEach(x => assert.equal(separated.submit({ kind: 'experiment', x }).y, 0));
  const weak = local.submit(reference(local.view())).metrics;
  const strong = separated.submit(reference(separated.view())).metrics;
  assert.equal(weak.compatibleModels, '37');
  assert.equal(strong.compatibleModels, '1');
  assert.equal(weak.reportingScore, '1');
  assert.equal(strong.reportingScore, '1');
  assert.equal(weak.forecastExcess, '0');
  assert.equal(strong.forecastExcess, '0');
  assert.equal(weak.domainIrreduciblePredictiveRisk, '0');
  // f(0)=f(1)=0 implies c0=0 and c1=-c2-c3. Count this
  // two-coordinate lattice directly, independently of the family enumerator.
  const coefficients = [-3, -2, -1, 0, 1, 2, 3];
  const lattice = coefficients.flatMap(c2 => coefficients.filter(c3 => Math.abs(c2 + c3) <= 3).map(c3 => ({ c2, c3 })));
  assert.equal(lattice.length, 37);
  const risk = [-4, -2, -1, 0, 1, 2, 4].reduce((sum, x) => {
    const counts = new Map();
    lattice.forEach(({ c2, c3 }) => { const y = c2 * (x * x - x) + c3 * (x * x * x - x); counts.set(y, (counts.get(y) ?? 0) + 1); });
    return sum.plus(new Ratio(1369 - [...counts.values()].reduce((total, count) => total + count * count, 0), 1369));
  }, new Ratio(0)).over(new Ratio(7));
  assert.equal(String(risk), '6334/9583');
  assert.equal(weak.finalPredictiveRisk, String(risk));
  assert.equal(weak.score, '6416/9583');
  assert.equal(strong.finalPredictiveRisk, '0');
  assert.equal(strong.score, '1');
  assert.ok(Ratio.parse(weak.finalPredictiveRisk).compare(new Ratio(0)) > 0);
  assert.ok(Ratio.parse(weak.score).compare(Ratio.parse(strong.score)) < 0);
  assert.equal(weak.unfinishedDiscovery, '0');
  assert.equal(strong.unfinishedDiscovery, '0');
});

test('trailing-zero canonicalization uses semantic degree for zero products and cancellations', () => {
  [
    { op: 'mul', left: { op: 'mul', left: { op: 'const', value: 0 }, right: { op: 'x' } }, right: { op: 'x' } },
    { op: 'mul', left: { op: 'add', left: { op: 'x' }, right: { op: 'mul', left: { op: 'const', value: -1 }, right: { op: 'x' } } }, right: { op: 'x' } },
  ].forEach(model => {
    const game = create({ privateSeed: 4 });
    game.submit({ kind: 'experiment', x: 3 });
    const action = reference(game.view());
    action.model = model;
    const result = game.submit(action);
    assert.equal(result.metrics.observedErrors, '0');
    assert.equal(result.metrics.hiddenModelAgreement, '1');
    assert.equal(result.metrics.reportingScore, '1');
    assert.equal(result.metrics.score, '1');
  });
  const invalid = create({ privateSeed: 4 }), before = invalid.view();
  const action = baselines.premature(before);
  action.model = { op: 'mul', left: { op: 'x' }, right: { op: 'x' } };
  assert.throws(() => invalid.submit(action), /semantic polynomial degree/);
  assert.deepEqual(invalid.view(), before);
});
