#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
import { parseDocument } from 'yaml';
import { Catalog, FAMILY_IDS, ROOT } from '../arena/epistemic_families/catalog.mjs';
import { Configuration } from '../arena/epistemic_families/configuration.mjs';
import { Contract, AxisMatrix } from '../arena/epistemic_families/runtime.mjs';
import { Session } from '../arena/epistemic_families/session.mjs';
import { ModelPolicy } from '../arena/epistemic_families/model_policy.mjs';

export class Campaign {
  static profile(file) {
    const doc = parseDocument(fs.readFileSync(file, 'utf8'), { version: '1.2', schema: 'core', strict: true, uniqueKeys: true });
    if (doc.errors.length || doc.warnings.length) throw new Error('invalid campaign YAML');
    const p = doc.toJS({ maxAliasCount: 0 });
    Contract.fields(p, ['schema', 'name', 'provider', 'apiBase', 'model', 'apiKeyEnv', 'wireApi', 'reasoningEffort', 'minIntervalMs', 'maxOutputTokens', 'timeoutMs', 'maxTurns', 'maxRequests', 'maxEpisodesPerRun', 'jobSeconds', 'matrixMode', 'families', 'attempts']);
    if (p.schema !== 'epistemic-family-campaign/1') throw new Error('unsupported campaign schema');
    if (!/^[a-z][a-z0-9_-]+$/.test(p.name)) throw new Error('invalid campaign name');
    const mercury = p.provider === 'mercury' && p.apiBase === 'https://api.inceptionlabs.ai/v1' && p.model === 'mercury-3' && p.apiKeyEnv === 'INCEPTION_API_KEY' && p.wireApi === 'chat_completions';
    const atria = p.provider === 'atria' && p.apiBase === 'https://discovery-api.intern-ai.org.cn/v1' && p.model === 'Atria-Dawn-Preview' && p.apiKeyEnv === 'ATRIA_API_KEY' && p.wireApi === 'responses';
    if ((!mercury && !atria) || p.reasoningEffort !== 'high') throw new Error('unsupported provider profile');
    Contract.integer(p.minIntervalMs, 0, 60000, 'minimum interval');
    Contract.integer(p.maxOutputTokens, 1, 32768, 'output token limit');
    Contract.integer(p.timeoutMs, 1, 120000, 'request timeout');
    Contract.integer(p.maxTurns, 1, 128, 'turn limit');
    Contract.integer(p.maxRequests, 1, 20000, 'request ceiling');
    Contract.integer(p.maxEpisodesPerRun, 1, 1000, 'episode slice');
    Contract.integer(p.jobSeconds, 1, 18000, 'job duration');
    Contract.integer(p.attempts, 1, 10, 'attempt count');
    if (!['configured', 'single', 'pairwise'].includes(p.matrixMode)) throw new Error('invalid matrix mode');
    if (!Array.isArray(p.families) || !p.families.length || new Set(p.families).size !== p.families.length || p.families.some(id => !FAMILY_IDS.includes(id))) throw new Error('invalid campaign families');
    return p;
  }
  static options(options = {}) {
    Contract.fields(options, [], ['family', 'matrix', 'attempts', 'executionMode', 'maxEpisodes', 'maxRequests']);
    if (options.family !== undefined && options.family !== 'all' && !FAMILY_IDS.includes(options.family)) throw new Error('unknown family');
    if (options.matrix !== undefined && !['configured', 'single', 'pairwise'].includes(options.matrix)) throw new Error('invalid matrix mode');
    if (options.executionMode !== undefined && !['reference', 'live'].includes(options.executionMode)) throw new Error('invalid execution mode');
    if (options.attempts !== undefined) Contract.integer(options.attempts, 1, 10, 'attempt count');
    if (options.maxEpisodes !== undefined) Contract.integer(options.maxEpisodes, 1, 1000, 'episode slice');
    if (options.maxRequests !== undefined) Contract.integer(options.maxRequests, 1, 20000, 'request ceiling');
    return options;
  }
  static sources(families) {
    return { ...Catalog.sources(), ...Object.fromEntries(['tools/epistemic_family_campaign.mjs', 'arena/epistemic_families/model_policy.mjs', ...families.map(id => `envs/epistemic_families/${id}.yaml`)].map(name => [name, Contract.hash(fs.readFileSync(path.join(ROOT, name)))])) };
  }
  static atomic(file, value) {
    const temporary = `${file}.${randomUUID()}.tmp`, fd = fs.openSync(temporary, 'wx');
    try { fs.writeFileSync(fd, JSON.stringify(value, null, 2) + '\n'); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    fs.renameSync(temporary, file);
  }
  static seal(file, value) { this.atomic(file, { sha256: Contract.hash(value), value }); }
  static unseal(file) {
    const envelope = JSON.parse(fs.readFileSync(file, 'utf8'));
    Contract.fields(envelope, ['sha256', 'value']);
    if (Contract.hash(envelope.value) !== envelope.sha256) throw new Error(`evidence checksum mismatch: ${path.basename(file)}`);
    return envelope.value;
  }
  static async design(profile, options = {}) {
    this.options(options);
    const families = options.family && options.family !== 'all' ? [options.family] : profile.families;
    if (families.some(id => !profile.families.includes(id))) throw new Error('family outside campaign profile');
    const matrix = options.matrix ?? profile.matrixMode, attempts = options.attempts ?? profile.attempts;
    const grids = await Promise.all(families.map(async family => {
      const { configuration } = await Configuration.load(path.join(ROOT, `envs/epistemic_families/${family}.yaml`), family);
      const { definition } = await Catalog.load(family);
      const vectors = matrix === 'configured' ? [configuration.axes] : AxisMatrix.expand(definition, matrix);
      return { family, configuration, vectors, coverage: AxisMatrix.coverage(definition, vectors) };
    }));
    const cases = grids.flatMap(grid => grid.vectors.flatMap((axes, vector) => Array.from({ length: attempts }, (_, attempt) => ({ id: `${grid.family}-${vector}-${attempt}`, family: grid.family, vector, attempt, configuration: { ...grid.configuration, axes } }))));
    return { schema: 'epistemic-family-campaign-plan/1', profile, selection: { families, matrix, attempts }, runtimeMajor: process.versions.node.split('.')[0], sourceSha256: this.sources(families), cases, coverage: grids.map(grid => ({ family: grid.family, vectors: grid.vectors.length, ...grid.coverage })), estimates: { episodes: cases.length, maximumRequests: cases.length * profile.maxTurns, maximumOutputTokens: cases.length * profile.maxTurns * profile.maxOutputTokens, campaignRequestCeiling: profile.maxRequests }, inference: 'Configured coverage and repeated attempts on fixed instances; not independent structural samples or proven difficulty ordering.' };
  }
  static async prepare(profileFile, directory, options = {}) {
    const profile = this.profile(profileFile), manifest = await this.design(profile, options), identity = Contract.hash(manifest);
    if (options.maxRequests !== undefined && options.maxRequests > profile.maxRequests) throw new Error('request ceiling exceeds profile');
    fs.mkdirSync(directory, { recursive: true });
    const file = path.join(directory, 'campaign.json');
    if (fs.existsSync(file)) {
      if (Contract.hash(this.unseal(file)) !== identity) throw new Error('campaign plan, profile, configuration, or source changed');
    } else {
      if (fs.readdirSync(directory).length) throw new Error('new campaign needs an empty output directory');
      this.seal(file, manifest);
      fs.mkdirSync(path.join(directory, 'episodes'));
      fs.mkdirSync(path.join(directory, 'requests'));
      this.seal(path.join(directory, 'state.json'), { identity, executionMode: null, maxRequests: null, halt: null, requestCount: 0, recorded: [], activeCaseId: null });
    }
    return { manifest, identity };
  }
  static async inspect(directory, profileFile) {
    const manifest = this.unseal(path.join(directory, 'campaign.json')), identity = Contract.hash(manifest);
    if (profileFile && Contract.hash(this.profile(profileFile)) !== Contract.hash(manifest.profile)) throw new Error('campaign profile changed');
    if (Contract.hash(manifest.sourceSha256) !== Contract.hash(this.sources(manifest.selection.families)) || manifest.runtimeMajor !== process.versions.node.split('.')[0]) throw new Error('campaign source or Node major version changed');
    const state = this.unseal(path.join(directory, 'state.json'));
    Contract.fields(state, ['identity', 'executionMode', 'maxRequests', 'halt', 'requestCount', 'recorded', 'activeCaseId']);
    if (state.identity !== identity || ![null, 'reference', 'live'].includes(state.executionMode)) throw new Error('campaign state identity mismatch');
    if (state.executionMode !== null) Contract.integer(state.maxRequests, 1, manifest.profile.maxRequests, 'saved request ceiling');
    Contract.integer(state.requestCount, 0, state.maxRequests ?? 0, 'saved request count');
    if (!Array.isArray(state.recorded) || new Set(state.recorded.map(row => row.caseId)).size !== state.recorded.length) throw new Error('invalid recorded checkpoint');
    if (state.activeCaseId !== null && !manifest.cases.some(row => row.id === state.activeCaseId)) throw new Error('unknown active case');
    const requestNames = fs.readdirSync(path.join(directory, 'requests')).sort();
    if (requestNames.some(name => !/^\d{8}\.(request|response)\.json$/.test(name))) throw new Error('unexpected request evidence');
    const requests = requestNames.filter(name => name.endsWith('.request.json')).map((name, index) => {
      if (name !== `${String(index + 1).padStart(8, '0')}.request.json`) throw new Error('request ledger gap');
      const request = this.unseal(path.join(directory, 'requests', name));
      if (request.sequence !== index + 1 || request.identity !== identity || !manifest.cases.some(row => row.id === request.caseId)) throw new Error('request identity mismatch');
      const responseFile = path.join(directory, 'requests', name.replace('.request.', '.response.'));
      const response = fs.existsSync(responseFile) ? this.unseal(responseFile) : null;
      if (response && (response.sequence !== request.sequence || response.requestHash !== Contract.hash(request))) throw new Error('response identity mismatch');
      return { request, response };
    });
    if (requestNames.filter(name => name.endsWith('.response.json')).length !== requests.filter(row => row.response).length) throw new Error('orphan response evidence');
    if (requests.length < state.requestCount) throw new Error('request evidence regressed from checkpoint');
    if (requests.length > (state.maxRequests ?? 0) || (state.executionMode !== 'live' && requests.length)) throw new Error('request ledger exceeds saved authority');
    const names = fs.readdirSync(path.join(directory, 'episodes'));
    if (names.some(name => !manifest.cases.some(row => row.id === name))) throw new Error('unknown episode evidence');
    if (requests.some(row => !names.includes(row.request.caseId))) throw new Error('missing episode evidence for recorded request');
    const records = await Promise.all(names.map(async name => {
      const row = manifest.cases.find(item => item.id === name), file = path.join(directory, 'episodes', name, 'record.json');
      if (!fs.existsSync(file)) return { caseId: name, incomplete: true };
      const saved = this.unseal(file);
      if (saved.identity !== identity || saved.caseId !== name || saved.record.family !== row.family || Contract.hash(saved.record.configuration) !== Contract.hash(row.configuration)) throw new Error('episode identity mismatch');
      const replay = await Session.replay(saved.record);
      if (Contract.hash(replay) !== Contract.hash(saved.replay)) throw new Error('saved replay mismatch');
      if (state.executionMode === 'live') {
        const control = this.unseal(path.join(directory, 'episodes', name, 'control.json'));
        if (control.family !== row.family || Contract.hash(control.configuration) !== Contract.hash(row.configuration) || control.status !== 'completed') throw new Error('reference control mismatch');
        await Session.replay(control);
        const expectedPolicy = { kind: 'model', provider: manifest.profile.provider, model: manifest.profile.model, apiBase: manifest.profile.apiBase, wireApi: manifest.profile.wireApi, reasoningEffort: manifest.profile.reasoningEffort, maxOutputTokens: manifest.profile.maxOutputTokens };
        if (Contract.hash(saved.record.policy) !== Contract.hash(expectedPolicy)) throw new Error('episode provider identity mismatch');
        const ledger = requests.filter(item => item.request.caseId === name), events = saved.record.events.filter(event => event.transport !== null);
        if (ledger.length !== events.length) throw new Error('episode request evidence count mismatch');
        events.forEach((event, index) => {
          const item = ledger.at(index);
          if (!item.response || Contract.hash(item.request.request) !== Contract.hash(ModelPolicy.request(manifest.profile, event.view)) || Contract.hash(item.response.transport) !== Contract.hash(event.transport)) throw new Error('episode request or transport mismatch');
          let decoded, failure = null;
          try { decoded = ModelPolicy.decode(manifest.profile, item.response.transport); } catch (error) { failure = error.message; }
          if (Object.hasOwn(event, 'action')) {
            if (failure || Contract.hash(decoded.action) !== Contract.hash(event.action)) throw new Error('recorded action differs from provider response');
          } else if (failure !== event.failure) throw new Error('recorded provider failure mismatch');
        });
      } else if (state.executionMode !== 'reference' || saved.record.policy !== 'reference') throw new Error('episode execution mode mismatch');
      return saved;
    }));
    if (state.recorded.some(checkpoint => !records.some(row => !row.incomplete && row.caseId === checkpoint.caseId && Contract.hash(row) === checkpoint.sha256))) throw new Error('episode evidence regressed from checkpoint');
    if (records.some(row => !row.incomplete && !state.recorded.some(checkpoint => checkpoint.caseId === row.caseId) && row.caseId !== state.activeCaseId)) throw new Error('untracked episode evidence');
    if (state.activeCaseId !== null && !records.some(row => row.caseId === state.activeCaseId)) records.push({ caseId: state.activeCaseId, incomplete: true });
    return { manifest, identity, state, requests, records };
  }
  static summary(directory, inspected, status = 'paused', reason = null, selectedRequestCeiling) {
    const { manifest, state, records, requests, identity } = inspected;
    const completed = records.filter(row => !row.incomplete), unknownRequests = requests.filter(row => row.response === null).length;
    const reportedUsage = requests.filter(row => row.response?.transport.usage !== null && row.response?.transport.usage !== undefined);
    const ceiling = state.maxRequests ?? selectedRequestCeiling ?? manifest.profile.maxRequests;
    const summary = { schema: 'epistemic-family-campaign-summary/1', identity, name: manifest.profile.name, status, reason, executionMode: state.executionMode, planned: manifest.cases.length, recorded: completed.length, remaining: manifest.cases.length - completed.length, requests: requests.length, unknownRequests, maxRequests: state.maxRequests, selectedRequestCeiling: ceiling, reportedUsage: { requests: reportedUsage.length, inputTokens: reportedUsage.reduce((sum, row) => sum + row.response.transport.usage.inputTokens, 0), outputTokens: reportedUsage.reduce((sum, row) => sum + row.response.transport.usage.outputTokens, 0), totalTokens: reportedUsage.reduce((sum, row) => sum + row.response.transport.usage.totalTokens, 0) }, requestsWithoutUsage: requests.length - reportedUsage.length, families: manifest.selection.families.map(family => ({ family, planned: manifest.cases.filter(row => row.family === family).length, outcomes: completed.filter(row => row.record.family === family).map(row => ({ caseId: row.caseId, status: row.record.status, failure: row.record.failure, metrics: row.record.terminal?.metrics ?? null })) })), estimates: { ...manifest.estimates, maximumAuthorizedOutputTokens: ceiling * manifest.profile.maxOutputTokens } };
    this.atomic(path.join(directory, 'summary.json'), summary);
    fs.writeFileSync(path.join(directory, 'report.md'), `# ${manifest.profile.name}\n\nStatus: ${status}${reason ? ` (${reason})` : ''}. Recorded ${summary.recorded}/${summary.planned} episodes.\n\nExecution: ${state.executionMode ?? 'plan only'}. HTTP requests: ${requests.length}/${ceiling}; requests without reported usage: ${summary.requestsWithoutUsage}; unknown responses: ${unknownRequests}.\n\nFull-plan maximum requests: ${manifest.estimates.maximumRequests}. Selected ceiling allows at most ${summary.estimates.maximumAuthorizedOutputTokens} output tokens; input tokens are separate.\n\nPer-family outcomes and separate metric channels are saved in summary.json. Repeated attempts use the same configured instance. Raw requests contain only the current public view.\n`);
    return summary;
  }
  static async plan(profileFile, directory, options = {}) {
    await this.prepare(profileFile, directory, options);
    const inspected = await this.inspect(directory, profileFile);
    return this.summary(directory, inspected, 'planned', null, options.maxRequests);
  }
  static async verify(profileFile, directory) {
    const inspected = await this.inspect(directory, profileFile);
    if (inspected.requests.some(row => !row.response) || inspected.records.some(row => row.incomplete)) throw new Error('unfinished episode or HTTP request; automatic retry is forbidden');
    return { status: 'passed', identity: inspected.identity, episodes: inspected.records.length, requests: inspected.requests.length };
  }
  static async run(profileFile, directory, options = {}, dependencies = {}) {
    this.options(options);
    await this.prepare(profileFile, directory, options);
    let inspected = await this.inspect(directory, profileFile);
    const { manifest, identity, state } = inspected, profile = manifest.profile;
    const executionMode = options.executionMode ?? 'reference', maxRequests = options.maxRequests ?? state.maxRequests ?? profile.maxRequests;
    if (maxRequests > profile.maxRequests) throw new Error('request ceiling exceeds profile');
    if (state.executionMode && (state.executionMode !== executionMode || state.maxRequests !== maxRequests)) throw new Error('saved execution mode or request ceiling differs');
    if (inspected.requests.some(row => !row.response) || inspected.records.some(row => row.incomplete)) {
      this.summary(directory, inspected, 'failed', 'unfinished episode or HTTP request; automatic retry is forbidden');
      throw new Error('unfinished episode or HTTP request; automatic retry is forbidden');
    }
    const failed = inspected.records.find(row => row.record.status === 'policy_failure');
    state.halt ??= failed ? `policy failure in ${failed.caseId}: ${failed.record.failure}` : null;
    state.recorded = inspected.records.map(row => ({ caseId: row.caseId, sha256: Contract.hash(row) }));
    state.requestCount = inspected.requests.length;
    state.activeCaseId = null;
    if (state.halt) { this.seal(path.join(directory, 'state.json'), state); return this.summary(directory, inspected, 'failed', state.halt); }
    const pending = manifest.cases.filter(row => !inspected.records.some(saved => saved.caseId === row.id));
    const apiKey = dependencies.apiKey ?? process.env[profile.apiKeyEnv];
    if (executionMode === 'live' && pending.length && !apiKey) throw new Error(`missing ${profile.apiKeyEnv}`);
    state.executionMode = executionMode; state.maxRequests = maxRequests;
    this.seal(path.join(directory, 'state.json'), state);
    const started = Date.now(), maximum = options.maxEpisodes ?? profile.maxEpisodesPerRun;
    let processed = 0, requestCount = inspected.requests.length, pauseReason = null, lastRequest = -Infinity;
    await pending.reduce(async (previous, row) => {
      await previous;
      if (pauseReason || state.halt) return;
      if (processed >= maximum) { pauseReason = 'episode_slice'; return; }
      const worstSeconds = executionMode === 'live' ? profile.maxTurns * (profile.timeoutMs + profile.minIntervalMs) / 1000 : 0;
      if ((Date.now() - started) / 1000 + worstSeconds >= profile.jobSeconds) { pauseReason = 'job_time'; return; }
      if (executionMode === 'live' && requestCount + profile.maxTurns > maxRequests) { pauseReason = 'request_budget'; return; }
      state.activeCaseId = row.id;
      this.seal(path.join(directory, 'state.json'), state);
      const episodeDirectory = path.join(directory, 'episodes', row.id);
      fs.mkdirSync(episodeDirectory);
      let activeRequest = null;
      const beforeRequest = async request => {
        const remaining = profile.minIntervalMs - (performance.now() - lastRequest);
        if (remaining > 0) await delay(remaining);
        if (requestCount >= maxRequests) throw new Error('campaign request budget exhausted');
        if ((Date.now() - started) / 1000 + profile.timeoutMs / 1000 >= profile.jobSeconds) throw new Error('campaign request time exhausted');
        const sequence = requestCount + 1;
        activeRequest = { sequence, identity, caseId: row.id, createdAt: new Date().toISOString(), request };
        this.seal(path.join(directory, 'requests', `${String(sequence).padStart(8, '0')}.request.json`), activeRequest);
        state.requestCount = sequence;
        this.seal(path.join(directory, 'state.json'), state);
        requestCount = sequence;
        lastRequest = performance.now();
      };
      const afterResponse = async transport => {
        if (!activeRequest) throw new Error('response without request reservation');
        this.seal(path.join(directory, 'requests', `${String(activeRequest.sequence).padStart(8, '0')}.response.json`), { sequence: activeRequest.sequence, requestHash: Contract.hash(activeRequest), transport });
        activeRequest = null;
      };
      let policy = 'reference';
      if (executionMode === 'live') {
        const control = await Session.run(row.family, row.configuration, 'reference', { maxTurns: profile.maxTurns, timeoutMs: profile.timeoutMs });
        this.seal(path.join(episodeDirectory, 'control.json'), control);
        await Session.replay(control);
        if (control.status !== 'completed') throw new Error(`reference control failed: ${row.id}`);
        policy = dependencies.policyFactory ? await dependencies.policyFactory(profile, { apiKey, beforeRequest, afterResponse }, row) : new ModelPolicy(profile, { apiKey, beforeRequest, afterResponse });
      }
      const record = await Session.run(row.family, row.configuration, policy, { maxTurns: profile.maxTurns, timeoutMs: profile.timeoutMs });
      const replay = await Session.replay(record), saved = { identity, caseId: row.id, record, replay };
      this.seal(path.join(episodeDirectory, 'record.json'), saved);
      state.recorded.push({ caseId: row.id, sha256: Contract.hash(saved) });
      state.activeCaseId = null;
      processed++;
      if (record.status === 'policy_failure') state.halt = `policy failure in ${row.id}: ${record.failure}`;
      this.seal(path.join(directory, 'state.json'), state);
      inspected = await this.inspect(directory, profileFile);
      this.summary(directory, inspected, state.halt ? 'failed' : 'paused', state.halt ?? 'in_progress');
    }, Promise.resolve());
    inspected = await this.inspect(directory, profileFile);
    return this.summary(directory, inspected, state.halt ? 'failed' : inspected.records.length === manifest.cases.length ? 'completed' : 'paused', state.halt ?? pauseReason);
  }
  static async cli(args) {
    const [command, ...rest] = args;
    if (!['plan', 'run', 'verify'].includes(command) || rest.length % 2) throw new Error('usage: plan|run|verify --profile YAML --output DIRECTORY [--execution-mode reference|live] [--family all|ID] [--matrix configured|single|pairwise] [--attempts N] [--max-episodes N] [--max-requests N]');
    const parsed = rest.reduce((values, value, index) => {
      if (index % 2) return values;
      if (!['--profile', '--output', '--execution-mode', '--family', '--matrix', '--attempts', '--max-episodes', '--max-requests'].includes(value) || Object.hasOwn(values, value)) throw new Error(`unknown or repeated option ${value}`);
      return { ...values, [value]: rest[index + 1] };
    }, {});
    if (!parsed['--profile'] || !parsed['--output']) throw new Error('profile and output are required');
    const options = Object.fromEntries(Object.entries({ family: parsed['--family'], matrix: parsed['--matrix'], executionMode: parsed['--execution-mode'], attempts: parsed['--attempts'] === undefined ? undefined : Number(parsed['--attempts']), maxEpisodes: parsed['--max-episodes'] === undefined ? undefined : Number(parsed['--max-episodes']), maxRequests: parsed['--max-requests'] === undefined ? undefined : Number(parsed['--max-requests']) }).filter(([, value]) => value !== undefined));
    if (command === 'verify' && Object.keys(options).length) throw new Error('verify uses the saved plan and accepts no overrides');
    return this[command](parsed['--profile'], path.resolve(parsed['--output']), options);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { const result = await Campaign.cli(process.argv.slice(2)); process.stdout.write(JSON.stringify(result, null, 2) + '\n'); if (result.status === 'failed') process.exitCode = 1; }
  catch (error) { process.stderr.write(error.message + '\n'); process.exitCode = 1; }
}
