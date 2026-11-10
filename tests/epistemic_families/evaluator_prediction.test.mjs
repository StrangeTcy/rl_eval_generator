import test from 'node:test';
import assert from 'node:assert/strict';
import { create, definition, features, quality, rubricScore, reference, baselines } from '../../arena/epistemic_families/evaluator_prediction.mjs';

const near = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-10, `${actual} != ${expected}`);
const complete = game => {
  let result;
  for (let count = 0; count < 4 && !game.done; count++) result = game.submit(reference(game.view()));
  assert.equal(game.done, true);
  return result;
};

test('evaluator features and factual quality agree with a hand-calculated report', () => {
  const source = { facts: [{ id: 'a', value: 1 }, { id: 'b', value: 0 }, { id: 'c', value: 1 }], required: ['a', 'b', 'c'] };
  const document = { id: 'x', claims: [{ fact: 'a', value: 1 }, { fact: 'b', value: 0 }, { fact: 'c', value: 0 }], caveat: false, example: true };
  assert.deepEqual(features(document, source, 5), [2 / 3, 2 / 3, 1, 0, 1]);
  near(quality(document, source), 2 / 3);
  near(rubricScore(document, source, [1, 2, 3]), 5 / 6);
  near(rubricScore(document, source, [1, 2, 3, 4, 5]), 2 / 3);
});

test('all five axes alter operative inputs at every declared level', () => {
  definition.axes.forEach(axis => Object.entries(axis.levels).forEach(([level, value]) => {
    const view = create({ seed: 19, axes: { [axis.id]: level } }).view();
    assert.equal(view.axes[axis.id], value);
    if (axis.id === 'criteria') assert.equal(view.rubrics[0].weights.length, value);
    if (axis.id === 'rubrics') assert.equal(view.rubrics.length, value);
    if (axis.id === 'candidates') assert.equal(view.documents.length, value);
    if (axis.id === 'revisions') assert.equal(view.remainingRevisions, value);
    if (axis.id === 'uncertainty') near(view.rubrics[0].prior / view.rubrics[1].prior, value);
  }));
});

test('public packets and revision observations do not expose target scores or identity', () => {
  const games = [1, 2, 3, 4, 5].map(privateSeed => create({ seed: 8, privateSeed, axes: { revisions: 'hard', uncertainty: 'hard' } }));
  const initial = JSON.stringify(games[0].view());
  games.forEach(game => assert.equal(JSON.stringify(game.view()), initial));
  const action = reference(games[0].view());
  assert.equal(action.kind, 'revise');
  const observations = games.map(game => game.submit(action));
  observations.forEach(observation => {
    assert.equal(JSON.stringify(observation), JSON.stringify(observations[0]));
    assert.equal(Object.hasOwn(observation, 'targetScore'), false);
    assert.equal(Object.hasOwn(observation, 'targetRubric'), false);
  });
  assert.ok(new Set(games.map(game => game.audit().targetRubric.id)).size > 1);
});

test('invalid revisions and malformed final forecasts are atomic', () => {
  const game = create({ axes: { revisions: 'medium' } });
  const initial = JSON.stringify(game.view());
  [{ kind: 'revise', candidateId: 'missing', editId: 'missing' }, { kind: 'revise', candidateId: game.view().documents[0].id, editId: 'missing' },
    { kind: 'submit', selectedId: 'missing', predictions: [] }, { kind: 'receive_score' }].forEach(action => {
    assert.throws(() => game.submit(action)); assert.equal(JSON.stringify(game.view()), initial); assert.equal(game.done, false);
  });
  const terminal = baselines.no_revision(game.view());
  [-1, 1.1, Infinity, NaN].forEach(score => {
    const changed = structuredClone(terminal); changed.predictions[0].score = score;
    assert.throws(() => game.submit(changed)); assert.equal(JSON.stringify(game.view()), initial);
  });
  game.submit(terminal);
  assert.throws(() => game.submit(terminal), /closed/);
});

test('bounded public planner completes varied axes and expected-score forecasts are exact', () => {
  ['easy', 'medium', 'hard'].forEach(level => [3, 29].forEach(seed => {
    const axes = Object.fromEntries(definition.axes.map(axis => [axis.id, level]));
    const game = create({ seed, privateSeed: 73, axes });
    const result = complete(game);
    near(result.metrics.forecastExcess, 0);
    near(result.metrics.selectedForecastExcess, 0);
    near(result.metrics.revisionForecastExcess, 0);
    near(result.metrics.expectedSelectionRegret, 0);
    assert.ok(result.metrics.revisionsUsed <= game.view().axes.revisions);
    assert.ok(result.metrics.factualQuality >= 0 && result.metrics.factualQuality <= 1);
    assert.equal(result.candidates.length, game.view().axes.candidates);
  }));
});

test('pre-edit forecasts are recorded prospectively and judged only at terminal', () => {
  const game = create({ seed: 8, axes: { revisions: 'medium' } });
  const action = reference(game.view());
  assert.equal(action.kind, 'revise');
  action.predictedBefore = 1; action.predictedAfter = 0;
  const observation = game.submit(action);
  assert.equal(Object.hasOwn(observation, 'forecastExcess'), false);
  assert.equal(Object.hasOwn(observation, 'targetScore'), false);
  const result = game.submit(baselines.no_revision(game.view()));
  assert.equal(result.metrics.revisionForecastCount, 2);
  assert.ok(result.metrics.revisionForecastExcess > 0);
});

test('forecast variance is irreducible and is separate from forecast excess', () => {
  const game = create({ seed: 17, privateSeed: 21, axes: { rubrics: 'hard', uncertainty: 'hard', candidates: 'hard', criteria: 'hard' } });
  const result = game.submit(baselines.no_revision(game.view()));
  near(result.metrics.forecastExcess, 0);
  assert.ok(result.metrics.conditionalForecastMSE > 0);
  const certainty = create({ seed: 17, privateSeed: 21, axes: { rubrics: 'hard', uncertainty: 'hard', candidates: 'hard', criteria: 'hard' } });
  assert.ok(certainty.submit(baselines.first_rubric_certainty(certainty.view())).metrics.forecastExcess > 0);
});

test('reported quality is independently recomputed from facts, not evaluator preference', () => {
  const game = create({ seed: 41, axes: { criteria: 'hard', candidates: 'hard', rubrics: 'hard' } });
  const view = game.view(), action = baselines.quality_first(view), result = game.submit(action);
  const document = view.documents.find(item => item.id === action.selectedId);
  const supported = document.claims.filter(claim => view.source.facts.some(fact => fact.id === claim.fact && fact.value === claim.value));
  const coverage = view.source.required.filter(id => supported.some(claim => claim.fact === id)).length / view.source.required.length;
  near(result.metrics.factualQuality, (supported.length / document.claims.length + coverage) / 2);
  near(result.metrics.factualQualityRegret, 0);
});

test('generated rubric vectors are distinct and priors normalize', () => {
  ['easy', 'medium', 'hard'].forEach(criteria => {
    const view = create({ seed: 98, axes: { criteria, rubrics: 'hard', uncertainty: 'medium' } }).view();
    assert.equal(new Set(view.rubrics.map(rubric => JSON.stringify(rubric.weights))).size, 6);
    near(view.rubrics.reduce((sum, rubric) => sum + rubric.prior, 0), 1);
    view.rubrics.forEach(rubric => assert.ok(rubric.weights.every(weight => weight > 0)));
  });
  assert.throws(() => create({ axes: { unknown: 'easy' } }), /axis/);
  assert.throws(() => create({ axes: { candidates: 'impossible' } }), /axis/);
});
