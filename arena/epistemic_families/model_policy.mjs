import { setTimeout as delay } from 'node:timers/promises';
import { Contract } from './runtime.mjs';

export const MODEL_POLICY_INSTRUCTIONS = 'You are taking an interactive reasoning evaluation. The current JSON view is your entire permitted context. Return exactly one JSON object matching its actionSchema, without commentary. Follow the rules in the view, including exact fractions where requested. Choose useful investigations within the available budget and then submit a terminal answer. Do not assume unavailable information or retain earlier views across calls.';

class ModelOutputError extends Error {
  constructor(episodeStatus, message) { super(message); this.episodeStatus = episodeStatus; }
}

export class ModelPolicy {
  constructor(profile, { apiKey, beforeRequest = ModelPolicy.nothing, afterResponse = ModelPolicy.nothing, fetchImpl = fetch } = {}) {
    ModelPolicy.validate(profile);
    if (typeof apiKey !== 'string' || apiKey.trim().length === 0) throw new Error('provider API key is required');
    if ([beforeRequest, afterResponse, fetchImpl].some(value => typeof value !== 'function')) throw new Error('provider hooks and fetch implementation must be functions');
    this.profile = structuredClone(profile);
    this.identity = { kind: 'model', provider: profile.provider, model: profile.model, apiBase: profile.apiBase, wireApi: profile.wireApi, reasoningEffort: profile.reasoningEffort, maxOutputTokens: profile.maxOutputTokens };
    this.apiKey = apiKey;
    this.beforeRequest = beforeRequest;
    this.afterResponse = afterResponse;
    this.fetchImpl = fetchImpl;
    this.lastStarted = -Infinity;
  }

  static async nothing() {}

  static validate(profile) {
    Contract.object(profile, 'provider profile');
    const endpoints = { mercury: ['https://api.inceptionlabs.ai/v1', 'chat_completions'], atria: ['https://discovery-api.intern-ai.org.cn/v1', 'responses'] };
    const endpoint = endpoints[profile.provider];
    if (!endpoint || profile.apiBase !== endpoint.at(0) || profile.wireApi !== endpoint.at(1)) throw new Error('unsupported provider endpoint or wire API');
    if (typeof profile.model !== 'string' || !profile.model.trim()) throw new Error('model is required');
    if (profile.reasoningEffort !== 'high') throw new Error('campaign reasoning effort must be high');
    Contract.integer(profile.maxOutputTokens, 1, 131072, 'output token limit');
    Contract.integer(profile.timeoutMs, 1, 600000, 'request timeout');
    Contract.integer(profile.minIntervalMs, 0, 60000, 'request interval');
  }

  static request(profile, view) {
    ModelPolicy.validate(profile);
    Contract.object(view, 'current view');
    const current = JSON.stringify(view);
    if (profile.wireApi === 'chat_completions') return {
      url: `${profile.apiBase}/chat/completions`,
      body: { model: profile.model, messages: [{ role: 'system', content: MODEL_POLICY_INSTRUCTIONS }, { role: 'user', content: current }], max_completion_tokens: profile.maxOutputTokens, reasoning_effort: profile.reasoningEffort, temperature: 1, stream: false },
    };
    return {
      url: `${profile.apiBase}/responses`,
      body: { model: profile.model, input: `${MODEL_POLICY_INSTRUCTIONS}\n\nCurrent view:\n${current}`, reasoning: { effort: profile.reasoningEffort }, max_output_tokens: profile.maxOutputTokens, stream: false },
    };
  }

  static usage(payload) {
    if (!payload?.usage || typeof payload.usage !== 'object' || Array.isArray(payload.usage)) return null;
    const inputTokens = payload.usage.input_tokens ?? payload.usage.prompt_tokens;
    const outputTokens = payload.usage.output_tokens ?? payload.usage.completion_tokens;
    const totalTokens = payload.usage.total_tokens ?? (Number.isSafeInteger(inputTokens) && Number.isSafeInteger(outputTokens) ? inputTokens + outputTokens : undefined);
    if ([inputTokens, outputTokens, totalTokens].some(value => !Number.isSafeInteger(value) || value < 0)) return null;
    return { inputTokens, outputTokens, totalTokens };
  }

  static text(profile, payload) {
    Contract.object(payload, 'provider response envelope');
    if (payload?.error) throw new Error('provider returned an error payload');
    if (profile.wireApi === 'chat_completions') {
      if (!Array.isArray(payload?.choices) || payload.choices.length !== 1) throw new Error('provider must return exactly one completion');
      const choice = Contract.object(payload.choices.at(0), 'provider completion'), message = Contract.object(choice.message, 'provider assistant message');
      if (message.role !== undefined && message.role !== 'assistant') throw new Error('provider returned an invalid assistant role');
      if (choice.finish_reason === 'length') throw new ModelOutputError('output_limit', 'provider reached the output token limit');
      if (choice.finish_reason === 'content_filter') throw new ModelOutputError('refusal', 'provider refused');
      if (choice.finish_reason === 'tool_calls' && Array.isArray(message.tool_calls) && message.tool_calls.length) throw new ModelOutputError('invalid_output', 'provider returned a tool call instead of a JSON action');
      if (choice.finish_reason !== 'stop') throw new Error('provider completion was not finished normally');
      if (typeof message.refusal === 'string' && message.refusal.trim()) throw new ModelOutputError('refusal', 'provider refused');
      if (Array.isArray(message.tool_calls) && message.tool_calls.length) throw new ModelOutputError('invalid_output', 'provider returned a tool call instead of a JSON action');
      if (typeof message.content === 'string') return message.content;
      if (Array.isArray(message.content) && message.content.every(part => part.type === 'text' && typeof part.text === 'string')) return message.content.map(part => part.text).join('');
      if (message.content === null) throw new ModelOutputError('invalid_output', 'provider returned no assistant text');
      throw new Error('provider returned invalid assistant content');
    }
    if (!Array.isArray(payload.output) && typeof payload.output_text !== 'string') throw new Error('provider returned invalid output envelope');
    if (payload.status === 'incomplete' && payload.incomplete_details?.reason === 'max_output_tokens') throw new ModelOutputError('output_limit', 'provider reached the output token limit');
    if (payload.status === 'incomplete' && payload.incomplete_details?.reason === 'content_filter') throw new ModelOutputError('refusal', 'provider refused');
    if (payload?.status !== undefined && payload.status !== 'completed' || payload?.incomplete_details) throw new Error('provider response is incomplete');
    if (Array.isArray(payload?.output)) {
      const messages = payload.output.filter(item => item.type === 'message');
      if (messages.some(item => item.role !== 'assistant' || item.status !== undefined && item.status !== 'completed')) throw new Error('provider assistant message is incomplete');
      if (messages.some(item => !Array.isArray(item.content))) throw new Error('provider returned invalid message content');
      const parts = messages.flatMap(item => item.content ?? []);
      if (parts.some(part => part.type !== 'output_text' && part.type !== 'refusal' || part.type === 'output_text' && typeof part.text !== 'string' || part.type === 'refusal' && typeof part.refusal !== 'string')) throw new Error('provider returned invalid message content');
      if (parts.some(part => part.type === 'refusal')) throw new ModelOutputError('refusal', 'provider refused');
      const text = parts.filter(part => part.type === 'output_text' && typeof part.text === 'string').map(part => part.text).join('');
      if (text.trim()) return text;
    }
    if (typeof payload?.output_text === 'string' && payload.output_text.trim()) return payload.output_text;
    throw new ModelOutputError('invalid_output', 'provider returned no assistant text');
  }

  static decode(profile, transport) {
    try {
      if (transport.error) throw new Error('provider request failed');
      if (!Number.isInteger(transport.httpStatus) || transport.httpStatus < 200 || transport.httpStatus >= 300) throw new Error(`provider HTTP ${transport.httpStatus}`);
      let payload;
      try { payload = JSON.parse(transport.raw); } catch { throw new Error('provider returned invalid response JSON'); }
      const text = ModelPolicy.text(profile, payload).trim();
      const fenced = text.match(/^```(?:json)?\s*\n([\s\S]*?)\n```$/i);
      let action;
      try { action = JSON.parse(fenced ? fenced.at(1) : text); } catch { throw new ModelOutputError('invalid_output', 'provider returned invalid action JSON'); }
      try { Contract.object(action, 'provider JSON action'); } catch { throw new ModelOutputError('invalid_output', 'provider action must be a JSON object'); }
      return { action, transport };
    } catch (error) { error.transport = transport; throw error; }
  }

  redact(value) { return String(value).split(this.apiKey).join('[REDACTED]'); }

  async act(view) {
    const request = ModelPolicy.request(this.profile, view);
    const remaining = this.profile.minIntervalMs - (performance.now() - this.lastStarted);
    if (remaining > 0) await delay(remaining);
    await this.beforeRequest(structuredClone(request));
    this.lastStarted = performance.now();
    let transport;
    try {
      const response = await this.fetchImpl(request.url, {
        method: 'POST', headers: { Authorization: `Bearer ${this.apiKey}`, 'Content-Type': 'application/json' }, body: JSON.stringify(request.body), redirect: 'error', signal: AbortSignal.timeout(this.profile.timeoutMs),
      });
      const raw = this.redact(await response.text());
      let payload = null;
      try { payload = JSON.parse(raw); } catch {}
      transport = { httpStatus: response.status, raw, usage: ModelPolicy.usage(payload), error: null };
    } catch (error) {
      transport = { httpStatus: null, raw: '', usage: null, error: this.redact(error.message ?? 'provider transport failure') };
    }
    await this.afterResponse(structuredClone(transport));
    return ModelPolicy.decode(this.profile, transport);
  }
}
