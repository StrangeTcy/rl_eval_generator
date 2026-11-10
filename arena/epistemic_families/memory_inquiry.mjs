import { Contract, RNG, Ratio } from './runtime.mjs';

export const definition = {
  id: 'memory_inquiry', title: 'Inquiry after controlled retention',
  description: 'Forecast earlier events after an explicit retention boundary; purchase limited retrievals and preserve uncertainty about unavailable facts.',
  axes: [
    { id: 'events', description: 'Number of independently valued events in the exposure.', class: 'structural', levels: { easy: 4, medium: 6, hard: 8 } },
    { id: 'sources', description: 'Number of distinct event sources.', class: 'structural', levels: { easy: 1, medium: 2, hard: 3 } },
    { id: 'retention', description: 'Number of event records restored after the boundary; selected independently of event values.', class: 'information', levels: { easy: 4, medium: 2, hard: 1 } },
    { id: 'task', description: 'Recall a final value, final values by source, or parity of each source history.', class: 'structural', levels: { easy: 'last', medium: 'last_per_source', hard: 'source_parity' } },
    { id: 'retrievals', description: 'Number of additional original event values that can be recovered.', class: 'resource', levels: { easy: 2, medium: 1, hard: 0 } },
    { id: 'distractors', description: 'Irrelevant current events; a presentation intervention with no change in the exact posterior.', class: 'presentation', levels: { easy: 0, medium: 2, hard: 5 } },
  ],
  claims: ['Controlled context retention and retrieval planning in finite event histories.', 'The runner passes only the current view to a fresh policy invocation; the full audit is trusted-side.', 'Not a measurement of biological memory, internal attention, or hostile-code confinement.'],
  controls: ['Complete retention.', 'Zero retrieval budget.', 'Independent missing event bits remain uncertain.', 'Distractor-count invariance for the exact reference.', 'No-retrieval and overconfident forecasts.'],
};

class MemoryMath {
  static known(view) { return new Map([...view.retained, ...view.retrieved].map(event => [event.id, event.value])); }
  static posterior(target, known) { return target.events.some(id => !known.has(id)) ? new Ratio(1, 2) : new Ratio(target.events.reduce((value, id) => value ^ known.get(id), 0)); }
  static risk(view, known) { return new Ratio(view.targets.filter(target => target.events.some(id => !known.has(id))).length, 2 * view.targets.length); }
  static plan(view) {
    const known = this.known(view), available = view.skeleton.map(event => event.id).filter(id => !known.has(id));
    const visit = (remaining, acquired) => {
      const simulated = new Map(known);
      acquired.forEach(id => simulated.set(id, 0));
      const candidates = [{ ids: acquired, value: this.risk(view, simulated).plus(new Ratio(acquired.length, 20)) }];
      if (remaining > 0) available.filter(id => !acquired.includes(id)).forEach(id => candidates.push(visit(remaining - 1, [...acquired, id])));
      return candidates.reduce((best, candidate) => candidate.value.compare(best.value) < 0 ? candidate : best);
    };
    return visit(view.budget.remaining, []);
  }
  static answer(view, confident = false) {
    const known = this.known(view);
    return { kind: 'answer', predictions: view.targets.map(target => {
      const p = this.posterior(target, known), decision = p.compare(new Ratio(1, 2)) > 0 ? 1 : 0;
      return { target: target.id, probability: confident ? String(decision) : String(p), decision };
    }) };
  }
}

export function reference(view) {
  if (view.phase === 'exposure') return { kind: 'advance' };
  const plan = MemoryMath.plan(view);
  return plan.ids.length ? { kind: 'retrieve', event: plan.ids[0] } : MemoryMath.answer(view);
}
export const baselines = {
  no_retrieval: view => view.phase === 'exposure' ? { kind: 'advance' } : MemoryMath.answer(view),
  overconfident: view => view.phase === 'exposure' ? { kind: 'advance' } : MemoryMath.answer(view, true),
};

export function create(options = {}) {
  const configuration = Contract.configuration(definition, options), p = configuration.parameters, random = new RNG(configuration.seed);
  const order = random.shuffle(Array.from({ length: p.events }, (_, i) => i));
  const skeleton = order.map((position, time) => ({ id: `event_${position}`, source: `source_${time % p.sources}`, time }));
  const events = skeleton.map((event, i) => ({ ...event, value: (configuration.privateSeed >>> i) & 1 }));
  const retainedIds = random.shuffle(skeleton.map(event => event.id)).slice(0, Math.min(p.retention, p.events));
  const targets = p.task === 'last' ? [{ id: 'last', events: [skeleton.at(-1).id] }]
    : Array.from({ length: p.sources }, (_, i) => {
      const history = skeleton.filter(event => event.source === `source_${i}`);
      return { id: `target_${i}`, events: p.task === 'last_per_source' ? [history.at(-1).id] : history.map(event => event.id) };
    });
  const distracting = Array.from({ length: p.distractors }, (_, i) => ({ id: `current_${i}`, source: `source_${i % p.sources}`, value: (configuration.seed + i) % 2, period: 'current_not_exposure' }));
  let phase = 'exposure', remaining = p.retrievals, retrieved = [], done = false, result = null;
  const history = [];
  const view = () => ({
    family: definition.id, phase, axes: structuredClone(configuration.axes), parameters: structuredClone(p),
    actionSchema: phase === 'exposure' ? { kind: 'advance' } : { retrieve: { kind: 'retrieve', event: 'unretained event ID' }, answer: { kind: 'answer', predictions: [{ target: 'target ID', probability: 'nonnegative exact fraction', decision: '0 or 1' }] } },
    rules: { eventPrior: 'Independent uniform bits. Private ticket population is 0..2^events-1.', retention: 'The retention set was chosen independently of values. Advance replaces the policy context; it does not supply the old exposure or arbitrary notes.', targets: 'Each target is XOR of the listed original event values; a singleton is direct recall.', retrievalCost: '1/20', objective: 'Mean target decision loss plus retrieval expenditure.', policyContract: 'Only the current view is supplied on each call. Exposure audit and earlier views remain controller-side.' },
    skeleton: structuredClone(skeleton), targets: structuredClone(targets),
    exposure: phase === 'exposure' ? structuredClone(events) : [],
    retained: phase === 'exposure' ? [] : structuredClone(events.filter(event => retainedIds.includes(event.id))),
    retrieved: structuredClone(retrieved), distractors: phase === 'exposure' ? [] : structuredClone(distracting),
    budget: { remaining, initial: p.retrievals },
  });
  return {
    get done() { return done; }, view,
    submit(action) {
      if (done) throw new Error('episode closed');
      if (phase === 'exposure') {
        Contract.fields(action, ['kind']);
        if (action.kind !== 'advance') throw new Error('advance required at retention boundary');
        phase = 'recall'; history.push({ action: structuredClone(action), observation: { kind: 'retention_boundary' } });
        return { kind: 'retention_boundary', retainedCount: retainedIds.length };
      }
      if (action?.kind === 'retrieve') {
        Contract.fields(action, ['kind', 'event']);
        if (remaining <= 0 || !skeleton.some(event => event.id === action.event) || retainedIds.includes(action.event) || retrieved.some(event => event.id === action.event)) throw new Error('retrieval unavailable');
        const observation = structuredClone(events.find(event => event.id === action.event));
        retrieved = [...retrieved, observation]; remaining--; history.push({ action: structuredClone(action), observation });
        return { kind: 'retrieved_event', event: structuredClone(observation), remaining };
      }
      Contract.fields(action, ['kind', 'predictions']);
      if (action.kind !== 'answer' || !Array.isArray(action.predictions) || action.predictions.length !== targets.length || new Set(action.predictions.map(item => item?.target)).size !== targets.length) throw new Error('complete predictions required');
      const checked = action.predictions.map(item => {
        Contract.fields(item, ['target', 'probability', 'decision']);
        if (!targets.some(target => target.id === item.target)) throw new Error('unknown target');
        Contract.integer(item.decision, 0, 1, 'decision');
        const probability = Ratio.parse(item.probability);
        if (probability.compare(new Ratio(1)) > 0) throw new Error('probability outside unit interval');
        return { ...item, probability };
      });
      const publicView = view(), known = MemoryMath.known(publicView);
      const rows = targets.map(target => {
        const submitted = checked.find(item => item.target === target.id), truth = target.events.reduce((value, id) => value ^ events.find(event => event.id === id).value, 0);
        const posterior = MemoryMath.posterior(target, known), delta = submitted.probability.minus(posterior), realized = submitted.probability.minus(new Ratio(truth));
        const chosenLoss = submitted.decision === 1 ? new Ratio(1).minus(posterior) : posterior;
        const risk = posterior.compare(new Ratio(1, 2)) < 0 ? posterior : new Ratio(1).minus(posterior);
        return { target: target.id, posterior: String(posterior), forecastExcess: String(delta.times(delta)), realizedBrier: String(realized.times(realized)), decisionRegret: String(chosenLoss.minus(risk)), realizedDecisionLoss: String(submitted.decision === truth ? 0 : 1), irreducibleRisk: String(risk) };
      });
      const mean = key => String(rows.reduce((sum, row) => sum.plus(Ratio.parse(row[key])), new Ratio(0)).over(new Ratio(rows.length)));
      result = { kind: 'terminal', metrics: { forecastExcess: mean('forecastExcess'), realizedBrier: mean('realizedBrier'), decisionRegret: mean('decisionRegret'), realizedDecisionLoss: mean('realizedDecisionLoss'), irreducibleRisk: mean('irreducibleRisk'), retrievalCost: String(new Ratio(p.retrievals - remaining, 20)), retainedCount: retainedIds.length, recoveredCount: retrieved.length }, targets: rows };
      done = true; phase = 'terminal'; history.push({ action: structuredClone(action) });
      return structuredClone(result);
    },
    audit() { return structuredClone({ configuration, events, retainedIds, history, result }); },
  };
}
