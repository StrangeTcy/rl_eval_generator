import test from 'node:test';
import assert from 'node:assert/strict';
import { create, reference, definition, baselines } from '../../arena/epistemic_families/evidence_process.mjs';
import { Ratio } from '../../arena/inquiry/selection_laws.mjs';

const finish = (game, policy = reference, steps = 0) => {
  assert.ok(steps < 8, 'finite episode');
  const result = game.submit(policy(game.view()));
  return game.done ? result : finish(game, policy, steps + 1);
};

test('exact reference succeeds for every independent axis level and combined hard setting', () => {
  definition.axes.forEach(axis => Object.keys(axis.levels).forEach(level => {
    const game = create({ seed: 4, privateSeed: 7, axes: { [axis.id]: level } });
    const result = finish(game);
    assert.equal(result.metrics.score, '1', `${axis.id}:${level}`);
    assert.equal(result.metrics.regret, '0');
    assert.equal(result.metrics.posteriorExcess, '0');
  }));
  const hard = Object.fromEntries(definition.axes.map(axis => [axis.id, 'hard']));
  const result = finish(create({ seed: 3, privateSeed: 7, axes: hard }));
  assert.equal(result.metrics.score, '1');
  assert.equal(result.metrics.compatibleMechanisms, '3');
});

test('full diagnostic access identifies all three mechanisms under multiple deterministic seeds', () => {
  Array.from({ length: 18 }, (_, privateSeed) => privateSeed).forEach(privateSeed => {
    const game = create({ seed: 4, privateSeed, axes: { severity: 'hard' } });
    const result = finish(game);
    assert.equal(result.metrics.score, '1');
    assert.equal(result.metrics.compatibleMechanisms, '1');
    assert.equal(result.metrics.residualUncertainty, '0');
    assert.equal(game.audit().targetPosterior[['ordinary', 'selection', 'sensor'].indexOf(game.audit().hiddenMechanism)], '1');
  });
});

test('hand-derived high-only batch distinguishes support for selection from identification', () => {
  const game = create({ privateSeed: 1, axes: { diagnostic_access: 'hard', severity: 'medium', evidence_batch: 'medium' } });
  assert.deepEqual(game.view().history.map(event => event.result.shown), [2, 2]);
  const action = reference(game.view());
  assert.deepEqual(action.posterior, ['1/11', '9/11', '1/11']);
  assert.equal(action.mechanism, 'underdetermined');
  const result = game.submit(action);
  assert.equal(result.metrics.score, '1');
  assert.equal(result.metrics.residualUncertainty, '38/121');
});

test('operational interventions separate rejection from transformed sensor readings', () => {
  const selected = create({ seed: 2, privateSeed: 1, axes: { severity: 'medium' } });
  const selectionAudit = selected.submit({ kind: 'diagnose', diagnostic: 'gate_audit' });
  assert.deepEqual(selectionAudit.result.decisions.map(item => item.decision), ['reject', 'reject', 'accept']);
  const transformed = create({ seed: 2, privateSeed: 2, axes: { severity: 'medium' } });
  const sensorAudit = transformed.submit({ kind: 'diagnose', diagnostic: 'calibrate' });
  assert.deepEqual(sensorAudit.result, { raw: 0, shown: 1 });
  assert.equal(reference(transformed.view()).mechanism, 'sensor');
});

test('ordinary and transformed displayed marginal laws retain equal posterior mass', () => {
  Array.from({ length: 12 }, (_, privateSeed) => privateSeed).forEach(privateSeed => {
    const game = create({ privateSeed, axes: { diagnostic_access: 'hard', severity: 'hard', evidence_batch: 'hard' } });
    const action = reference(game.view());
    assert.equal(action.posterior[0], action.posterior[2]);
    assert.equal(action.mechanism, 'underdetermined');
    assert.equal(game.submit(action).metrics.claimError, '0');
  });
});

test('null source audit consumes credit without changing posterior, and skipping useful diagnostics has regret', () => {
  const game = create({ privateSeed: 1 });
  const before = game.audit().targetPosterior, remaining = game.view().budget.remaining;
  game.submit({ kind: 'diagnose', diagnostic: 'source_audit' });
  assert.deepEqual(game.audit().targetPosterior, before);
  assert.equal(game.view().budget.remaining, remaining - 1);
  const premature = create({ privateSeed: 1 });
  const result = premature.submit(baselines.sample_only(premature.view()));
  assert.equal(result.metrics.posteriorExcess, '0');
  assert.equal(result.metrics.regret, '5/8');
  assert.equal(result.metrics.score, '8/13');
});

test('wrong certainty is penalized even when the selected mechanism is the hidden mechanism', () => {
  const game = create({ privateSeed: 1, axes: { diagnostic_access: 'hard' } });
  const result = game.submit(baselines.certain_selection());
  assert.equal(game.audit().hiddenMechanism, 'selection');
  assert.equal(result.metrics.claimError, '1');
  assert.equal(result.metrics.posteriorExcess, '3/8');
  assert.equal(result.metrics.score, '8/19');
});

test('invalid actions preserve random stream and all state; public snapshots are isolated', () => {
  const game = create({ seed: 8, privateSeed: 18 }), twin = create({ seed: 8, privateSeed: 18 });
  const before = game.view(), audit = game.audit();
  [null, { kind: 'diagnose', diagnostic: 'unavailable' }, { kind: 'diagnose', diagnostic: 'paired_trace', extra: 1 }, { kind: 'identify', mechanism: 'selection', posterior: ['1', '1', '1'] }, { kind: 'identify', mechanism: 'unknown', posterior: ['1', '0', '0'] }].forEach(action => {
    assert.throws(() => game.submit(action));
    assert.deepEqual(game.view(), before);
    assert.deepEqual(game.audit(), audit);
  });
  assert.deepEqual(game.submit({ kind: 'diagnose', diagnostic: 'paired_trace' }), twin.submit({ kind: 'diagnose', diagnostic: 'paired_trace' }));
  const snapshot = game.view(); snapshot.rules.sensorShift = 999; snapshot.mechanisms[0].gate = 'maximum';
  assert.notEqual(game.view().rules.sensorShift, 999);
  assert.equal(game.view().mechanisms[0].gate, 'all');
  assert.doesNotMatch(JSON.stringify(game.view()), /privateSeed|hiddenMechanism|targetPosterior|oracle/);
  assert.deepEqual(finish(game), finish(twin));
});

test('finite private-ticket enumeration independently reproduces adaptive transcript posteriors', () => {
  const axes = { diagnostic_access: 'medium', evidence_batch: 'medium', diagnostic_budget: 'medium' };
  const count = create({ axes }).audit().privateTicketCount;
  assert.equal(count, 48);
  const transcripts = new Map();
  Array.from({ length: count }, (_, privateSeed) => privateSeed).forEach(privateSeed => {
    const game = create({ seed: 3, privateSeed, axes });
    finish(game);
    const audit = game.audit(), key = JSON.stringify(audit.history);
    const group = transcripts.get(key) ?? { counts: [0, 0, 0], expected: audit.targetPosterior };
    group.counts[['ordinary', 'selection', 'sensor'].indexOf(audit.hiddenMechanism)] += 1;
    transcripts.set(key, group);
  });
  [...transcripts.values()].forEach(group => {
    const total = group.counts.reduce((sum, value) => sum + value, 0);
    assert.deepEqual(group.expected, group.counts.map(value => String(new Ratio(value, total))));
  });
});

test('all 81 axis combinations retain the calibrated reference contract', () => {
  const settings = definition.axes.reduce((prefixes, axis) => prefixes.flatMap(prefix => Object.keys(axis.levels).map(level => ({ ...prefix, [axis.id]: level }))), [{}]);
  assert.equal(settings.length, 81);
  settings.forEach(axes => assert.equal(finish(create({ seed: 5, privateSeed: 22, axes })).metrics.score, '1', JSON.stringify(axes)));
});
