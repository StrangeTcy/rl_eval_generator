import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { Campaign } from '../../tools/epistemic_family_campaign.mjs';
import { Catalog, FAMILY_IDS, ROOT } from '../../arena/epistemic_families/catalog.mjs';
import { Contract } from '../../arena/epistemic_families/runtime.mjs';
import { ModelPolicy } from '../../arena/epistemic_families/model_policy.mjs';

class Fixture {
  static create(changes = {}) {
    const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'epistemic-campaign-'));
    const profile = { ...Campaign.profile(path.join(ROOT, 'experiments/epistemic_mercury_campaign.yaml')), minIntervalMs: 0, matrixMode: 'configured', ...changes };
    const profileFile = path.join(parent, 'profile.yaml');
    fs.writeFileSync(profileFile, JSON.stringify(profile));
    return { parent, profile, profileFile, directory: path.join(parent, 'campaign') };
  }
  static factory(counter, responseMode = 'reference') {
    return async (profile, hooks) => new ModelPolicy(profile, { ...hooks, fetchImpl: async (url, request) => {
      counter.requests++;
      const body = JSON.parse(request.body), view = JSON.parse(body.messages.at(1).content);
      counter.views.push(view);
      assert.equal(body.messages.length, 2);
      const action = responseMode === 'invalid' ? { kind: 'not_an_action' } : (await Catalog.load(view.family)).reference(view);
      return { status: responseMode === 'http_error' ? 503 : 200, text: async () => JSON.stringify({ choices: [{ finish_reason: 'stop', message: { role: 'assistant', content: JSON.stringify(action) } }], usage: { prompt_tokens: 5, completion_tokens: 3, total_tokens: 8 } }) };
    } });
  }
}

test('campaign plans cover every real axis and repeated attempts retain identical instances', async () => {
  const fixture = Fixture.create({ matrixMode: 'pairwise', attempts: 2 });
  const summary = await Campaign.plan(fixture.profileFile, fixture.directory, { executionMode: 'live', maxRequests: 512 });
  const manifest = Campaign.unseal(path.join(fixture.directory, 'campaign.json'));
  assert.deepEqual(manifest.selection.families, FAMILY_IDS);
  assert.ok(manifest.coverage.every(item => item.complete));
  assert.ok(manifest.coverage.every(item => item.vectors > 1));
  assert.equal(summary.requests, 0);
  assert.equal(summary.executionMode, null);
  assert.equal(summary.selectedRequestCeiling, 512);
  assert.equal(summary.estimates.maximumAuthorizedOutputTokens, 512 * fixture.profile.maxOutputTokens);
  const twin = manifest.cases.find(row => row.family === manifest.cases.at(0).family && row.vector === 0 && row.attempt === 1);
  assert.deepEqual(twin.configuration, manifest.cases.at(0).configuration);
  assert.equal(manifest.estimates.maximumRequests, manifest.cases.length * fixture.profile.maxTurns);
});

test('all nine configured references run, checkpoint, resume without overwriting episodes, and verify', async () => {
  const fixture = Fixture.create();
  await Campaign.plan(fixture.profileFile, fixture.directory, { executionMode: 'live' });
  const first = await Campaign.run(fixture.profileFile, fixture.directory, { executionMode: 'reference', maxEpisodes: 4 });
  assert.equal(first.status, 'paused');
  assert.equal(first.reason, 'episode_slice');
  assert.equal(first.recorded, 4);
  const preserved = path.join(fixture.directory, 'episodes', 'agent_reconstruction-0-0', 'record.json');
  const bytes = fs.readFileSync(preserved);
  const second = await Campaign.run(fixture.profileFile, fixture.directory, { executionMode: 'reference', maxEpisodes: 100 });
  assert.equal(second.status, 'completed');
  assert.equal(second.recorded, 9);
  assert.equal(second.requests, 0);
  assert.deepEqual(fs.readFileSync(preserved), bytes);
  assert.ok(second.families.every(row => row.outcomes.at(0).status === 'completed'));
  assert.equal((await Campaign.verify(fixture.profileFile, fixture.directory)).episodes, 9);
});

test('live campaign reserves calls, retains raw responses and reference control, and never repeats completed work', async () => {
  const fixture = Fixture.create({ families: ['memory_inquiry'] });
  const counter = { requests: 0, views: [] };
  const dependencies = { apiKey: 'test-credential', policyFactory: Fixture.factory(counter) };
  const options = { executionMode: 'live', maxRequests: 32 };
  const summary = await Campaign.run(fixture.profileFile, fixture.directory, options, dependencies);
  assert.equal(summary.status, 'completed');
  assert.ok(counter.requests > 1);
  assert.equal(summary.requests, counter.requests);
  assert.equal(summary.reportedUsage.totalTokens, counter.requests * 8);
  assert.equal(summary.requestsWithoutUsage, 0);
  assert.equal(counter.views.at(0).phase, 'exposure');
  assert.ok(counter.views.slice(1).every(view => view.exposure.length === 0));
  const inspected = await Campaign.inspect(fixture.directory, fixture.profileFile);
  assert.ok(inspected.requests.every(row => row.response.transport.raw.includes('choices')));
  assert.equal(inspected.records.at(0).record.policy.kind, 'model');
  const before = counter.requests;
  await Campaign.run(fixture.profileFile, fixture.directory, options, dependencies);
  assert.equal(counter.requests, before);
  assert.equal((await Campaign.verify(fixture.profileFile, fixture.directory)).status, 'passed');
});

test('insufficient request allowance pauses before HTTP and a saved bound cannot increase on resume', async () => {
  const fixture = Fixture.create({ families: ['memory_inquiry'] });
  const counter = { requests: 0, views: [] }, dependencies = { apiKey: 'test', policyFactory: Fixture.factory(counter) };
  const summary = await Campaign.run(fixture.profileFile, fixture.directory, { executionMode: 'live', maxRequests: 1 }, dependencies);
  assert.equal(summary.reason, 'request_budget');
  assert.equal(counter.requests, 0);
  assert.equal((await Campaign.verify(fixture.profileFile, fixture.directory)).status, 'passed');
  await assert.rejects(Campaign.run(fixture.profileFile, fixture.directory, { executionMode: 'live', maxRequests: 32 }, dependencies), /saved execution mode or request ceiling/);
  await assert.rejects(Campaign.run(fixture.profileFile, fixture.directory, { executionMode: 'reference', maxRequests: 1 }, dependencies), /saved execution mode or request ceiling/);
});

test('transport failure is recorded and replayed, and later resume never retries it', async () => {
  const fixture = Fixture.create({ families: ['memory_inquiry'] });
  const counter = { requests: 0, views: [] }, dependencies = { apiKey: 'test', policyFactory: Fixture.factory(counter, 'http_error') };
  const options = { executionMode: 'live', maxRequests: 32 };
  const summary = await Campaign.run(fixture.profileFile, fixture.directory, options, dependencies);
  assert.equal(summary.status, 'failed');
  assert.equal(summary.recorded, 1);
  assert.equal(summary.families.at(0).outcomes.at(0).status, 'policy_failure');
  assert.equal((await Campaign.verify(fixture.profileFile, fixture.directory)).status, 'passed');
  await Campaign.run(fixture.profileFile, fixture.directory, options, dependencies);
  assert.equal(counter.requests, 1);
});

test('invalid model action is an observed outcome and is never retried', async () => {
  const fixture = Fixture.create({ families: ['memory_inquiry'], attempts: 2 });
  const counter = { requests: 0, views: [] }, dependencies = { apiKey: 'test', policyFactory: Fixture.factory(counter, 'invalid') };
  const options = { executionMode: 'live', maxRequests: 64 };
  const summary = await Campaign.run(fixture.profileFile, fixture.directory, options, dependencies);
  assert.equal(summary.status, 'completed');
  assert.equal(summary.recorded, 2);
  assert.ok(summary.families.at(0).outcomes.every(row => row.status === 'invalid_action'));
  await Campaign.run(fixture.profileFile, fixture.directory, options, dependencies);
  assert.equal(counter.requests, 2);
});

test('unknown in-flight request survives inspection and blocks automatic paid resume', async () => {
  const fixture = Fixture.create({ families: ['memory_inquiry'] });
  const { identity, manifest } = await Campaign.prepare(fixture.profileFile, fixture.directory);
  const row = manifest.cases.at(0);
  Campaign.seal(path.join(fixture.directory, 'state.json'), { identity, executionMode: 'live', maxRequests: 32, halt: null, requestCount: 1, recorded: [], activeCaseId: row.id });
  fs.mkdirSync(path.join(fixture.directory, 'episodes', row.id));
  Campaign.seal(path.join(fixture.directory, 'requests', '00000001.request.json'), { sequence: 1, identity, caseId: row.id, request: { url: 'recorded-request' } });
  const counter = { requests: 0, views: [] };
  await assert.rejects(Campaign.run(fixture.profileFile, fixture.directory, { executionMode: 'live', maxRequests: 32 }, { apiKey: 'test', policyFactory: Fixture.factory(counter) }), /unfinished episode or HTTP request/);
  assert.equal(counter.requests, 0);
  await assert.rejects(Campaign.verify(fixture.profileFile, fixture.directory), /unfinished episode or HTTP request/);
  assert.equal((await Campaign.inspect(fixture.directory)).requests.length, 1);
});

test('corrupt episode evidence and changed profile are rejected before resuming', async () => {
  const fixture = Fixture.create({ families: ['memory_inquiry'] });
  await Campaign.run(fixture.profileFile, fixture.directory);
  const recordFile = path.join(fixture.directory, 'episodes', 'memory_inquiry-0-0', 'record.json');
  const envelope = JSON.parse(fs.readFileSync(recordFile));
  envelope.value.record.configuration.seed++;
  fs.writeFileSync(recordFile, JSON.stringify(envelope));
  await assert.rejects(Campaign.verify(fixture.profileFile, fixture.directory), /checksum/);
  envelope.sha256 = Contract.hash(envelope.value);
  fs.writeFileSync(recordFile, JSON.stringify(envelope));
  await assert.rejects(Campaign.verify(fixture.profileFile, fixture.directory), /episode identity/);
  fs.writeFileSync(fixture.profileFile, JSON.stringify({ ...fixture.profile, maxOutputTokens: 1 }));
  await assert.rejects(Campaign.run(fixture.profileFile, fixture.directory), /plan, profile, configuration, or source changed/);
});

test('profile and CLI reject ambiguous YAML, invalid bounds, unknown selectors and duplicate flags', async () => {
  const fixture = Fixture.create();
  assert.throws(() => Campaign.options({ matrix: 'all' }), /matrix/);
  assert.throws(() => Campaign.options({ maxRequests: 0 }), /request ceiling/);
  await assert.rejects(Campaign.cli(['plan', '--profile', fixture.profileFile, '--profile', fixture.profileFile]), /repeated option/);
  await assert.rejects(Campaign.cli(['verify', '--profile', fixture.profileFile, '--output', fixture.directory, '--family', 'all']), /no overrides/);
  fs.writeFileSync(fixture.profileFile, 'schema: one\nschema: two\n');
  assert.throws(() => Campaign.profile(fixture.profileFile), /invalid campaign YAML/);
});

test('lost completed episode evidence blocks resume before any repeated provider request', async () => {
  const fixture = Fixture.create({ families: ['memory_inquiry'] });
  const counter = { requests: 0, views: [] }, dependencies = { apiKey: 'test', policyFactory: Fixture.factory(counter) };
  const options = { executionMode: 'live', maxRequests: 32 };
  await Campaign.run(fixture.profileFile, fixture.directory, options, dependencies);
  const before = counter.requests;
  fs.unlinkSync(path.join(fixture.directory, 'episodes', 'memory_inquiry-0-0', 'record.json'));
  await assert.rejects(Campaign.run(fixture.profileFile, fixture.directory, options, dependencies), /episode evidence regressed/);
  assert.equal(counter.requests, before);
});

test('a deleted request ledger entry cannot reset the durable request count', async () => {
  const fixture = Fixture.create({ families: ['memory_inquiry'] });
  const counter = { requests: 0, views: [] }, dependencies = { apiKey: 'test', policyFactory: Fixture.factory(counter, 'invalid') };
  const options = { executionMode: 'live', maxRequests: 32 };
  await Campaign.run(fixture.profileFile, fixture.directory, options, dependencies);
  fs.unlinkSync(path.join(fixture.directory, 'requests', '00000001.request.json'));
  fs.unlinkSync(path.join(fixture.directory, 'requests', '00000001.response.json'));
  await assert.rejects(Campaign.run(fixture.profileFile, fixture.directory, options, dependencies), /request evidence regressed/);
  assert.equal(counter.requests, 1);
});

test('resealed transport corruption is rejected against the recorded episode', async () => {
  const fixture = Fixture.create({ families: ['memory_inquiry'] });
  const counter = { requests: 0, views: [] }, dependencies = { apiKey: 'test', policyFactory: Fixture.factory(counter) };
  await Campaign.run(fixture.profileFile, fixture.directory, { executionMode: 'live', maxRequests: 32 }, dependencies);
  const file = path.join(fixture.directory, 'requests', '00000001.response.json');
  const response = Campaign.unseal(file);
  response.transport.raw = '{}';
  Campaign.seal(file, response);
  await assert.rejects(Campaign.verify(fixture.profileFile, fixture.directory), /transport mismatch/);
});

test('a durable failure record recovers its stop when the final checkpoint write was interrupted', async () => {
  const fixture = Fixture.create({ families: ['memory_inquiry'] });
  const counter = { requests: 0, views: [] }, dependencies = { apiKey: 'test', policyFactory: Fixture.factory(counter, 'http_error') };
  const options = { executionMode: 'live', maxRequests: 32 };
  await Campaign.run(fixture.profileFile, fixture.directory, options, dependencies);
  const file = path.join(fixture.directory, 'state.json'), state = Campaign.unseal(file);
  state.recorded = [];
  state.activeCaseId = 'memory_inquiry-0-0';
  state.halt = null;
  Campaign.seal(file, state);
  const resumed = await Campaign.run(fixture.profileFile, fixture.directory, options, dependencies);
  assert.equal(resumed.status, 'failed');
  assert.equal(counter.requests, 1);
  assert.match(Campaign.unseal(file).halt, /policy failure/);
});
