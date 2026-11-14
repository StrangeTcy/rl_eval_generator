import test from 'node:test';
import assert from 'node:assert/strict';
import { Catalog, FAMILY_IDS } from '../../arena/epistemic_families/catalog.mjs';
import { Session } from '../../arena/epistemic_families/session.mjs';
import { ReferenceControl, REFERENCE_REQUIREMENTS } from '../../arena/epistemic_families/reference_control.mjs';
import { Campaign } from '../../tools/epistemic_family_campaign.mjs';

test('all family references satisfy mathematical controls at combined axis boundaries', async () => {
  await FAMILY_IDS.reduce(async (previous, family) => {
    await previous;
    const { definition } = await Catalog.load(family);
    await ['easy', 'medium', 'hard'].reduce(async (prior, level) => {
      await prior;
      const record = await Session.run(family, { axes: Object.fromEntries(definition.axes.map(axis => [axis.id, level])) });
      assert.equal(ReferenceControl.check(record).status, 'passed');
      assert.equal((await Session.replay(record)).status, 'passed');
    }, Promise.resolve());
  }, Promise.resolve());
});

test('every required metric rejects incorrect, absent, and nonfinite measurements', async () => {
  await Promise.all(FAMILY_IDS.map(async family => {
    const record = await Session.run(family), requirement = REFERENCE_REQUIREMENTS[family];
    Object.entries(requirement.exact ?? {}).forEach(([key, expected]) => {
      ['1/2', undefined, 'NaN', Number(expected)].forEach(value => {
        const changed = structuredClone(record);
        changed.terminal.metrics[key] = value;
        assert.throws(() => ReferenceControl.check(changed), new RegExp(`${family}\\.${key}`));
      });
    });
    Object.entries(requirement.numeric ?? {}).forEach(([key, expected]) => {
      [expected + 1e-6, undefined, NaN, Infinity, String(expected)].forEach(value => {
        const changed = structuredClone(record);
        changed.terminal.metrics[key] = value;
        assert.throws(() => ReferenceControl.check(changed), new RegExp(`${family}\\.${key}`));
      });
    });
    assert.throws(() => ReferenceControl.check({ ...record, status: 'turn_limit' }), /did not complete/);
  }));
});

test('legitimate posterior uncertainty and realized loss are not reference failures', async () => {
  const memory = await Session.run('memory_inquiry', { axes: { events: 'hard', retention: 'hard', retrievals: 'hard', task: 'hard' } });
  assert.notEqual(memory.terminal.metrics.irreducibleRisk, '0');
  assert.equal(ReferenceControl.check(memory).status, 'passed');
  const discovery = await Session.run('hypothesis_discovery', { axes: { degree: 'hard', observable_domain: 'hard', experiment_budget: 'hard' } });
  assert.notEqual(discovery.terminal.metrics.score, '1');
  assert.equal(ReferenceControl.check(discovery).status, 'passed');
});

test('a completed and replayable overconfident policy fails the memory control', async () => {
  const record = await Session.run('memory_inquiry', { axes: { events: 'hard', retention: 'hard', retrievals: 'hard', task: 'hard' } }, 'overconfident');
  assert.equal((await Session.replay(record)).status, 'passed');
  assert.throws(() => ReferenceControl.check({ ...record, policy: 'reference' }), /memory_inquiry.forecastExcess/);
});

test('numeric tolerance and subset counts are checked against the recorded conclusions', async () => {
  const record = await Session.run('belief_revision');
  record.terminal.metrics.forecastExcess = 5e-13;
  assert.equal(ReferenceControl.check(record).status, 'passed');
  ['changedConclusionCount', 'retainedSupportedCount'].forEach(key => {
    const changed = structuredClone(record);
    assert.ok(changed.terminal.metrics[key] > 0);
    changed.terminal.metrics[key] = 0;
    assert.throws(() => ReferenceControl.check(changed), new RegExp(key));
  });
  const evaluator = await Session.run('evaluator_prediction', { axes: { revisions: 'hard' } });
  assert.ok(evaluator.events.some(event => event.action.kind === 'revise'));
  evaluator.terminal.metrics.revisionsUsed = 0;
  evaluator.terminal.metrics.revisionForecastCount = 0;
  assert.throws(() => ReferenceControl.check(evaluator), /revisionForecastCount/);
});

test('campaign provenance includes the mathematical reference contract', () => {
  assert.match(Campaign.sources(FAMILY_IDS)['arena/epistemic_families/reference_control.mjs'], /^[a-f0-9]{64}$/);
});
