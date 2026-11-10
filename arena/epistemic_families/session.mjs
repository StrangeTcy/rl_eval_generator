import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { Catalog, PROTOCOL } from './catalog.mjs';
import { Contract } from './runtime.mjs';

export class Session {
  static async run(id, options = {}, policy = 'reference', { maxTurns = 32, timeoutMs = 15000 } = {}) {
    Contract.integer(maxTurns, 1, 128, 'turn limit');
    Contract.integer(timeoutMs, 1, 120000, 'policy timeout');
    const module = await Catalog.load(id), configuration = Catalog.options(module.definition, options), game = module.create(configuration);
    const actor = policy === 'reference' ? module.reference : typeof policy === 'string' ? module.baselines?.[policy] : null;
    const asynchronous = policy !== null && typeof policy === 'object' && !Array.isArray(policy) && typeof policy.act === 'function';
    const policyIdentity = asynchronous ? Contract.serializable(Contract.object(policy.identity, 'model policy identity')) : policy;
    if (typeof policy === 'string' && typeof actor !== 'function') throw new Error('unknown policy');
    if (typeof policy !== 'string' && !asynchronous && (!Array.isArray(policy) || policy.length === 0 || policy.some(item => typeof item !== 'string' || item.length === 0))) throw new Error('external policy must be an argv array or an async policy with identity');
    const events = [];
    let terminal = null, status = 'turn_limit', failure = null;
    for (let turn = 0; turn < maxTurns; turn++) {
      const view = Contract.serializable(game.view());
      let action, transport = null;
      try {
        if (actor) action = Contract.serializable(actor(structuredClone(view)));
        else if (asynchronous) {
          const result = await policy.act(structuredClone(view));
          transport = Contract.serializable(result.transport ?? null);
          action = Contract.serializable(Contract.object(result.action, 'JSON action'));
        }
        else {
          const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'epistemic-policy-'));
          const execution = spawnSync(policy[0], policy.slice(1), { input: JSON.stringify(view)+'\n', cwd, encoding: 'utf8', timeout: timeoutMs, maxBuffer: 1048576, windowsHide: true, shell: false });
          transport = { cwd, exitCode: execution.status, signal: execution.signal, stderr: execution.stderr, raw: execution.stdout, error: execution.error?.message ?? null };
          if (execution.error || execution.status !== 0) throw new Error('external policy failed');
          action = JSON.parse(execution.stdout);
          Contract.object(action, 'JSON action');
        }
      } catch (error) {
        status = ['output_limit', 'invalid_output', 'refusal'].includes(error.episodeStatus) ? error.episodeStatus : 'policy_failure';
        failure = error.message; transport = Contract.serializable(error.transport ?? transport);
        events.push({ view, transport, failure, outcome: status }); break;
      }
      try {
        const response = Contract.serializable(game.submit(structuredClone(action)));
        events.push({ view, action, response, transport });
        if (game.done) {
          if (response.kind !== 'terminal' || !response.metrics) throw new Error('invalid terminal contract');
          terminal = response; status = 'completed'; break;
        }
      } catch (error) {
        if (JSON.stringify(game.view()) !== JSON.stringify(view)) throw new Error(`invalid action mutated state: ${id}`);
        status = 'invalid_action'; failure = error.message; events.push({ view, action, failure, transport }); break;
      }
    }
    return { protocol: PROTOCOL, family: id, configuration, policy: policyIdentity, status, failure, events, terminal, audit: Contract.serializable(game.audit()), scope: 'Trusted controller transcript; policy receives current views only. External argv processes have no hidden controller object, but are not a hostile-code OS sandbox.' };
  }
  static async replay(record) {
    if (record.protocol !== PROTOCOL) throw new Error('unsupported record protocol');
    const module = await Catalog.load(record.family), configuration = Catalog.options(module.definition, record.configuration), game = module.create(configuration);
    let terminal = null, outcome = 'turn_limit', failure = null;
    record.events.forEach((event, index) => {
      if (outcome !== 'turn_limit') throw new Error('event after episode outcome');
      if (JSON.stringify(game.view()) !== JSON.stringify(event.view)) throw new Error(`view mismatch at ${index}`);
      if (!Object.hasOwn(event, 'action')) {
        if (!event.failure || index !== record.events.length - 1 || !['policy_failure', 'output_limit', 'invalid_output', 'refusal'].includes(event.outcome) || record.status !== event.outcome || record.failure !== event.failure) throw new Error('invalid policy failure outcome record');
        outcome = event.outcome; failure = event.failure;
        return;
      }
      let response, error = null;
      try { response = game.submit(structuredClone(event.action)); } catch (caught) { error = caught; }
      if (event.failure) {
        if (!error || error.message !== event.failure || JSON.stringify(game.view()) !== JSON.stringify(event.view)) throw new Error('invalid-action replay mismatch');
        outcome = 'invalid_action'; failure = event.failure;
      } else {
        if (error || JSON.stringify(response) !== JSON.stringify(event.response)) throw new Error(`response mismatch at ${index}`);
        if (game.done) { terminal = response; outcome = 'completed'; }
      }
    });
    if (record.status !== outcome || record.failure !== failure) throw new Error('episode outcome mismatch');
    if (JSON.stringify(terminal) !== JSON.stringify(record.terminal) || JSON.stringify(game.audit()) !== JSON.stringify(record.audit)) throw new Error('terminal/audit mismatch');
    if ((record.status === 'completed') !== game.done) throw new Error('completion mismatch');
    return { status: 'passed', family: record.family, events: record.events.length, episodeStatus: record.status };
  }
}
