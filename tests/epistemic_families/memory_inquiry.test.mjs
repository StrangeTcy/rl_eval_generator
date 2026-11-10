import test from 'node:test';
import assert from 'node:assert/strict';
import { create, definition, reference } from '../../arena/epistemic_families/memory_inquiry.mjs';
import { AxisMatrix, Ratio } from '../../arena/epistemic_families/runtime.mjs';

test('retention boundary removes the full exposure and restores only predetermined records', () => {
  const game = create({ privateSeed: 15, axes: { retention: 'hard', events: 'hard' } });
  assert.equal(game.view().exposure.length, 8);
  game.submit({ kind: 'advance' });
  assert.equal(game.view().exposure.length, 0);
  assert.equal(game.view().retained.length, 1);
  assert.equal(Object.hasOwn(game.view(), 'history'), false);
  assert.equal(Object.hasOwn(game.view(), 'privateSeed'), false);
});

test('retention IDs are independent of private values', () => {
  const views = [0, 1, 7, 255].map(privateSeed => {
    const game = create({ seed: 3, privateSeed, axes: { retention: 'medium', events: 'hard' } });
    game.submit({ kind: 'advance' });
    return game.view().retained.map(event => event.id);
  });
  views.forEach(view => assert.deepEqual(view, views[0]));
});

test('independent ticket counting verifies every posterior after partial retention', () => {
  const groups = new Map();
  for (let ticket = 0; ticket < 16; ticket++) {
    const game = create({ seed: 7, privateSeed: ticket, axes: { retention: 'hard', task: 'hard', sources: 'medium', retrievals: 'hard' } });
    game.submit({ kind: 'advance' });
    const view = game.view(), truth = game.audit().events;
    const key = JSON.stringify(view);
    const outcomes = view.targets.map(target => target.events.reduce((value, id) => value ^ truth.find(event => event.id === id).value, 0));
    const record = { outcomes, result: game.submit(reference(view)) };
    groups.set(key, [...(groups.get(key) ?? []), record]);
  }
  groups.forEach(group => group[0].result.targets.forEach((target, index) => {
    const expected = new Ratio(group.reduce((sum, item) => sum + item.outcomes[index], 0), group.length);
    group.forEach(item => assert.equal(item.result.targets[index].posterior, String(expected)));
  }));
});

test('retrieval changes information and charges exactly one twentieth', () => {
  const game = create({ seed: 8, axes: { retention: 'hard' } });
  game.submit({ kind: 'advance' });
  const id = game.view().skeleton.find(item => !game.view().retained.some(retained => retained.id === item.id)).id;
  const observation = game.submit({ kind: 'retrieve', event: id });
  assert.equal(observation.remaining, 1);
  assert.ok(game.view().retrieved.some(item => item.id === id));
  const answer = { kind: 'answer', predictions: game.view().targets.map(target => ({ target: target.id, probability: '1/2', decision: 0 })) };
  assert.equal(game.submit(answer).metrics.retrievalCost, '1/20');
});

test('distractors change presentation but not target posterior or optimal action', () => {
  const views = ['easy', 'medium', 'hard'].map(distractors => {
    const game = create({ seed: 13, privateSeed: 3, axes: { distractors, retention: 'hard' } });
    game.submit({ kind: 'advance' });
    return game.view();
  });
  assert.deepEqual(views.map(view => view.distractors.length), [0, 2, 5]);
  views.forEach(view => assert.deepEqual(reference(view), reference(views[0])));
});

test('returned retrieval objects cannot mutate the engine or audit', () => {
  const game = create({ privateSeed: 15, axes: { retention: 'hard' } });
  game.submit({ kind: 'advance' });
  const id = game.view().skeleton.find(event => !game.view().retained.some(item => item.id === event.id)).id;
  const response = game.submit({ kind: 'retrieve', event: id });
  const view = game.view(), audit = game.audit();
  response.event.value ^= 1;
  assert.deepEqual(game.view(), view);
  assert.deepEqual(game.audit(), audit);
});

test('complete retention needs no retrieval and yields exact forecasts', () => {
  const game = create({ privateSeed: 9, axes: { task: 'hard' } });
  game.submit(reference(game.view()));
  const action = reference(game.view());
  assert.equal(action.kind, 'answer');
  const result = game.submit(action);
  assert.equal(result.metrics.forecastExcess, '0');
  assert.equal(result.metrics.realizedDecisionLoss, '0');
  assert.equal(result.metrics.retrievalCost, '0');
});

test('invalid actions leave both exposure and recall state unchanged', () => {
  const game = create({ axes: { retention: 'hard' } });
  const initial = game.view();
  assert.throws(() => game.submit({ kind: 'advance', note: 'secret' }));
  assert.deepEqual(game.view(), initial);
  game.submit({ kind: 'advance' });
  const after = game.view();
  [{ kind: 'retrieve', event: 'missing' }, { kind: 'answer', predictions: [] }, { kind: 'answer', predictions: [{ target: after.targets[0].id, probability: '2', decision: 0 }] }].forEach(action => { assert.throws(() => game.submit(action)); assert.deepEqual(game.view(), after); });
});

test('all 729 axis combinations complete through the public reference', () => {
  const vectors = AxisMatrix.expand(definition, 'all');
  assert.equal(vectors.length, 729);
  vectors.forEach(axes => {
    const game = create({ seed: 2, privateSeed: 5, axes });
    let result;
    for (let step = 0; step < 5 && !game.done; step++) result = game.submit(reference(game.view()));
    assert.equal(game.done, true);
    assert.equal(result.metrics.forecastExcess, '0');
    assert.equal(result.metrics.decisionRegret, '0');
    assert.throws(() => game.submit({ kind: 'advance' }), /closed/);
  });
});
