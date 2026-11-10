import { Ratio } from '../inquiry/selection_laws.mjs';

export const definition = {
  id: 'evidence_process', title: 'Identify how evidence was produced',
  description: 'Distinguish ordinary sampling, selection before display, and sensor transformation by intervening on the evidence pipeline.',
  axes: [
    { id: 'diagnostic_access', description: 'Accessible interventions on the gate and sensor.', class: 'information', levels: { easy: ['paired_trace', 'gate_audit', 'calibrate', 'source_audit'], medium: ['paired_trace', 'source_audit'], hard: ['source_audit'] } },
    { id: 'evidence_batch', description: 'Number of initially displayed observations.', class: 'evidence', levels: { easy: 1, medium: 2, hard: 3 } },
    { id: 'severity', description: 'Raw source alphabet size; selecting its maximum amplifies its display probability by this factor.', class: 'structural', levels: { easy: 2, medium: 3, hard: 5 } },
    { id: 'diagnostic_budget', description: 'Credits for diagnostic interventions; paired/source traces cost one, gate/sensor interventions cost two.', class: 'resource', levels: { easy: 4, medium: 2, hard: 1 } },
  ],
  claims: ['Exact posterior inference over three operationally specified evidence pipelines.', 'Ordinary and cyclically transformed samples have the same displayed marginal law.', 'Unidentified mechanisms require an underdetermined claim and a calibrated distribution.', 'Does not diagnose arbitrary real-world deception or sensor faults.'],
  controls: ['Source audit is a paid null intervention.', 'Ordinary and sensor pipelines are observationally equivalent without a paired trace or calibration.', 'A maximum-only batch supports selection without proving it.', 'Sample-only and certain-selection baselines.'],
};

const zero = new Ratio(0), one = new Ratio(1);
const clone = value => structuredClone(value);
const closed = (value, keys) => value !== null && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).sort().join(',') === keys.split(',').sort().join(',');

function configure(options) {
  if (options === null || typeof options !== 'object' || Array.isArray(options) || Object.keys(options).some(key => !['seed', 'privateSeed', 'axes'].includes(key))) throw new Error('unknown creation option');
  if (!Number.isSafeInteger(options.seed ?? 1) || !Number.isSafeInteger(options.privateSeed ?? 1)) throw new Error('safe integer seeds required');
  const supplied = options.axes ?? {};
  if (supplied === null || typeof supplied !== 'object' || Array.isArray(supplied) || Object.keys(supplied).some(key => !definition.axes.some(axis => axis.id === key))) throw new Error('unknown axis');
  return { seed: Math.abs(options.seed ?? 1), privateSeed: Math.abs(options.privateSeed ?? 1), axes: Object.fromEntries(definition.axes.map(axis => {
    const level = supplied[axis.id] ?? 'easy';
    if (!Object.hasOwn(axis.levels, level)) throw new Error('unknown axis level');
    return [axis.id, { level, value: clone(axis.levels[level]) }];
  })) };
}

const accepts = (process, raw, values) => process.gate === 'all' || raw === values[values.length - 1];
const display = (process, raw, rules) => process.sensor === 'identity' ? raw : (raw + rules.sensorShift) % rules.sourceValues.length;

// Likelihoods are derived by running finite interventions through gate/sensor primitives.
function outcomes(view, process, diagnostic) {
  const values = view.rules.sourceValues;
  if (diagnostic === 'source_audit') return [{ result: { sourceValues: values }, probability: one }];
  if (diagnostic === 'gate_audit') return [{ result: { decisions: values.map(raw => ({ raw, decision: accepts(process, raw, values) ? 'accept' : 'reject' })) }, probability: one }];
  if (diagnostic === 'calibrate') return [{ result: { raw: 0, shown: display(process, 0, view.rules) }, probability: one }];
  const admitted = values.filter(raw => accepts(process, raw, values));
  return admitted.map(raw => ({ result: diagnostic === 'paired_trace' ? { raw, shown: display(process, raw, view.rules) } : { shown: display(process, raw, view.rules) }, probability: new Ratio(1, admitted.length) }));
}

function condition(view, belief, diagnostic, result) {
  const encoded = JSON.stringify(result);
  const mass = belief.map((prior, index) => prior.times(outcomes(view, view.mechanisms[index], diagnostic).filter(outcome => JSON.stringify(outcome.result) === encoded).reduce((sum, outcome) => sum.plus(outcome.probability), zero)));
  const probability = mass.reduce((sum, item) => sum.plus(item), zero);
  return probability.n === 0n ? null : { probability, posterior: mass.map(item => item.over(probability)) };
}

function posterior(view) {
  return view.history.reduce((belief, event) => condition(view, belief, event.diagnostic, event.result).posterior, view.mechanisms.map(() => new Ratio(1, view.mechanisms.length)));
}

const bayesRisk = belief => one.minus(belief.reduce((sum, probability) => sum.plus(probability.times(probability)), zero));

function planner(view) {
  const cache = new Map();
  const visit = (belief, budget) => {
    const key = `${belief.map(String).join(',')}/${budget}`;
    if (cache.has(key)) return cache.get(key);
    const stop = bayesRisk(belief);
    const candidates = view.diagnostics.filter(diagnostic => diagnostic.cost <= budget).map(diagnostic => {
      const possible = new Map();
      view.mechanisms.forEach((process, index) => {
        if (belief[index].n > 0n) outcomes(view, process, diagnostic.id).forEach(outcome => possible.set(JSON.stringify(outcome.result), outcome.result));
      });
      const value = [...possible.values()].reduce((sum, result) => {
        const next = condition(view, belief, diagnostic.id, result);
        return sum.plus(next.probability.times(visit(next.posterior, budget - diagnostic.cost).value));
      }, zero);
      return { diagnostic: diagnostic.id, value };
    });
    const best = candidates.reduce((answer, candidate) => candidate.value.compare(answer.value) < 0 ? candidate : answer, { diagnostic: null, value: stop });
    const result = { ...best, stop, candidates };
    cache.set(key, result);
    return result;
  };
  return visit(posterior(view), view.budget.remaining);
}

function answer(view) {
  const belief = posterior(view), supported = belief.map((probability, index) => ({ probability, index })).filter(item => item.probability.n > 0n);
  return { kind: 'identify', mechanism: supported.length === 1 ? view.mechanisms[supported[0].index].id : 'underdetermined', posterior: belief.map(String) };
}

export function reference(view) {
  const plan = planner(view);
  return plan.diagnostic === null ? answer(view) : { kind: 'diagnose', diagnostic: plan.diagnostic };
}

export const baselines = {
  sample_only: view => answer(view),
  certain_selection: () => ({ kind: 'identify', mechanism: 'selection', posterior: ['0', '1', '0'] }),
  null_audit: view => view.budget.remaining > 0 ? { kind: 'diagnose', diagnostic: 'source_audit' } : answer(view),
};

export function create(options = {}) {
  const config = configure(options), alphabetSize = config.axes.severity.value;
  const sourceValues = Array.from({ length: alphabetSize }, (_, index) => index);
  const rules = { sourceValues, sourceLaw: 'Independent uniform raw draws before any gate.', sensorShift: 1 + config.seed % (alphabetSize - 1), selection: 'Reject every raw value except the maximum and redraw until accepted; then apply the sensor.', calibration: 'Feed known raw value zero directly to the sensor, bypassing the gate.', gateAudit: 'Feed every known raw source value into the gate and observe acceptance, bypassing the sensor.', pairedTrace: 'Observe both the admitted raw value and its displayed sensor reading.', sourceAudit: 'Read the fixed upstream source alphabet; this is identical for every mechanism.', objective: 'Use the available diagnostic budget to minimize posterior Brier uncertainty, then report its exact mechanism distribution. Claim a single mechanism only when uniquely identified; otherwise claim underdetermined.' };
  const mechanisms = [
    { id: 'ordinary', gate: 'all', sensor: 'identity' },
    { id: 'selection', gate: 'maximum', sensor: 'identity' },
    { id: 'sensor', gate: 'all', sensor: 'rotate' },
  ];
  const diagnostics = config.axes.diagnostic_access.value.map(id => ({ id, cost: id === 'gate_audit' || id === 'calibrate' ? 2 : 1 }));
  // A uniform ticket over this finite range gives an independent mechanism and
  // enough independent uniform raw digits for every permitted trajectory.
  const tapeSize = alphabetSize ** (config.axes.evidence_batch.value + config.axes.diagnostic_budget.value);
  const ticket = config.privateSeed % (mechanisms.length * tapeSize);
  const hidden = mechanisms[ticket % mechanisms.length];
  let tape = Math.floor(ticket / mechanisms.length);
  const generate = diagnostic => {
    if (diagnostic === 'source_audit') return { sourceValues: clone(sourceValues) };
    if (diagnostic === 'gate_audit') return { decisions: sourceValues.map(raw => ({ raw, decision: hidden.gate === 'maximum' && raw !== alphabetSize - 1 ? 'reject' : 'accept' })) };
    if (diagnostic === 'calibrate') return { raw: 0, shown: hidden.sensor === 'rotate' ? rules.sensorShift : 0 };
    const sourceDraw = tape % alphabetSize;
    tape = Math.floor(tape / alphabetSize);
    const raw = hidden.gate === 'maximum' ? alphabetSize - 1 : sourceDraw;
    const shown = hidden.sensor === 'rotate' ? (raw + rules.sensorShift) % alphabetSize : raw;
    return diagnostic === 'paired_trace' ? { raw, shown } : { shown };
  };
  let history = Array.from({ length: config.axes.evidence_batch.value }, () => ({ kind: 'observation', diagnostic: 'sample', result: generate('sample'), cost: 0 }));
  let remaining = config.axes.diagnostic_budget.value, regret = zero, terminal = null;
  const view = () => clone({
    family: definition.id, phase: terminal ? 'terminal' : 'diagnosis', axes: config.axes, rules, mechanisms,
    prior: mechanisms.map(() => '1/3'), diagnostics, history,
    budget: { initial: config.axes.diagnostic_budget.value, remaining },
    actionSchema: { diagnose: { kind: 'diagnose', diagnostic: 'affordable diagnostic id' }, identify: { kind: 'identify', mechanism: 'ordinary|selection|sensor|underdetermined', posterior: 'three normalized exact fractions in mechanisms order' } },
  });
  return {
    view,
    get done() { return terminal !== null; },
    submit(action) {
      if (terminal) throw new Error('episode already terminal');
      const current = view();
      if (closed(action, 'kind,diagnostic') && action.kind === 'diagnose') {
        const diagnostic = diagnostics.find(item => item.id === action.diagnostic);
        if (!diagnostic || diagnostic.cost > remaining) throw new Error('available affordable diagnostic required');
        const plan = planner(current), candidate = plan.candidates.find(item => item.diagnostic === diagnostic.id);
        const event = { kind: 'observation', diagnostic: diagnostic.id, result: generate(diagnostic.id), cost: diagnostic.cost };
        regret = regret.plus(candidate.value.minus(plan.value)); remaining -= diagnostic.cost; history = history.concat([event]);
        return clone(event);
      }
      if (!closed(action, 'kind,mechanism,posterior') || action.kind !== 'identify' || !['ordinary', 'selection', 'sensor', 'underdetermined'].includes(action.mechanism) || !Array.isArray(action.posterior) || action.posterior.length !== mechanisms.length) throw new Error('mechanism claim and exact posterior required');
      const forecast = action.posterior.map(value => Ratio.parse(value));
      if (forecast.some(value => value.compare(one) > 0) || forecast.reduce((sum, probability) => sum.plus(probability), zero).compare(one) !== 0) throw new Error('normalized posterior required');
      const belief = posterior(current), claim = answer(current).mechanism;
      const claimError = action.mechanism === claim ? zero : one;
      const excess = belief.reduce((sum, probability, index) => { const delta = forecast[index].minus(probability); return sum.plus(delta.times(delta)); }, zero);
      const finalRegret = regret.plus(bayesRisk(belief).minus(planner(current).value));
      const score = one.over(one.plus(finalRegret).plus(excess).plus(claimError));
      terminal = { kind: 'terminal', metrics: { score: String(score), exact: score.compare(one) === 0 ? '1' : '0', regret: String(finalRegret), posteriorExcess: String(excess), claimError: String(claimError), residualUncertainty: String(bayesRisk(belief)), diagnosticCost: String(config.axes.diagnostic_budget.value - remaining), compatibleMechanisms: String(belief.filter(probability => probability.n > 0n).length) } };
      return clone(terminal);
    },
    audit() { return clone({ family: definition.id, hiddenMechanism: hidden.id, privateTicketCount: mechanisms.length * tapeSize, targetPosterior: posterior(view()).map(String), history, terminal }); },
  };
}
