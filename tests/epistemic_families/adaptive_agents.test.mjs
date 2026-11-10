import test from 'node:test';
import assert from 'node:assert/strict';
import { create, definition, trajectory, diagnostic, posterior, forecast, plan, reference, baselines } from '../../arena/epistemic_families/adaptive_agents.mjs';

const fixture = () => ({ family: 'adaptive_agents', axes: { learner_count: 2, update_law: 'cumulative', change_cadence: 0, observation_access: 'action-only', forecast_horizon: 2, inspection_budget: 1 },
  learners: [{ id: 'positive', initialScore: 0, polarity: 1, priorWeight: 1 }, { id: 'negative', initialScore: 0, polarity: -1, priorWeight: 3 }],
  stream: [2, -3, 4, -1], queries: [{ id: 'q0', checkpoint: 0 }, { id: 'q1', checkpoint: 1 }, { id: 'null', checkpoint: null }],
  rules: { historyLength: 2, threshold: 0, diagnosticOutage: false }, history: [], budget: { initial: 1, remaining: 1 } });
const complete = game => {
  let result;
  for (let count = 0; count < 5 && !game.done; count++) result = game.submit(reference(game.view()));
  assert.equal(game.done, true);
  return result;
};

test('all three update laws and polarity cadence match independent hand calculations', () => {
  const view = fixture(), learner = { initialScore: 3, polarity: 1 };
  assert.deepEqual(trajectory(view, learner).map(point => point.score), [5, 2, 6, 5]);
  view.axes.update_law = 'leaky';
  assert.deepEqual(trajectory(view, learner).map(point => point.score), [3, -2, 3, 0]);
  view.axes.update_law = 'window-two';
  assert.deepEqual(trajectory(view, learner).map(point => point.score), [5, -1, 1, 3]);
  view.axes.update_law = 'cumulative'; view.axes.change_cadence = 1;
  assert.deepEqual(trajectory(view, learner).map(point => point.score), [5, 8, 12, 13]);
  assert.deepEqual(trajectory(view, learner).map(point => point.polarity), [1, -1, 1, -1]);
});

test('weighted forecast and one-step value of information match a hand oracle', () => {
  const view = fixture();
  assert.deepEqual(posterior(view).map(String), ['1/4', '3/4']);
  assert.deepEqual(forecast(view).map(String), ['1/4', '1/4']);
  const optimum = plan(view);
  assert.equal(String(optimum.stop), '3/16');
  assert.equal(String(optimum.value), '0');
  assert.equal(String(optimum.candidates.find(candidate => candidate.query === 'null').value), '3/16');
  assert.deepEqual(reference(view), { kind: 'inspect', query: 'q0' });
  view.history.push({ kind: 'observation', query: 'q0', signal: 'action:0' }); view.budget.remaining = 0;
  assert.deepEqual(reference(view), { kind: 'forecast', probabilities: ['0', '0'] });
});

test('identical historical actions preserve uncertainty over opposite future behavior', () => {
  const view = fixture();
  view.stream = [0, 1]; view.rules.historyLength = 1; view.axes.forecast_horizon = 1;
  view.queries = [{ id: 'q0', checkpoint: 0 }, { id: 'null', checkpoint: null }];
  assert.equal(diagnostic(view, view.learners[0], 'q0'), 'action:1');
  assert.equal(diagnostic(view, view.learners[1], 'q0'), 'action:1');
  assert.deepEqual(reference(view), { kind: 'forecast', probabilities: ['1/4'] });
  view.history.push({ kind: 'observation', query: 'q0', signal: 'action:1' });
  assert.deepEqual(posterior(view).map(String), ['1/4', '3/4']);
});

test('diagnostic visibility filters real state observations and null never identifies a learner', () => {
  const view = fixture();
  view.axes.observation_access = 'state-and-action';
  assert.equal(diagnostic(view, view.learners[0], 'q0'), 'score:2;action:1');
  view.axes.observation_access = 'action-only';
  assert.equal(diagnostic(view, view.learners[0], 'q0'), 'action:1');
  view.axes.observation_access = 'alternate-action';
  assert.equal(diagnostic(view, view.learners[0], 'q1'), 'withheld');
  view.history.push({ kind: 'observation', query: 'null', signal: 'withheld' });
  assert.deepEqual(posterior(view).map(String), ['1/4', '3/4']);
  const outage = create({ seed: 17, axes: { learner_count: 'hard' } });
  assert.equal(outage.view().rules.diagnosticOutage, true);
  assert.equal(reference(outage.view()).kind, 'forecast');
  assert.equal(complete(outage).metrics.inspections, '0');
});

test('private identity is absent from every initial public packet', () => {
  const games = Array.from({ length: 12 }, (_, privateSeed) => create({ seed: 31, privateSeed, axes: { learner_count: 'hard' } }));
  const publicPacket = JSON.stringify(games[0].view());
  games.forEach(game => assert.equal(JSON.stringify(game.view()), publicPacket));
  assert.ok(new Set(games.map(game => game.audit().hiddenLearner)).size > 1);
  assert.equal(Object.hasOwn(games[0].view(), 'trajectory'), false);
  const detached = games[0].view(); detached.stream[0] = 9999; detached.learners[0].initialScore = 9999;
  assert.equal(JSON.stringify(games[0].view()), publicPacket);
});

test('malformed actions, repeated inspections, and invalid fractions preserve state', () => {
  const game = create({ seed: 9 });
  const before = JSON.stringify(game.view());
  [null, [], { kind: 'inspect', query: 'missing' }, { kind: 'inspect', query: 'null', train: 1 },
    { kind: 'train', input: 3 }, { kind: 'forecast', probabilities: [] }, { kind: 'forecast', probabilities: ['2'] },
    { kind: 'forecast', probabilities: ['-1'] }, { kind: 'forecast', probabilities: [0.5] },
    { kind: 'forecast', probabilities: ['1/0'] }, { kind: 'forecast', probabilities: ['1\n'] }].forEach(action => {
    assert.throws(() => game.submit(action)); assert.equal(JSON.stringify(game.view()), before); assert.equal(game.done, false);
  });
  game.submit({ kind: 'inspect', query: 'null' });
  const inspected = JSON.stringify(game.view());
  assert.throws(() => game.submit({ kind: 'inspect', query: 'null' }));
  assert.equal(JSON.stringify(game.view()), inspected);
  game.submit(baselines.stop(game.view()));
  assert.throws(() => game.submit(baselines.stop(game.view())), /terminal/);
});

test('creation rejects unknown options, invalid axes and unsafe seeds', () => {
  [{ seed: 1.5 }, { privateSeed: Infinity }, { seed: Number.MAX_SAFE_INTEGER + 1 }, { unknown: 3 },
    { axes: [] }, { axes: { update_law: 'other' } }, { axes: { nonexistent: 'easy' } }].forEach(options => assert.throws(() => create(options)));
});

test('each declared axis changes its operative resource or process independently', () => {
  definition.axes.forEach(axis => Object.entries(axis.levels).forEach(([level, value]) => {
    const view = create({ seed: 31, axes: { [axis.id]: level } }).view();
    assert.equal(view.axes[axis.id], value);
    if (axis.id === 'learner_count') assert.equal(view.learners.length, value);
    if (axis.id === 'forecast_horizon') assert.equal(view.stream.length - view.rules.historyLength, value);
    if (axis.id === 'inspection_budget') assert.equal(view.budget.initial, value);
  }));
  const view = fixture();
  const cumulative = trajectory(view, view.learners[0]);
  view.axes.update_law = 'leaky'; assert.notDeepEqual(trajectory(view, view.learners[0]), cumulative);
  view.axes.update_law = 'cumulative'; view.axes.change_cadence = 3;
  assert.notDeepEqual(trajectory(view, view.learners[0]), cumulative);
});

test('all 729 cross-axis combinations complete with exact public reference forecasts and planning', () => {
  const combinations = definition.axes.reduce((rows, axis) => rows.flatMap(row => Object.keys(axis.levels).map(level => ({ ...row, [axis.id]: level }))), [{}]);
  assert.equal(combinations.length, 729);
  combinations.forEach((axes, index) => {
    const game = create({ seed: index + 1, privateSeed: index * 7 + 2, axes });
    const result = complete(game);
    assert.equal(result.metrics.score, '1', JSON.stringify(axes));
    assert.equal(result.metrics.forecastExcess, '0');
    assert.equal(result.metrics.inquiryRegret, '0');
    assert.ok(Number(result.metrics.inspections) <= game.view().axes.inspection_budget);
  });
});

test('forecast-only actions leave the entire exogenous learner trajectory unchanged', () => {
  const first = create({ seed: 73, privateSeed: 8, axes: { forecast_horizon: 'hard', change_cadence: 'hard' } });
  const second = create({ seed: 73, privateSeed: 8, axes: { forecast_horizon: 'hard', change_cadence: 'hard' } });
  const truth = first.audit().trajectory;
  complete(first);
  second.submit({ kind: 'inspect', query: 'null' }); second.submit(baselines.frozen_state(second.view()));
  assert.deepEqual(first.audit().trajectory, truth);
  assert.deepEqual(second.audit().trajectory, truth);
  const signatures = Array.from({ length: 10 }, (_, seed) => JSON.stringify(create({ seed: seed + 1 }).view().stream));
  assert.ok(new Set(signatures).size >= 8);
});

test('frozen-state ablation has positive forecast loss on generated changing learners', () => {
  const losses = Array.from({ length: 40 }, (_, index) => {
    const game = create({ seed: index + 1, axes: { change_cadence: 'hard', forecast_horizon: 'hard', update_law: 'medium' } });
    return game.submit(baselines.frozen_state(game.view())).metrics.forecastExcess;
  });
  assert.ok(losses.some(value => value !== '0'));
});

test('missing future forecasts are rejected through both native and JSON action paths', () => {
  const game = create({ seed: 17, axes: { forecast_horizon: 'hard' } }), before = game.view(), trusted = game.audit();
  const partial = ['0', '0', '0', '0']; delete partial[2];
  // An all-hole array previously accumulated zero forecast error without predicting any future action.
  [Array(4), partial].forEach(probabilities => {
    [probabilities, JSON.parse(JSON.stringify(probabilities))].forEach(candidate => {
      assert.throws(() => game.submit({ kind: 'forecast', probabilities: candidate }));
      assert.deepEqual(game.view(), before);
      assert.deepEqual(game.audit(), trusted);
      assert.equal(game.done, false);
    });
  });
});

test('extending the forecast horizon preserves the existing process and observable history', () => {
  [3, 4, 31].forEach(seed => ['easy', 'medium', 'hard'].forEach(update_law => {
    const axes = { learner_count: 'hard', update_law, change_cadence: 'hard' };
    const longest = create({ seed, axes: { ...axes, forecast_horizon: 'hard' } }).view();
    ['easy', 'medium'].forEach(forecast_horizon => {
      const shorter = create({ seed, axes: { ...axes, forecast_horizon } }).view();
      assert.equal(shorter.rules.threshold, longest.rules.threshold);
      assert.deepEqual(shorter.learners, longest.learners);
      assert.deepEqual(shorter.queries, longest.queries);
      assert.deepEqual(shorter.stream, longest.stream.slice(0, shorter.stream.length));
      shorter.learners.forEach((learner, index) => {
        assert.deepEqual(trajectory(shorter, learner), trajectory(longest, longest.learners[index]).slice(0, shorter.stream.length));
        shorter.queries.forEach(query => assert.equal(diagnostic(shorter, learner, query.id), diagnostic(longest, longest.learners[index], query.id)));
      });
    });
  }));
});

test('one uniform finite ticket cycle realizes each learner prior weight exactly', () => {
  const axes = { learner_count: 'hard' }, view = create({ seed: 31, axes }).view();
  const mass = view.learners.reduce((sum, learner) => sum + learner.priorWeight, 0);
  const realized = Array.from({ length: mass }, (_, privateSeed) => create({ seed: 31, privateSeed, axes }).audit().hiddenLearner);
  assert.deepEqual(view.learners.map(learner => realized.filter(id => id === learner.id).length), view.learners.map(learner => learner.priorWeight));
  assert.equal(create({ seed: 31, privateSeed: mass, axes }).audit().hiddenLearner, realized[0]);
});
