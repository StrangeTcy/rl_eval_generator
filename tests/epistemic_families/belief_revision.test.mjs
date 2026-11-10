import test from 'node:test';
import assert from 'node:assert/strict';
import { create, definition, posterior, reference, baselines } from '../../arena/epistemic_families/belief_revision.mjs';

const finish = game => { game.submit(reference(game.view())); return game.submit(reference(game.view())); };

test('hand-calculated entailment, refutation, uncertainty and independent support', () => {
  const view = { premises: ['a', 'b', 'c'].map(id => ({ id, priorProbability: 0.5 })),
    graph: [{ id: 'x', op: 'literal', premise: 'a', value: 1 }, { id: 'y', op: 'literal', premise: 'b', value: 1 }, { id: 'z', op: 'literal', premise: 'c', value: 1 },
      { id: 'supported', op: 'or', inputs: ['x', 'y'] }, { id: 'uncertain', op: 'and', inputs: ['y', 'z'] }],
    targets: ['x', 'supported', 'uncertain'], evidence: [{ premise: 'a', value: 0 }, { premise: 'b', value: 1 }] };
  const result = posterior(view);
  assert.deepEqual(result.map(row => [row.probability, row.status]), [[0, 'refuted'], [1, 'entailed'], [0.5, 'undetermined']]);
  assert.deepEqual(result[2].witnesses, ['011', '010']);
});

test('all five axes change generated graph, evidence or available uncertainty', () => {
  definition.axes.forEach(axis => Object.entries(axis.levels).forEach(([level, value]) => {
    const game = create({ seed: 44, axes: { [axis.id]: level } });
    const initial = game.view();
    assert.equal(initial.axes[axis.id], value);
    if (axis.id === 'premises') assert.equal(initial.premises.length, value);
    if (axis.id === 'depth') assert.equal(initial.graph.filter(node => node.op === 'and').length, value + 1);
    if (axis.id === 'supports') assert.equal(initial.graph.find(node => node.op === 'or').inputs.length, value);
    const observation = game.submit({ kind: 'receive_correction' });
    if (axis.id === 'corrections') assert.equal(observation.changes.filter(change => change.operation === 'replace').length, value);
    if (axis.id === 'uncertainty') assert.equal(observation.changes.filter(change => change.operation === 'withdraw').length, value);
  }));
});

test('corrected conclusion changes while independent support survives', () => {
  const game = create({ seed: 5, axes: { supports: 'hard', uncertainty: 'hard' } });
  assert.ok(posterior(game.view()).every(row => row.probability === 1));
  game.submit({ kind: 'receive_correction' });
  assert.deepEqual(posterior(game.view()).map(row => row.probability).sort((a, b) => a - b), [0, 0.25, 1]);
  const result = game.submit(reference(game.view()));
  assert.equal(result.metrics.forecastExcess, 0);
  assert.equal(result.metrics.statusAccuracy, 1);
  assert.equal(result.metrics.certificateValidity, 1);
  assert.equal(result.metrics.correctionPropagationAccuracy, 1);
  assert.equal(result.metrics.retainedSupportAccuracy, 1);
});

test('public state and correction packet are identical across private assignments', () => {
  const options = { seed: 89, axes: { uncertainty: 'hard', supports: 'hard' } };
  const games = [1, 2, 3, 4].map(privateSeed => create({ ...options, privateSeed }));
  const packets = games.map(game => JSON.stringify(game.view()));
  assert.ok(packets.every(packet => packet === packets[0]));
  const corrections = games.map(game => JSON.stringify(game.submit({ kind: 'receive_correction' })));
  assert.ok(corrections.every(packet => packet === corrections[0]));
  assert.ok(new Set(games.map(game => game.audit().hiddenAssignment)).size > 1);
  assert.equal(Object.hasOwn(games[0].view(), 'hiddenAssignment'), false);
});

test('malformed and premature actions are atomic', () => {
  const game = create(), initial = JSON.stringify(game.view());
  [{ kind: 'submit', predictions: [] }, { kind: 'receive_correction', extra: 1 }, { kind: 'unknown' }].forEach(action => {
    assert.throws(() => game.submit(action)); assert.equal(JSON.stringify(game.view()), initial);
  });
  game.submit({ kind: 'receive_correction' });
  const revised = JSON.stringify(game.view()), answer = reference(game.view());
  assert.throws(() => game.submit({ kind: 'receive_correction' }));
  [-0.1, 1.1, NaN, Infinity].forEach(probability => {
    const changed = structuredClone(answer); changed.predictions[0].probability = probability;
    assert.throws(() => game.submit(changed)); assert.equal(JSON.stringify(game.view()), revised);
  });
  const malformed = structuredClone(answer); malformed.predictions[0].witnesses = ['not-bits'];
  assert.throws(() => game.submit(malformed)); assert.equal(JSON.stringify(game.view()), revised);
  game.submit(answer); assert.throws(() => game.submit(answer), /closed/);
});

test('plausible but contradictory uncertainty witnesses fail semantic verification', () => {
  const game = create({ axes: { uncertainty: 'hard' } });
  game.submit({ kind: 'receive_correction' });
  const answer = reference(game.view()), row = answer.predictions.find(item => item.status === 'undetermined');
  row.witnesses = [row.witnesses[0], row.witnesses[0]];
  const result = game.submit(answer);
  assert.equal(result.metrics.forecastExcess, 0);
  assert.equal(result.metrics.statusAccuracy, 1);
  assert.ok(result.metrics.certificateValidity < 1);
});

test('stale evidence and blanket disbelief fail different requirements', () => {
  const options = { seed: 7, axes: { supports: 'hard', uncertainty: 'hard', corrections: 'medium' } };
  const stale = create(options); stale.submit(baselines.stale_evidence(stale.view()));
  const old = stale.submit(baselines.stale_evidence(stale.view()));
  assert.ok(old.metrics.forecastExcess > 0);
  assert.equal(old.metrics.correctionPropagationAccuracy, 0);
  assert.equal(old.metrics.retainedSupportAccuracy, 1);
  const distrust = create(options); distrust.submit(baselines.global_disbelief(distrust.view()));
  const rejected = distrust.submit(baselines.global_disbelief(distrust.view()));
  assert.equal(rejected.metrics.retainedSupportAccuracy, 0);
  assert.ok(rejected.metrics.forecastExcess > 0);
});

test('all-hard and mixed configurations retain independent supports and exact conclusions', () => {
  const selections = [Object.fromEntries(definition.axes.map(axis => [axis.id, 'hard'])),
    { premises: 'easy', depth: 'hard', corrections: 'hard', supports: 'hard', uncertainty: 'hard' },
    { premises: 'hard', depth: 'medium', corrections: 'easy', supports: 'medium', uncertainty: 'easy' }];
  selections.forEach(axes => [2, 37, 98].forEach(seed => {
    const game = create({ seed, privateSeed: 33, axes });
    const initial = game.view(), branch = initial.graph.find(node => node.op === 'or');
    assert.equal(new Set(branch.inputs).size, initial.axes.supports);
    const result = finish(game);
    assert.equal(result.metrics.forecastExcess, 0);
    assert.equal(result.metrics.certificateValidity, 1);
    assert.equal(result.metrics.replacements, initial.axes.corrections);
    assert.equal(result.metrics.withdrawals, initial.axes.uncertainty);
  }));
});

test('independent truth-table evaluation agrees on a generated corrected graph', () => {
  const game = create({ seed: 42, axes: { supports: 'hard', corrections: 'hard', uncertainty: 'hard', depth: 'hard' } });
  game.submit({ kind: 'receive_correction' }); const view = game.view();
  const sums = new Map(view.targets.map(id => [id, 0])); let count = 0;
  for (let bits = 0; bits < 2 ** view.premises.length; bits++) {
    const truth = Object.fromEntries(view.premises.map((premise, index) => [premise.id, (bits >> index) & 1]));
    if (!view.evidence.every(item => truth[item.premise] === item.value)) continue;
    const values = {};
    view.graph.forEach(node => {
      values[node.id] = node.op === 'literal' ? Number(truth[node.premise] === node.value)
        : node.op === 'and' ? node.inputs.reduce((value, id) => value * values[id], 1)
        : 1 - node.inputs.reduce((value, id) => value * (1 - values[id]), 1);
    });
    count++;
    view.targets.forEach(id => sums.set(id, sums.get(id) + values[id]));
  }
  posterior(view).forEach(row => assert.equal(row.probability, sums.get(row.nodeId) / count));
});
