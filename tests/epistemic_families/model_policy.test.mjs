import test from 'node:test';
import assert from 'node:assert/strict';
import { ModelPolicy, MODEL_POLICY_INSTRUCTIONS } from '../../arena/epistemic_families/model_policy.mjs';
import { Catalog } from '../../arena/epistemic_families/catalog.mjs';
import { Session } from '../../arena/epistemic_families/session.mjs';

class Fixture {
  static profile(provider = 'mercury') {
    return { provider, apiBase: provider === 'mercury' ? 'https://api.inceptionlabs.ai/v1' : 'https://discovery-api.intern-ai.org.cn/v1', model: provider === 'mercury' ? 'mercury-3' : 'Atria-Dawn-Preview', wireApi: provider === 'mercury' ? 'chat_completions' : 'responses', reasoningEffort: 'high', maxOutputTokens: 8192, timeoutMs: 30000, minIntervalMs: 0 };
  }
  static response(provider, action) {
    return provider === 'mercury'
      ? { choices: [{ finish_reason: 'stop', message: { role: 'assistant', content: JSON.stringify(action) } }], usage: { prompt_tokens: 31, completion_tokens: 17, total_tokens: 48 } }
      : { status: 'completed', output: [{ type: 'reasoning', summary: [{ type: 'summary_text', text: 'private reasoning is not an action' }] }, { type: 'message', role: 'assistant', status: 'completed', content: [{ type: 'output_text', text: JSON.stringify(action) }] }], usage: { input_tokens: 31, output_tokens: 17, total_tokens: 48 } };
  }
  static transport(payload, httpStatus = 200) { return { httpStatus, raw: JSON.stringify(payload), usage: ModelPolicy.usage(payload), error: null }; }
  static current(provider, body) { return provider === 'mercury' ? JSON.parse(body.messages.at(1).content) : JSON.parse(body.input.split('\n\nCurrent view:\n').at(1)); }
}

test('Mercury 3 uses high-effort Chat Completions with its supported default temperature', () => {
  const view = { family: 'memory_inquiry', phase: 'recall', retained: [], actionSchema: {} };
  const request = ModelPolicy.request(Fixture.profile(), view);
  assert.equal(request.url, 'https://api.inceptionlabs.ai/v1/chat/completions');
  assert.deepEqual(request.body, { model: 'mercury-3', messages: [{ role: 'system', content: MODEL_POLICY_INSTRUCTIONS }, { role: 'user', content: JSON.stringify(view) }], max_completion_tokens: 8192, reasoning_effort: 'high', temperature: 1, stream: false });
});

test('Atria uses the token-plan Responses endpoint and only the current view', () => {
  const view = { family: 'memory_inquiry', phase: 'recall', retained: [], actionSchema: {} };
  const request = ModelPolicy.request(Fixture.profile('atria'), view);
  assert.equal(request.url, 'https://discovery-api.intern-ai.org.cn/v1/responses');
  assert.deepEqual(request.body, { model: 'Atria-Dawn-Preview', input: `${MODEL_POLICY_INSTRUCTIONS}\n\nCurrent view:\n${JSON.stringify(view)}`, reasoning: { effort: 'high' }, max_output_tokens: 8192, stream: false });
  assert.equal(Object.hasOwn(request.body, 'previous_response_id'), false);
});

test('unapproved endpoint and cross-wired provider profiles fail before transport', () => {
  assert.throws(() => new ModelPolicy({ ...Fixture.profile('atria'), apiBase: 'https://api.atria-asi.ai/v1' }, { apiKey: 'secret' }), /unsupported/);
  assert.throws(() => new ModelPolicy({ ...Fixture.profile(), wireApi: 'responses' }, { apiKey: 'secret' }), /unsupported/);
  assert.throws(() => new ModelPolicy(Fixture.profile(), { apiKey: '' }), /key/);
});

test('request reservation precedes transport; raw response is journaled before action decoding', async () => {
  const sequence = [], key = 'test-only-secret';
  const policy = new ModelPolicy(Fixture.profile(), {
    apiKey: key,
    beforeRequest: async request => { sequence.push('reserve'); assert.equal(JSON.stringify(request).includes(key), false); },
    fetchImpl: async (url, options) => {
      sequence.push('fetch'); assert.equal(options.headers.Authorization, `Bearer ${key}`); assert.equal(options.redirect, 'error'); assert.ok(options.signal);
      return new Response(JSON.stringify(Fixture.response('mercury', { kind: 'advance' })), { status: 200 });
    },
    afterResponse: async transport => { sequence.push('persist'); assert.equal(transport.httpStatus, 200); assert.deepEqual(transport.usage, { inputTokens: 31, outputTokens: 17, totalTokens: 48 }); },
  });
  const result = await policy.act({ phase: 'exposure' });
  assert.deepEqual(result.action, { kind: 'advance' });
  assert.deepEqual(sequence, ['reserve', 'fetch', 'persist']);
});

test('a rejected budget reservation makes no HTTP attempt and no response entry', async () => {
  let calls = 0, responses = 0;
  const policy = new ModelPolicy(Fixture.profile(), { apiKey: 'secret', beforeRequest: async () => { throw new Error('budget exhausted'); }, fetchImpl: async () => { calls++; }, afterResponse: async () => { responses++; } });
  await assert.rejects(policy.act({}), /budget exhausted/);
  assert.equal(calls, 0); assert.equal(responses, 0);
});

test('network errors are persisted once, redacted, and never retried', async () => {
  let calls = 0;
  const responses = [], key = 'sensitive-token';
  const policy = new ModelPolicy(Fixture.profile(), { apiKey: key, fetchImpl: async () => { calls++; throw new Error(`failed with ${key}`); }, afterResponse: async value => { responses.push(value); } });
  await assert.rejects(policy.act({}), error => {
    assert.equal(error.transport.httpStatus, null);
    assert.equal(error.transport.error, 'failed with [REDACTED]');
    assert.equal(JSON.stringify(error.transport).includes(key), false);
    return error.message === 'provider request failed';
  });
  assert.equal(calls, 1); assert.equal(responses.length, 1);
});

test('HTTP failure retains sanitized raw evidence without exposing the token', async () => {
  const key = 'sensitive-token', persisted = [];
  const policy = new ModelPolicy(Fixture.profile(), { apiKey: key, fetchImpl: async () => new Response(`denied ${key}`, { status: 401 }), afterResponse: async value => { persisted.push(value); } });
  await assert.rejects(policy.act({}), error => { assert.equal(error.transport.raw, 'denied [REDACTED]'); return error.message === 'provider HTTP 401'; });
  assert.equal(persisted.length, 1);
});

test('invalid action output is persisted before decoding fails', async () => {
  const persisted = [], payload = Fixture.response('mercury', {});
  payload.choices.at(0).message.content = 'not JSON';
  const policy = new ModelPolicy(Fixture.profile(), { apiKey: 'secret', fetchImpl: async () => new Response(JSON.stringify(payload)), afterResponse: async value => { persisted.push(value); } });
  await assert.rejects(policy.act({}), error => { assert.equal(error.transport.raw, JSON.stringify(payload)); return /invalid action JSON/.test(error.message); });
  assert.equal(persisted.length, 1);
});

test('complete fenced JSON is accepted and no reasoning item becomes an action', () => {
  const chat = Fixture.response('mercury', {});
  chat.choices.at(0).message.content = '```json\n{"kind":"advance"}\n```';
  assert.deepEqual(ModelPolicy.decode(Fixture.profile(), Fixture.transport(chat)).action, { kind: 'advance' });
  const responses = Fixture.response('atria', { kind: 'advance' });
  assert.deepEqual(ModelPolicy.decode(Fixture.profile('atria'), Fixture.transport(responses)).action, { kind: 'advance' });
  responses.output = responses.output.filter(item => item.type === 'reasoning');
  assert.throws(() => ModelPolicy.decode(Fixture.profile('atria'), Fixture.transport(responses)), /no assistant text/);
});

test('known token cutoffs and refusals are model outcomes while unknown incomplete responses remain service failures', () => {
  const chat = Fixture.response('mercury', { kind: 'advance' });
  chat.choices.at(0).finish_reason = 'length';
  chat.choices.at(0).message.content = null;
  assert.throws(() => ModelPolicy.decode(Fixture.profile(), Fixture.transport(chat)), error => error.episodeStatus === 'output_limit');
  chat.choices.at(0).finish_reason = 'stop';
  chat.choices.at(0).message.refusal = 'refused';
  assert.throws(() => ModelPolicy.decode(Fixture.profile(), Fixture.transport(chat)), error => error.episodeStatus === 'refusal');
  const responses = Fixture.response('atria', { kind: 'advance' });
  responses.status = 'incomplete';
  assert.throws(() => ModelPolicy.decode(Fixture.profile('atria'), Fixture.transport(responses)), error => /incomplete/.test(error.message) && error.episodeStatus === undefined);
  responses.incomplete_details = { reason: 'max_output_tokens' };
  assert.throws(() => ModelPolicy.decode(Fixture.profile('atria'), Fixture.transport(responses)), error => error.episodeStatus === 'output_limit');
  responses.incomplete_details = null;
  responses.status = 'completed';
  responses.output.at(1).content = [{ type: 'refusal', refusal: 'refused' }];
  assert.throws(() => ModelPolicy.decode(Fixture.profile('atria'), Fixture.transport(responses)), error => error.episodeStatus === 'refusal');
});

test('malformed model actions are outcomes but malformed provider envelopes and errors still fail the service', () => {
  ['not JSON', '[]', 'null', '"text"'].forEach(content => {
    const payload = Fixture.response('mercury', {});
    payload.choices.at(0).message.content = content;
    assert.throws(() => ModelPolicy.decode(Fixture.profile(), Fixture.transport(payload)), error => error.episodeStatus === 'invalid_output');
  });
  [{}, { choices: [{ finish_reason: 'length' }] }, { error: { message: 'service failure' }, choices: [{ finish_reason: 'length', message: { content: null } }] }].forEach(payload => {
    assert.throws(() => ModelPolicy.decode(Fixture.profile(), Fixture.transport(payload)), error => error.episodeStatus === undefined);
  });
  assert.throws(() => ModelPolicy.decode(Fixture.profile(), { httpStatus: 200, raw: 'not JSON', usage: null, error: null }), error => error.episodeStatus === undefined);
  const cutoff = Fixture.response('mercury', {});
  cutoff.choices.at(0).finish_reason = 'length';
  [503, undefined, NaN, '200', null].forEach(httpStatus => {
    const transport = { ...Fixture.transport(cutoff), httpStatus };
    assert.throws(() => ModelPolicy.decode(Fixture.profile(), transport), error => error.episodeStatus === undefined);
  });
});

test('token cutoff episodes retain raw usage and replay without inventing an action or terminal metrics', async () => {
  const payload = Fixture.response('mercury', {});
  payload.choices.at(0).finish_reason = 'length';
  payload.choices.at(0).message.content = null;
  payload.usage = { prompt_tokens: 977, completion_tokens: 7913, total_tokens: 8890 };
  const policy = new ModelPolicy(Fixture.profile(), { apiKey: 'secret', fetchImpl: async () => new Response(JSON.stringify(payload)) });
  const record = await Session.run('memory_inquiry', {}, policy);
  assert.equal(record.status, 'output_limit');
  assert.equal(record.terminal, null);
  assert.equal(record.events.length, 1);
  assert.equal(Object.hasOwn(record.events.at(0), 'action'), false);
  assert.equal(record.events.at(0).outcome, 'output_limit');
  assert.deepEqual(record.events.at(0).transport.usage, { inputTokens: 977, outputTokens: 7913, totalTokens: 8890 });
  assert.equal(record.events.at(0).transport.raw, JSON.stringify(payload));
  assert.equal((await Session.replay(record)).episodeStatus, 'output_limit');
  record.status = 'invalid_output';
  await assert.rejects(Session.replay(record), /outcome record/);
});

test('successful action-only traces cannot be relabeled as output cutoffs', async () => {
  const record = await Session.run('memory_inquiry', {}, 'reference', { maxTurns: 1 });
  assert.equal(record.status, 'turn_limit');
  assert.equal((await Session.replay(record)).episodeStatus, 'turn_limit');
  record.status = 'output_limit';
  record.failure = 'provider reached the output token limit';
  await assert.rejects(Session.replay(record), /episode outcome mismatch/);
});

test('missing or malformed usage remains unknown rather than being recorded as zero', () => {
  assert.equal(ModelPolicy.usage({}), null);
  assert.equal(ModelPolicy.usage({ usage: { total_tokens: 12 } }), null);
  assert.equal(ModelPolicy.usage({ usage: { input_tokens: -1, output_tokens: 2 } }), null);
  assert.deepEqual(ModelPolicy.usage({ usage: { input_tokens: 5, output_tokens: 7 } }), { inputTokens: 5, outputTokens: 7, totalTokens: 12 });
});

test('both model dialects complete and replay memory episodes using only each permitted view', async () => {
  const module = await Catalog.load('memory_inquiry');
  await ['mercury', 'atria'].reduce(async (previous, provider) => {
    await previous;
    const requests = [], policy = new ModelPolicy(Fixture.profile(provider), { apiKey: 'never-saved', fetchImpl: async (url, options) => {
      const body = JSON.parse(options.body), view = Fixture.current(provider, body);
      requests.push(body);
      if (view.phase === 'recall') assert.deepEqual(view.exposure, []);
      assert.equal(Object.hasOwn(view, 'privateSeed'), false);
      return new Response(JSON.stringify(Fixture.response(provider, module.reference(view))));
    } });
    const record = await Session.run('memory_inquiry', { seed: 3, privateSeed: 7, axes: { retention: 'hard' } }, policy);
    assert.equal(record.status, 'completed');
    assert.equal((await Session.replay(record)).status, 'passed');
    assert.deepEqual(record.policy, policy.identity);
    assert.equal(JSON.stringify(record).includes('never-saved'), false);
    assert.equal(requests.length, record.events.length);
    assert.ok(requests.length >= 2);
  }, Promise.resolve());
});

test('Session keeps provider failure evidence and replays the failed episode', async () => {
  const policy = new ModelPolicy(Fixture.profile(), { apiKey: 'secret', fetchImpl: async () => new Response('provider unavailable', { status: 503 }) });
  const record = await Session.run('memory_inquiry', {}, policy);
  assert.equal(record.status, 'policy_failure');
  assert.equal(record.events.at(0).transport.httpStatus, 503);
  assert.equal(record.events.at(0).transport.raw, 'provider unavailable');
  assert.equal((await Session.replay(record)).status, 'passed');
});
