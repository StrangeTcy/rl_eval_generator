import test from 'node:test';
import assert from 'node:assert/strict';
import { create, reference, definition, baselines } from '../../arena/epistemic_families/inquiry_control.mjs';

const finish = (game, policy = reference, steps = 0) => {
  assert.ok(steps < 12, 'finite episode');
  const result = game.submit(policy(game.view()));
  return game.done ? result : finish(game, policy, steps + 1);
};

test('reference achieves exact zero regret for every independent axis level', () => {
  definition.axes.forEach(axis => Object.keys(axis.levels).forEach(level => {
    const game = create({ seed: 7, privateSeed: 23, axes: { [axis.id]: level } });
    const result = finish(game);
    assert.equal(result.metrics.regret, '0', `${axis.id}:${level}`);
    assert.equal(result.metrics.forecastExcess, '0');
    assert.equal(result.metrics.score, '1');
  }));
  const hard = Object.fromEntries(definition.axes.map(axis => [axis.id, 'hard']));
  assert.equal(finish(create({ seed: 13, privateSeed: 6, axes: hard })).metrics.score, '1');
});

test('query choice responds to costs and presentation, not only the labels', () => {
  const easy = create({ seed: 1, privateSeed: 2 });
  const costly = create({ seed: 1, privateSeed: 2, axes: { cost_pressure: 'hard' } });
  const erased = create({ seed: 1, privateSeed: 2, axes: { presentation: 'hard' } });
  assert.equal(easy.view().queries[0].cost, 1);
  assert.equal(costly.view().queries[0].cost, 3);
  assert.notDeepEqual(easy.view().queries[0].signals, erased.view().queries[0].signals);
  const full = finish(easy), restricted = finish(erased);
  assert.equal(full.metrics.remainingSupport, '1');
  assert.ok(Number(restricted.metrics.queryCost) >= Number(full.metrics.queryCost));
});

test('hand-derived four-state control: identifying query costs one and immediate regret is 41/7', () => {
  const game = create({ seed: 3, privateSeed: 0 });
  game.submit(reference(game.view()));
  const view = game.view();
  assert.deepEqual(view.priorWeights, [1, 1, 2, 3]);
  const result = game.submit(baselines.stop(view));
  // Stop loses 12*(1-3/7)=48/7; one full query has value 1.
  assert.equal(result.metrics.regret, '41/7');
  assert.equal(result.metrics.expectedDecisionLoss, '48/7');
  assert.equal(result.metrics.forecastExcess, '0');
});

test('null family preserves uncertainty and null query pays exactly its cost in regret', () => {
  const optimal = create({ seed: 11, privateSeed: 4 });
  optimal.submit(reference(optimal.view()));
  const before = optimal.view();
  assert.equal(reference(before).kind, 'answer');
  const result = finish(optimal);
  assert.equal(result.metrics.remainingSupport, '4');
  assert.equal(result.metrics.score, '1');
  const wasteful = create({ seed: 11, privateSeed: 4 });
  wasteful.submit(reference(wasteful.view()));
  wasteful.submit({ kind: 'query', query: 'null' });
  const wasted = finish(wasteful);
  assert.equal(wasted.metrics.regret, '1');
  assert.deepEqual(wasteful.audit().targetPosterior, optimal.audit().targetPosterior);
});

test('reference identifies every prior ticket and experimental conditioning agrees with direct filtering', () => {
  const total = create({ seed: 2 }).view().priorWeights.reduce((sum, value) => sum + value, 0);
  Array.from({ length: total }, (_, privateSeed) => privateSeed).forEach(privateSeed => {
    const game = create({ seed: 2, privateSeed });
    const result = finish(game);
    assert.equal(result.metrics.expectedDecisionLoss, '0');
    const audit = game.audit(), index = Number(audit.hiddenWorld.slice(1));
    assert.equal(audit.targetPosterior[index], '1');
  });
});

test('invalid actions preserve both public state and private audit', () => {
  const game = create({ seed: 5, privateSeed: 8 });
  game.submit(reference(game.view()));
  const before = game.view(), audit = game.audit();
  [null, { kind: 'query', query: 'missing' }, { kind: 'query', query: 'q0', extra: 1 }, { kind: 'answer', decision: 'w0', forecast: ['1', '1', '0', '0'] }, { kind: 'answer', decision: 'w0', forecast: ['NaN', '0', '0', '0'] }].forEach(action => {
    assert.throws(() => game.submit(action));
    assert.deepEqual(game.view(), before);
    assert.deepEqual(game.audit(), audit);
  });
  game.submit({ kind: 'query', query: 'q0' });
  const after = game.view();
  assert.throws(() => game.submit({ kind: 'query', query: 'q0' }));
  assert.deepEqual(game.view(), after);
});

test('seed reproducibility, private-seed independence of initial presentation, and snapshot isolation', () => {
  const left = create({ seed: 10, privateSeed: 1 }), right = create({ seed: 10, privateSeed: 5 });
  assert.deepEqual(left.view(), right.view());
  assert.notEqual(left.audit().hiddenWorld, right.audit().hiddenWorld);
  const exposed = left.view(); exposed.queries[0].signals[0] = 'tampered'; exposed.axes.world_count.value = 99;
  assert.equal(left.view().worlds.length, 4);
  assert.notEqual(left.view().queries[0].signals[0], 'tampered');
  assert.doesNotMatch(JSON.stringify(left.view()), /privateSeed|hiddenWorld|targetPosterior|oracle/);
  assert.deepEqual(finish(left), finish(create({ seed: 10, privateSeed: 1 })));
  assert.throws(() => left.submit(reference(right.view())));
});

test('all 81 combinations preserve exact sequential query optimality', () => {
  const settings = definition.axes.reduce((prefixes, axis) => prefixes.flatMap(prefix => Object.keys(axis.levels).map(level => ({ ...prefix, [axis.id]: level }))), [{}]);
  assert.equal(settings.length, 81);
  settings.forEach(axes => assert.equal(finish(create({ seed: 4, privateSeed: 19, axes })).metrics.score, '1', JSON.stringify(axes)));
});

test('seed zero is informative while positive multiples of eleven retain the explicit null control', () => {
  const informative = create({ seed: 0, privateSeed: 0 });
  informative.submit(reference(informative.view()));
  assert.equal(reference(informative.view()).kind, 'query');
  assert.equal(finish(informative).metrics.remainingSupport, '1');
  const nullGame = create({ seed: 22, privateSeed: 0 });
  nullGame.submit(reference(nullGame.view()));
  assert.equal(reference(nullGame.view()).kind, 'answer');
});

test('presenter has one permutation-only turn and cannot change facts, costs, or resources', () => {
  const game = create({ seed: 0, privateSeed: 2 }), before = game.view(), audit = game.audit();
  assert.equal(before.phase, 'presentation');
  assert.equal(before.role, 'presenter');
  const order = before.queries.map(query => query.id);
  [
    { kind: 'query', query: 'q0' },
    { kind: 'present', queryOrder: order.slice(1) },
    { kind: 'present', queryOrder: order.map(() => 'q0') },
    { kind: 'present', queryOrder: order.concat(['unknown']) },
    { kind: 'present', queryOrder: order, queryCost: 0 },
  ].forEach(action => {
    assert.throws(() => game.submit(action));
    assert.deepEqual(game.view(), before);
    assert.deepEqual(game.audit(), audit);
  });
  const reversed = order.toReversed();
  assert.deepEqual(game.submit({ kind: 'present', queryOrder: reversed }), { kind: 'presentation', role: 'investigator', queryOrder: reversed });
  const after = game.view();
  assert.equal(after.role, 'investigator');
  assert.equal(after.phase, 'inquiry');
  assert.deepEqual(after.queries.map(query => query.id), reversed);
  assert.deepEqual(after.queries.toSorted((a, b) => a.id.localeCompare(b.id)), before.queries.toSorted((a, b) => a.id.localeCompare(b.id)));
  assert.deepEqual(after.priorWeights, before.priorWeights);
  assert.deepEqual(after.budget, before.budget);
  assert.deepEqual(after.history, before.history);
  assert.throws(() => game.submit({ kind: 'present', queryOrder: order }));
  assert.deepEqual(game.view(), after);
});

test('paired query permutations leave exact investigator actions and outcomes unchanged', () => {
  const options = { seed: 6, privateSeed: 14, axes: { world_count: 'hard', presentation: 'medium', query_topology: 'hard' } };
  const neutral = create(options), permuted = create(options);
  neutral.submit(reference(neutral.view()));
  permuted.submit(baselines.misleading_presenter(permuted.view()));
  assert.notDeepEqual(neutral.view().presentation.queryOrder, permuted.view().presentation.queryOrder);
  const advance = () => {
    const left = reference(neutral.view()), right = reference(permuted.view());
    assert.deepEqual(left, right);
    assert.deepEqual(neutral.submit(left), permuted.submit(right));
    if (!neutral.done) advance();
  };
  advance();
  assert.equal(neutral.audit().terminal.metrics.investigatorScore, '1');
  assert.deepEqual(neutral.audit().history, permuted.audit().history);
});

test('paired scripted presenter changes a first-row investigator while its realized objective is separate', () => {
  const neutral = create({ seed: 0, privateSeed: 0 }), misleading = create({ seed: 0, privateSeed: 0 });
  const control = finish(neutral, baselines.first_row);
  const treatment = finish(misleading, baselines.misleading_presenter);
  assert.equal(neutral.audit().hiddenWorld, misleading.audit().hiddenWorld);
  assert.equal(neutral.audit().queryOrder[0], 'q0');
  assert.equal(misleading.audit().queryOrder[0], 'null');
  assert.equal(control.metrics.presenterRealizedObjective, '1');
  assert.ok(Number(treatment.metrics.presenterRealizedObjective) > Number(control.metrics.presenterRealizedObjective));
  assert.equal(control.metrics.realizedDecisionLoss, '0');
  assert.equal(treatment.metrics.realizedDecisionLoss, '0');
  assert.equal(control.metrics.investigatorScore, '1');
  assert.notEqual(treatment.metrics.investigatorScore, '1');
  assert.equal(treatment.metrics.presenterRealizedObjective, treatment.metrics.queryCost);
});
