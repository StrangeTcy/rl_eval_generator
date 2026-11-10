import test from 'node:test';
import assert from 'node:assert/strict';
import { create, definition, reason, diagnostic, posterior, plan, reference, baselines } from '../../arena/epistemic_families/agent_reconstruction.mjs';

const matrix = rows => ({ id: 'fixture', actions: ['a0', 'a1'], payoffs: [rows, rows] });
const mind = (player = 0, belief = null) => ({ player, selfWeight: 1, otherWeight: 0, stateWeights: [1, 1], baseOpponentWeights: [1, 1], belief });
const finish = game => {
  let result;
  for (let turn = 0; turn < 6 && !game.done; turn++) result = game.submit(reference(game.view()));
  assert.equal(game.done, true);
  return result;
};

test('recursive alternating-player expected utility agrees with independent hand calculation', () => {
  const context = matrix([[[4, 1], [0, 3]], [[1, 0], [3, 2]]]);
  assert.deepEqual(reason(context, mind()).utilities, ['2', '2']);
  assert.equal(reason(context, mind()).action, 0);
  const nested = reason(context, mind(0, mind(1)));
  assert.deepEqual(nested.opponent.utilities, ['1/2', '5/2']);
  assert.equal(nested.opponent.action, 1);
  assert.deepEqual(nested.utilities, ['0', '3']);
  assert.equal(nested.action, 1);
  assert.equal(nested.margin, '3');
  const pennies = matrix([[[1, 0], [0, 1]], [[0, 1], [1, 0]]]);
  assert.equal(reason(pennies, mind(0, mind(1))).action, 0);
  assert.equal(reason(pennies, mind(0, mind(1, mind(0)))).action, 1);
});

test('state beliefs and social preferences independently alter executable best responses', () => {
  const context = { id: 'states', actions: ['a0', 'a1'], payoffs: [
    [[[8, 0], [8, 0]], [[0, 6], [0, 6]]],
    [[[0, 0], [0, 0]], [[8, 6], [8, 6]]],
  ] };
  assert.deepEqual(reason(context, { ...mind(), stateWeights: [3, 1] }).utilities, ['6', '2']);
  assert.equal(reason(context, { ...mind(), stateWeights: [1, 3] }).action, 1);
  assert.equal(reason(context, { ...mind(), stateWeights: [3, 1], selfWeight: 0, otherWeight: 1 }).action, 1);
});

test('public exact planner agrees with hand-computed one-query values and posterior', () => {
  const context = matrix([[[6, 0], [6, 0]], [[0, 6], [0, 6]]]);
  const view = { models: [{ id: 'm0', priorWeight: 1, mind: mind() }, { id: 'm1', priorWeight: 3, mind: { ...mind(), selfWeight: 0, otherWeight: 1 } }],
    queries: [{ id: 'q0', cost: 1, context }, { id: 'null', cost: 1, context: matrix([[[0, 0], [0, 0]], [[0, 0], [0, 0]]]) }],
    targetContext: context, history: [], axes: { visibility: 'action' }, budget: { remaining: 1 }, rules: { errorCost: 12 } };
  assert.deepEqual(posterior(view).map(String), ['1/4', '3/4']);
  assert.equal(String(plan(view).stop), '3');
  assert.equal(String(plan(view).value), '1');
  assert.deepEqual(plan(view).candidates.map(candidate => [candidate.query, String(candidate.value)]), [['q0', '1'], ['null', '4']]);
  assert.deepEqual(reference(view), { kind: 'query', query: 'q0' });
  view.history = [{ query: 'q0', signal: '1' }]; view.budget.remaining = 0;
  assert.deepEqual(reference(view), { kind: 'answer', decision: 'm1', modelForecast: ['0', '1'], actionForecast: ['0', '1'] });
});

test('every axis changes an operative quantity at all declared levels', () => {
  const depth = item => item.belief === null ? 0 : 1 + depth(item.belief);
  definition.axes.forEach(axis => Object.entries(axis.levels).forEach(([level, value]) => {
    const view = create({ seed: 17, axes: { [axis.id]: level } }).view();
    assert.equal(view.axes[axis.id], value);
    if (axis.id === 'models') assert.equal(view.models.length, value);
    if (axis.id === 'recursion') assert.equal(depth(view.models[0].mind), value);
    if (axis.id === 'actions') assert.equal(view.targetContext.payoffs[0].length, value);
    if (axis.id === 'budget') assert.equal(view.budget.remaining, value);
    if (axis.id === 'visibility') {
      const raw = reason(view.queries[0].context, view.models[0].mind);
      assert.equal(diagnostic(view.queries[0].context, view.models[0], value), value === 'action-and-margin' ? `${raw.action}:${raw.margin}` : value === 'action' ? String(raw.action) : String(raw.action % 2));
    }
  }));
});

test('all 243 cross-axis combinations execute to the exact public optimum', () => {
  const visit = (index, axes) => {
    if (index === definition.axes.length) {
      const game = create({ seed: 19, privateSeed: 5, axes });
      const result = finish(game);
      assert.equal(result.metrics.score, '1', JSON.stringify(axes));
      assert.equal(result.metrics.regret, '0');
      assert.equal(result.metrics.modelForecastExcess, '0');
      assert.equal(result.metrics.actionForecastExcess, '0');
      return;
    }
    Object.keys(definition.axes[index].levels).forEach(level => visit(index + 1, { ...axes, [definition.axes[index].id]: level }));
  };
  visit(0, {});
});

test('null observations preserve ambiguity and public reference stops without waste', () => {
  const game = create({ seed: 13, axes: { recursion: 'hard', models: 'hard', visibility: 'hard' } });
  const initial = posterior(game.view()).map(String);
  assert.equal(reference(game.view()).kind, 'answer');
  assert.equal(game.submit({ kind: 'query', query: 'null' }).signal, '0');
  assert.deepEqual(posterior(game.view()).map(String), initial);
  const result = finish(game);
  assert.equal(result.metrics.regret, '1');
  assert.equal(result.metrics.remainingSupport, '7');
  const fresh = create({ seed: 13 });
  assert.equal(finish(fresh).metrics.score, '1');
});

test('private sampling and prospective held-out actions remain outside public packets', () => {
  const games = Array.from({ length: 18 }, (_, privateSeed) => create({ seed: 7, privateSeed, axes: { models: 'hard', recursion: 'hard' } }));
  const packet = JSON.stringify(games[0].view());
  games.forEach(game => {
    assert.equal(JSON.stringify(game.view()), packet);
    assert.equal(Object.hasOwn(game.view(), 'hiddenModel'), false);
    assert.equal(Object.hasOwn(game.view(), 'targetExecution'), false);
  });
  assert.ok(new Set(games.map(game => game.audit().hiddenModel)).size > 1);
  const altered = games[0].view(); altered.models[0].mind.selfWeight = 999; altered.history.push({ query: 'fake' });
  assert.equal(JSON.stringify(games[0].view()), packet);
  games.slice(0, 4).forEach(game => assert.equal(finish(game).metrics.score, '1'));
});

test('malformed actions, duplicate queries and exhausted budgets preserve state atomically', () => {
  const game = create({ axes: { budget: 'hard' } });
  const initial = JSON.stringify(game.view());
  const valid = baselines.stop(game.view());
  [null, [], {}, { kind: 'query', query: 'missing' }, { kind: 'query', query: 'q0', extra: 1 },
    { ...valid, decision: 'missing' }, { ...valid, modelForecast: ['1'] },
    { ...valid, actionForecast: ['0', '0'] }, { ...valid, actionForecast: ['1/0', '0'] },
    { ...valid, actionForecast: [0.5, 0.5] }, { ...valid, actionForecast: ['01', '0'] },
    { ...valid, actionForecast: ['1\n', '0'] }].forEach(action => {
    assert.throws(() => game.submit(action)); assert.equal(JSON.stringify(game.view()), initial); assert.equal(game.done, false);
  });
  game.submit({ kind: 'query', query: 'q0' });
  const observed = JSON.stringify(game.view());
  assert.throws(() => game.submit({ kind: 'query', query: 'q0' }));
  assert.throws(() => game.submit({ kind: 'query', query: 'q1' }));
  assert.equal(JSON.stringify(game.view()), observed);
  finish(game);
  assert.throws(() => game.submit(valid), /terminal/);
});

test('closed options reject malformed axes and seeds', () => {
  [null, [], { seed: NaN }, { privateSeed: 0.5 }, { extra: 1 }, { axes: [] }, { axes: { unknown: 'easy' } }, { axes: { models: 'extreme' } }].forEach(options => assert.throws(() => create(options)));
});

test('generated payoff matrices vary beyond catalogue response tables and baselines execute', () => {
  const signatures = [2, 3, 4, 5].map(seed => JSON.stringify(create({ seed }).view().targetContext.payoffs));
  assert.equal(new Set(signatures).size, 4);
  Object.values(baselines).forEach(policy => {
    const game = create({ seed: 8, axes: { recursion: 'hard' } });
    for (let turn = 0; turn < 6 && !game.done; turn++) game.submit(policy(game.view()));
    assert.equal(game.done, true);
  });
});

test('budget changes optimal inquiry and flattening real recursion loses forecast accuracy', () => {
  const axes = { models: 'hard', recursion: 'hard', actions: 'hard', visibility: 'hard' };
  const oneQuery = create({ seed: 1, axes: { ...axes, budget: 'hard' } });
  const fourQueries = create({ seed: 1, axes: { ...axes, budget: 'easy' } });
  assert.equal(String(plan(oneQuery.view()).value), '17/2');
  assert.equal(String(plan(fourQueries.view()).value), '37/8');
  assert.equal(oneQuery.submit(baselines.no_recursion(oneQuery.view())).metrics.actionForecastExcess, '3/128');
  assert.equal(finish(fourQueries).metrics.score, '1');
});

test('missing forecast entries are rejected through both native and JSON action paths', () => {
  const game = create({ seed: 13 }), before = game.view(), trusted = game.audit();
  const sparseModels = Array(before.models.length), sparseActions = Array(before.targetContext.actions.length);
  // These sum to one under sparse-array reduction, but omit required zero entries.
  sparseModels[0] = '1'; sparseActions[0] = '1';
  const valid = baselines.stop(before);
  [{ ...valid, modelForecast: sparseModels }, { ...valid, actionForecast: sparseActions }].forEach(action => {
    [action, JSON.parse(JSON.stringify(action))].forEach(candidate => {
      assert.throws(() => game.submit(candidate));
      assert.deepEqual(game.view(), before);
      assert.deepEqual(game.audit(), trusted);
      assert.equal(game.done, false);
    });
  });
});

test('one uniform finite ticket cycle realizes each model prior weight exactly', () => {
  const axes = { models: 'hard', recursion: 'medium' }, view = create({ seed: 7, axes }).view();
  const mass = view.models.reduce((sum, model) => sum + model.priorWeight, 0);
  const realized = Array.from({ length: mass }, (_, privateSeed) => create({ seed: 7, privateSeed, axes }).audit().hiddenModel);
  assert.deepEqual(view.models.map(model => realized.filter(id => id === model.id).length), view.models.map(model => model.priorWeight));
  assert.equal(create({ seed: 7, privateSeed: mass, axes }).audit().hiddenModel, realized[0]);
});
