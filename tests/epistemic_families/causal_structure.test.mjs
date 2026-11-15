import test from 'node:test';
import assert from 'node:assert/strict';
import { create, definition, reference, baselines } from '../../arena/epistemic_families/causal_structure.mjs';
import { CausalOracle } from '../../arena/epistemic_families/causal_structure_oracle.mjs';
import { CausalReference } from '../../arena/epistemic_families/causal_structure_reference.mjs';
import { AxisMatrix, Ratio } from '../../arena/epistemic_families/runtime.mjs';
import { Session } from '../../arena/epistemic_families/session.mjs';

const finish = game => {
  let result;
  for (let step = 0; !game.done && step < 7; step++) result = game.submit(reference(game.view()));
  assert.equal(game.done, true, 'bounded reference episode');
  return result;
};
const rows = (...assignments) => assignments.sort().map(assignment => ({ assignment, probability: assignments.length === 1 ? '1' : '1/2' }));
const model = (root, ...edges) => ({ root, edges: edges.map(([from, to, flip = 0]) => ({ from, to, flip })) });

test('independent Cayley counts and child bounds give 6/9, 24/60/64, and 120/540/625 rooted trees', () => {
  [[3, 1, 6], [3, 2, 9], [4, 1, 24], [4, 2, 60], [4, 4, 64], [5, 1, 120], [5, 2, 540], [5, 4, 625]].forEach(([n, bound, expected]) => {
    const nodes = Array.from({ length: n }, (_, i) => `v${i}`);
    const trees = CausalOracle.trees(nodes, bound);
    assert.equal(trees.length, expected);
    assert.equal(CausalOracle.count(nodes, bound), expected);
    const signatures = trees.map(tree => JSON.stringify({ root: tree.root, edges: tree.edges.map(edge => `${edge.from}>${edge.to}:${edge.flip}`).sort() }));
    assert.equal(new Set(signatures).size, expected, 'no prior double counting');
  });
});

test('hand-derived observational twins differ under interventions, including a downstream clamp', () => {
  const nodes = ['A', 'B', 'C'];
  const forward = model('A', ['A', 'B'], ['B', 'C']);
  const reverse = model('C', ['C', 'B'], ['B', 'A']);
  const fork = model('B', ['B', 'A'], ['B', 'C']);
  [CausalOracle, CausalReference].forEach(engine => {
    [forward, reverse, fork].forEach(graph => assert.deepEqual(engine.distribution(nodes, graph), rows('000', '111')));
    assert.deepEqual(engine.distribution(nodes, forward, [{ node: 'A', value: 0 }]), rows('000'));
    assert.deepEqual(engine.distribution(nodes, reverse, [{ node: 'A', value: 0 }]), rows('000', '011'));
    assert.deepEqual(engine.distribution(nodes, forward, [{ node: 'B', value: 0 }]), rows('000', '100'));
    assert.deepEqual(engine.distribution(nodes, forward, [{ node: 'A', value: 0 }, { node: 'C', value: 1 }]), rows('001'));
    assert.deepEqual(engine.distribution(nodes, reverse, [{ node: 'A', value: 0 }, { node: 'C', value: 1 }]), rows('011'));
    assert.deepEqual(engine.distribution(nodes, fork, [{ node: 'A', value: 0 }, { node: 'C', value: 1 }]), rows('001', '011'));
    const inverted = model('A', ['A', 'B', 1], ['B', 'C', 1]);
    assert.deepEqual(engine.distribution(nodes, inverted), rows('010', '101'));
    assert.deepEqual(engine.distribution(nodes, inverted, [{ node: 'B', value: 0 }]), rows('001', '101'));
  });
});

test('no-access three-node posterior has hand-derived half-half held-out forecasts and accepts ambiguity', () => {
  const game = create({ privateSeed: 0, axes: { max_children: 'hard', intervention_access: 'hard' } });
  const view = game.view(), action = reference(view);
  assert.deepEqual(view.passive, rows('000', '111'));
  assert.equal(CausalReference.models(view).length, 9);
  assert.equal(action.identification, 'ambiguous');
  action.predictions.forEach(prediction => {
    const target = view.targets.find(item => item.id === prediction.id);
    const compatible = Array.from({ length: 8 }, (_, i) => i.toString(2).padStart(3, '0')).filter(assignment => target.intervention.every(clamp => Number(assignment[view.nodes.indexOf(clamp.node)]) === clamp.value));
    assert.deepEqual(prediction.distribution, rows(...compatible));
  });
  const metrics = game.submit(action).metrics;
  assert.equal(metrics.compatibleModels, '9');
  assert.equal(metrics.modelFitErrors, '0');
  assert.equal(metrics.identificationError, '0');
  assert.equal(metrics.forecastExcess, '0');
  assert.equal(metrics.reportingScore, '1');
  assert.equal(metrics.finalPredictiveRisk, '1/2');
  assert.equal(metrics.intrinsicPredictiveRisk, '1/6');
  assert.equal(metrics.structuralPredictiveUncertainty, '1/3');
  assert.equal(metrics.expectedPredictiveBrier, '1/2');
  assert.equal(metrics.predictiveScore, '3/4');
  assert.equal(metrics.score, '3/4');
  assert.equal(Object.hasOwn(metrics, 'regret'), false);
});

test('hand-derived posteriors after a singleton clamp retain four or three graph alternatives', () => {
  [
    { observation: rows('000', '011'), count: 4, expected: [{ assignment: '010', probability: '1/4' }, { assignment: '011', probability: '3/4' }] },
    { observation: rows('000'), count: 3, expected: [{ assignment: '010', probability: '2/3' }, { assignment: '011', probability: '1/3' }] },
  ].forEach(fixture => {
    let matched = null;
    for (let privateSeed = 0; privateSeed < 36 && matched === null; privateSeed++) {
      const game = create({ privateSeed, axes: { max_children: 'hard' } });
      const view = game.view();
      if (JSON.stringify(view.passive) !== JSON.stringify(rows('000', '111'))) continue;
      const response = game.submit({ kind: 'experiment', node: view.nodes[0] });
      if (JSON.stringify(response.distribution) === JSON.stringify(fixture.observation)) matched = game;
    }
    assert.ok(matched, 'the finite generator must contain the hand fixture');
    const view = matched.view(), [a, b] = view.nodes, answer = CausalReference.answer(view);
    assert.equal(CausalOracle.compatible(view).length, fixture.count);
    assert.equal(CausalReference.models(view).length, fixture.count);
    assert.equal(answer.identification, 'ambiguous');
    const target = view.targets.find(item => item.intervention.some(clamp => clamp.node === a && clamp.value === 0) && item.intervention.some(clamp => clamp.node === b && clamp.value === 1));
    assert.deepEqual(answer.predictions.find(item => item.id === target.id).distribution, fixture.expected);
    assert.equal(matched.submit(answer).metrics.reportingScore, '1');
  });
});

test('a premature but calibrated answer and unsupported certainty receive separate penalties', () => {
  const early = create({ privateSeed: 0, axes: { max_children: 'hard' } });
  const earlyMetrics = early.submit(CausalReference.answer(early.view())).metrics;
  assert.equal(earlyMetrics.reportingScore, '1');
  assert.equal(earlyMetrics.unfinishedDiscovery, '1');
  assert.equal(earlyMetrics.score, '3/8');
  const certain = create({ privateSeed: 0, axes: { max_children: 'hard', intervention_access: 'hard' } });
  const view = certain.view(), action = CausalReference.answer(view);
  action.identification = 'identified';
  action.predictions = view.targets.map(target => ({ id: target.id, distribution: CausalReference.distribution(view.nodes, action.model, target.intervention) }));
  const metrics = certain.submit(action).metrics;
  assert.equal(metrics.modelFitErrors, '0', 'a compatible representative is permitted');
  assert.equal(metrics.identificationError, '1');
  assert.ok(Ratio.parse(metrics.forecastExcess).compare(new Ratio(0)) > 0);
  assert.ok(Ratio.parse(metrics.score).compare(new Ratio(3, 4)) < 0);
});

test('all pairwise difficulty settings execute calibrated public-only references and replay', async () => {
  const matrix = AxisMatrix.expand(definition, 'pairwise');
  assert.equal(AxisMatrix.coverage(definition, matrix).complete, true);
  for (const axes of matrix) {
    const record = await Session.run('causal_structure', { seed: 17, privateSeed: 73, axes });
    assert.equal(record.status, 'completed', `${JSON.stringify(axes)}: ${record.failure}`);
    assert.equal(record.terminal.metrics.reportingScore, '1');
    assert.equal(record.terminal.metrics.unfinishedDiscovery, '0');
    assert.equal(record.terminal.metrics.forecastExcess, '0');
    const n = record.events[0].view.nodes.length;
    assert.equal(record.terminal.metrics.intrinsicPredictiveRisk, String(new Ratio(n - 2, 2 * n)));
    assert.equal((await Session.replay(record)).status, 'passed');
  }
});

test('correlation-only propagation fails held-out interventions, while reordered equivalent outputs are accepted', () => {
  const options = { privateSeed: 0, axes: { max_children: 'hard', intervention_access: 'hard' } };
  const shortcut = create(options), metrics = shortcut.submit(baselines.correlation_only(shortcut.view())).metrics;
  assert.equal(metrics.modelFitErrors, '0');
  assert.equal(metrics.forecastExcess, '1/2');
  assert.equal(metrics.score, '1/2');
  const equivalent = create(options), action = reference(equivalent.view());
  action.model.edges.reverse();
  action.predictions.reverse().forEach(prediction => prediction.distribution.reverse());
  assert.equal(equivalent.submit(action).metrics.score, '3/4');
});

test('all three-node signed trees are identified with full access without leaking their identity initially', () => {
  const groups = new Map();
  // Nine rooted trees times four relative parity assignments.
  for (let privateSeed = 0; privateSeed < 36; privateSeed++) {
    const game = create({ seed: 5, privateSeed, axes: { max_children: 'hard' } });
    const view = game.view(), signature = JSON.stringify(view.passive), encoded = JSON.stringify(view);
    assert.equal(encoded.includes('privateSeed'), false);
    assert.equal(encoded.includes('hiddenModel'), false);
    assert.equal(Object.hasOwn(view, 'models'), false);
    assert.equal(Object.hasOwn(view, 'candidates'), false);
    if (groups.has(signature)) assert.equal(encoded, groups.get(signature).view);
    groups.set(signature, { view: encoded, count: (groups.get(signature)?.count ?? 0) + 1 });
    const metrics = finish(game).metrics;
    assert.equal(metrics.compatibleModels, '1');
    assert.equal(metrics.reportingScore, '1');
    // Root remains stochastic even after the graph is identified.
    assert.equal(metrics.forecastExcess, '0');
    assert.equal(metrics.intrinsicPredictiveRisk, '1/6');
    assert.equal(metrics.structuralPredictiveUncertainty, '0');
    assert.equal(metrics.score, '11/12');
  }
  assert.equal(groups.size, 4);
  assert.deepEqual([...groups.values()].map(group => group.count), [9, 9, 9, 9]);
});

test('malformed graphs, forecasts, and unavailable experiments preserve the complete episode', () => {
  const game = create({ privateSeed: 0, axes: { intervention_access: 'hard' } });
  const before = game.view(), audit = game.audit(), answer = reference(before), [a, b, c] = before.nodes;
  const badModels = [
    0,
    { ...answer.model, candidate: 0 },
    model(a, [a, a], [a, c]),
    model(a, [a, b], [a, b]),
    model(a, [b, c], [c, b]),
    model(a, [a, b], [a, c]),
    model(a, [a, b]),
    model(a, [a, b, 2], [b, c]),
    model(a, [a, b, true], [b, c]),
    model(a, [a, 'missing'], [b, c]),
    model('missing', [a, b], [b, c]),
  ];
  const forecast = structuredClone(answer.predictions);
  forecast[0].distribution[0].probability = '-1';
  const duplicateRows = structuredClone(answer.predictions);
  duplicateRows[0].distribution = [{ assignment: '000', probability: '1/2' }, { assignment: '000', probability: '1/2' }];
  const impossibleRows = structuredClone(answer.predictions);
  impossibleRows[0].distribution = [{ assignment: '00000', probability: '1' }];
  [
    ...badModels.map(candidate => ({ ...answer, model: candidate })),
    { ...answer, predictions: [] },
    { ...answer, predictions: forecast },
    { ...answer, predictions: duplicateRows },
    { ...answer, predictions: impossibleRows },
    { ...answer, predictions: answer.predictions.map(() => answer.predictions[0]) },
    { ...answer, identification: 'maybe' },
    { ...answer, extra: 1 },
    { kind: 'experiment', node: a },
    { kind: 'submit_model', candidate: 0 },
  ].forEach(action => {
    assert.throws(() => game.submit(action));
    assert.deepEqual(game.view(), before);
    assert.deepEqual(game.audit(), audit);
  });
});

test('duplicate experiments and post-terminal submissions cannot mutate accepted state', () => {
  const game = create({ privateSeed: 0 });
  const action = { kind: 'experiment', node: game.view().experimentDomain[0] };
  game.submit(action);
  const view = game.view(), audit = game.audit();
  assert.throws(() => game.submit(action));
  assert.deepEqual(game.view(), view);
  assert.deepEqual(game.audit(), audit);
  finish(game);
  const final = game.audit();
  assert.throws(() => game.submit(action));
  assert.deepEqual(game.audit(), final);
});
