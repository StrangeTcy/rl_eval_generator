import test from 'node:test';
import assert from 'node:assert/strict';
import { create, definition, execute, signal, reference, baselines } from '../../arena/epistemic_families/recursive_delegation.mjs';

const finish = game => {
  let result;
  for (let step = 0; step < 5 && !game.done; step++) result = game.submit(reference(JSON.parse(JSON.stringify(game.view()))));
  assert.equal(game.done, true);
  return result;
};

// Independent exhaustive implementation: no cache, no Ratio, and comparison of integer
// unnormalized expected losses. It separately realizes a chosen child in the actual state.
const independent = (view, nodeId, request, worldIndex) => {
  const node = view.participants.find(item => item.id === nodeId);
  const observed = index => view.axes.private_information.value === 'full' ? index : view.axes.private_information.value === 'erased' ? 'hidden' : Math.floor(((index + node.channelOffset) % 6) / 2);
  const possible = view.worlds.map((_, index) => index).filter(index => observed(index) === observed(worldIndex));
  let winner, least = Infinity;
  const choices = [0, 1, 2].map(output => ({ output, cost: node.localCosts[output] })).concat(node.children.flatMap(child => [0, 1, 2].map(command => ({ child, command, cost: 1 }))));
  choices.forEach(choice => {
    const total = possible.reduce((sum, index) => {
      const output = choice.child ? independent(view, choice.child, choice.command, index) : choice.output;
      const ideal = Math.max(0, Math.min(2, view.worlds[index].goal + node.bias));
      return sum + view.priorWeights[index] * (2 * (ideal - output) ** 2 + 3 * (request - output) ** 2 + choice.cost);
    }, 0);
    if (total < least) { least = total; winner = choice; }
  });
  return winner.child ? independent(view, winner.child, winner.command, worldIndex) : winner.output;
};

test('two-participant hand control preserves private goals and upstream/downstream roles', () => {
  const packet = {
    root: 'boss', axes: { private_information: { value: 'erased' } }, worlds: [{ goal: 0 }, { goal: 2 }], priorWeights: [1, 1],
    participants: [
      { id: 'boss', parent: 'principal', children: ['worker'], bias: 0, channelOffset: 0, localCosts: [9, 9, 9] },
      { id: 'worker', parent: 'boss', children: [], bias: 1, channelOffset: 0, localCosts: [0, 0, 0] },
    ], rules: { ownGoalWeight: 2, mandateWeight: 3, delegationCost: 1 },
  };
  // Worker receiving zero chooses one: expected losses 5,4,13. Boss
  // receiving zero delegates that command: loss 6 versus local minimum 13.
  const first = execute(packet, 0, 0);
  assert.equal(first.output, 1);
  assert.deepEqual(first.route, ['boss', 'worker']);
  assert.equal(first.decisions[0].expectedLocalLoss, '6');
  assert.equal(first.decisions[1].expectedLocalLoss, '4');
  assert.equal(first.decisions[0].downstream, 'worker');
  assert.equal(first.decisions[1].upstream, 'boss');
  // Receiving two makes the boss delegate command two; worker returns two.
  const second = execute(packet, 2, 1);
  assert.equal(second.output, 2);
  assert.equal(second.decisions[0].outgoingRequest, 2);
  assert.equal(second.decisions[0].expectedLocalLoss, '5');
  assert.equal(second.decisions[1].expectedLocalLoss, '1');
});

test('independent recursion agrees across information channels and conflicting objectives', () => {
  ['easy', 'medium', 'hard'].forEach(private_information => [1, 4, 8].forEach(seed => {
    const view = create({ seed, axes: { depth: 'medium', branching: 'medium', alignment: 'hard', private_information } }).view();
    [0, 1, 2].forEach(request => view.worlds.forEach((world, index) => {
      assert.equal(execute(view, request, index).output, independent(view, view.root, request, index), `${seed}/${private_information}/${request}/${index}`);
    }));
  }));
});

test('all axes change executable resources, objectives, channels, or tree structure', () => {
  definition.axes.forEach(axis => Object.entries(axis.levels).forEach(([level, value]) => {
    const view = create({ seed: 4, axes: { [axis.id]: level } }).view();
    assert.equal(view.axes[axis.id].value, value);
    if (axis.id === 'depth') assert.equal(Math.max(...view.participants.map(item => item.depth)), value);
    if (axis.id === 'branching') assert.equal(view.participants[0].children.length, value);
    if (axis.id === 'alignment') assert.equal(Math.max(...view.participants.map(item => Math.abs(item.bias))), value);
    if (axis.id === 'inspection_budget') assert.equal(view.budget.remaining, value);
    if (axis.id === 'private_information') assert.equal(new Set(view.worlds.map((_, index) => signal(view, view.root, index))).size, level === 'easy' ? 6 : level === 'medium' ? 3 : 1);
  }));
});

test('full three-edge hierarchy executes interior participants in both relational roles', () => {
  const view = create({ seed: 4, axes: { depth: 'hard', branching: 'hard', alignment: 'hard', private_information: 'medium' } }).view();
  assert.equal(view.participants.length, 40);
  const result = execute(view, 0, 0);
  assert.equal(result.route.length, 4);
  result.decisions.slice(1, -1).forEach((entry, offset) => {
    assert.equal(entry.upstream, result.route[offset]);
    assert.equal(entry.downstream, result.route[offset + 2]);
    assert.equal(entry.kind, 'delegate');
  });
  assert.ok(new Set(result.decisions.map(entry => entry.ownBias)).size > 1);
  assert.ok(new Set(result.decisions.map(entry => entry.privateSignal)).size > 1);
});

test('paid full inspection has hand-derived regret against immediate delegation', () => {
  const game = create({ seed: 1, privateSeed: 0 });
  const view = game.view();
  assert.deepEqual(view.priorWeights, [2, 3, 1, 2, 3, 1]);
  assert.deepEqual([0, 1, 2].map(request => view.worlds.map((_, index) => execute(view, request, index).output)), [
    [1, 1, 0, 1, 1, 0], [1, 1, 1, 1, 1, 1], [1, 2, 1, 1, 2, 1],
  ]);
  const immediate = game.submit(baselines.no_inspection(view));
  // Request two errs only in the two goal-zero states, each of weight one:
  // 12*(1+1)/12 = 2. A full inspection costs one and eliminates that loss.
  assert.equal(immediate.metrics.expectedPrincipalLoss, '2');
  assert.equal(immediate.metrics.regret, '1');
  const optimal = create({ seed: 1, privateSeed: 0 });
  assert.deepEqual(reference(optimal.view()), { kind: 'inspect', participant: 'p0' });
  const result = finish(optimal);
  assert.equal(result.metrics.inspectionCost, '1');
  assert.equal(result.metrics.expectedPrincipalLoss, '0');
  assert.equal(result.metrics.score, '1');
});

test('null and erased-signal controls preserve uncertainty and charge useless inspections', () => {
  const erased = create({ seed: 4, axes: { private_information: 'hard' } });
  assert.equal(reference(erased.view()).kind, 'delegate');
  assert.equal(finish(erased).metrics.remainingSupport, '6');
  const game = create({ seed: 13 });
  assert.equal(reference(game.view()).kind, 'delegate');
  game.submit({ kind: 'inspect', participant: 'null' });
  const result = finish(game);
  assert.equal(result.metrics.regret, '1');
  assert.equal(result.metrics.remainingSupport, '6');
  assert.equal(result.metrics.forecastExcess, '0');
});

test('forecast conditioning agrees with independent program execution after a coarse observation', () => {
  const game = create({ seed: 8, privateSeed: 6, axes: { depth: 'medium', branching: 'medium', alignment: 'medium', private_information: 'medium', inspection_budget: 'medium' } });
  game.submit({ kind: 'inspect', participant: game.view().root });
  const view = game.view(), action = reference(view);
  assert.equal(action.kind, 'delegate');
  const surviving = view.worlds.map((_, index) => index).filter(index => Math.floor(((index + view.participants[0].channelOffset) % 6) / 2) === Number(view.history[0].signal.slice(1)));
  const total = surviving.reduce((sum, index) => sum + view.priorWeights[index], 0);
  const predicted = [0, 1, 2].map(output => surviving.filter(index => independent(view, view.root, action.request, index) === output).reduce((sum, index) => sum + view.priorWeights[index], 0) / total);
  action.forecast.forEach((text, index) => { const fields = text.split('/').map(Number); assert.equal(fields[0] / (fields[1] ?? 1), predicted[index]); });
  assert.equal(game.submit(action).metrics.forecastExcess, '0');
});

test('flattening the hierarchy and assuming compliance lose prediction accuracy', () => {
  const flat = create({ seed: 1, axes: { depth: 'medium', alignment: 'hard' } });
  assert.equal(flat.submit(baselines.flatten_tree(flat.view())).metrics.forecastExcess, '1/2');
  const compliant = create({ seed: 5, axes: { depth: 'medium', alignment: 'hard' } });
  assert.notEqual(compliant.submit(baselines.assume_compliance(compliant.view())).metrics.forecastExcess, '0');
});

test('invalid actions and closed episodes preserve public and trusted state', () => {
  const game = create({ seed: 7 }), before = game.view(), audit = game.audit();
  [null, { kind: 'inspect', participant: 'missing' }, { kind: 'inspect', participant: 'p0', extra: 2 },
    { kind: 'delegate', request: 3, forecast: ['1', '0', '0'] }, { kind: 'delegate', request: 0, forecast: ['1', '1', '0'] },
    { kind: 'delegate', request: 0, forecast: ['NaN', '0', '0'] }, { kind: 'delegate', request: 0, forecast: [1, 0, 0] },
    { kind: 'delegate', request: 0, forecast: ['1', '0', '0'], extra: 1 }].forEach(action => {
    assert.throws(() => game.submit(action)); assert.deepEqual(game.view(), before); assert.deepEqual(game.audit(), audit);
  });
  game.submit({ kind: 'inspect', participant: 'null' });
  const inspected = game.view();
  assert.throws(() => game.submit({ kind: 'inspect', participant: 'null' }));
  assert.deepEqual(game.view(), inspected);
  finish(game);
  const completed = game.audit();
  assert.throws(() => game.submit({ kind: 'inspect', participant: 'p0' }));
  assert.deepEqual(game.audit(), completed);
});

test('seed reproducibility, public packet separation, and isolated snapshots', () => {
  const first = create({ seed: 5, privateSeed: 0 }), second = create({ seed: 5, privateSeed: 3 });
  assert.deepEqual(first.view(), second.view());
  assert.notEqual(first.audit().hiddenWorld, second.audit().hiddenWorld);
  const exposed = first.view(); exposed.participants[0].bias = 99; exposed.history.push({ signal: 'spoof' });
  assert.notEqual(first.view().participants[0].bias, 99);
  assert.equal(first.view().history.length, 0);
  assert.doesNotMatch(JSON.stringify(first.view()), /privateSeed|hiddenIndex|hiddenWorld|execution|targetPosterior/);
  assert.deepEqual(finish(first), finish(create({ seed: 5, privateSeed: 0 })));
  assert.throws(() => create({ seed: 1.1 })); assert.throws(() => create({ axes: { missing: 'easy' } })); assert.throws(() => create({ axes: { depth: 'extreme' } }));
});

test('inspection leaves the participant program unchanged and exhausted budgets are atomic', () => {
  const game = create({ seed: 9, axes: { private_information: 'medium', inspection_budget: 'medium' } });
  const before = game.view();
  game.submit({ kind: 'inspect', participant: 'null' });
  const after = game.view(), trusted = game.audit();
  [0, 1, 2].forEach(request => before.worlds.forEach((_, index) => assert.deepEqual(execute(before, request, index), execute(after, request, index))));
  assert.equal(after.budget.remaining, 0);
  assert.throws(() => game.submit({ kind: 'inspect', participant: before.root }));
  assert.deepEqual(game.view(), after);
  assert.deepEqual(game.audit(), trusted);
});

test('each inspection-budget level changes attainable posterior information on a fixed fixture', () => {
  const outcomes = ['easy', 'medium', 'hard'].map(inspection_budget => finish(create({ seed: 3, privateSeed: 3, axes: { private_information: 'medium', inspection_budget } })).metrics);
  assert.deepEqual(outcomes.map(metrics => metrics.inspectionCost), ['2', '1', '0']);
  assert.deepEqual(outcomes.map(metrics => metrics.remainingSupport), ['1', '2', '6']);
  assert.deepEqual(outcomes.map(metrics => metrics.expectedPrincipalLoss), ['0', '3', '6']);
});

test('all 243 cross-axis combinations preserve exact planning and outcome forecasts', () => {
  const settings = definition.axes.reduce((prefixes, axis) => prefixes.flatMap(prefix => Object.keys(axis.levels).map(level => ({ ...prefix, [axis.id]: level }))), [{}]);
  assert.equal(settings.length, 243);
  settings.forEach(axes => {
    const result = finish(create({ seed: 4, privateSeed: 19, axes }));
    assert.equal(result.metrics.score, '1', JSON.stringify(axes));
    assert.equal(result.metrics.regret, '0');
    assert.equal(result.metrics.forecastExcess, '0');
  });
});

test('missing output probabilities are rejected before native or JSON submissions change state', () => {
  const game = create({ seed: 7 }), before = game.view(), trusted = game.audit();
  const sparse = Array(3); sparse[0] = '1';
  [sparse, JSON.parse(JSON.stringify(sparse))].forEach(forecast => {
    assert.throws(() => game.submit({ kind: 'delegate', request: 0, forecast }));
    assert.deepEqual(game.view(), before);
    assert.deepEqual(game.audit(), trusted);
    assert.equal(game.done, false);
  });
});

test('submitted and returned forecast arrays cannot rewrite a completed audit', () => {
  const game = create({ seed: 5, axes: { inspection_budget: 'hard' } });
  const action = reference(game.view()), response = game.submit(action), trusted = game.audit();
  action.forecast.fill('0');
  response.forecast.fill('1');
  assert.deepEqual(game.audit(), trusted);
  assert.equal(game.done, true);
});

test('one uniform finite ticket cycle realizes each state prior weight exactly', () => {
  const view = create({ seed: 5 }).view(), mass = view.priorWeights.reduce((sum, weight) => sum + weight, 0);
  const realized = Array.from({ length: mass }, (_, privateSeed) => create({ seed: 5, privateSeed }).audit().hiddenWorld);
  assert.deepEqual(view.worlds.map(world => realized.filter(id => id === world.id).length), view.priorWeights);
  assert.equal(create({ seed: 5, privateSeed: mass }).audit().hiddenWorld, realized[0]);
});
