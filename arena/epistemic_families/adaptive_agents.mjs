import { Ratio } from '../inquiry/selection_laws.mjs';

export const definition = {
  id: 'adaptive_agents', title: 'Forecast an adapting agent',
  description: 'Inspect an externally trained learner and forecast its actions after further fixed external updates.',
  axes: [
    { id: 'learner_count', description: 'Number of possible initial learner states and polarities.', class: 'structural', levels: { easy: 2, medium: 4, hard: 6 } },
    { id: 'update_law', description: 'Executable state update rule.', class: 'structural', levels: { easy: 'cumulative', medium: 'leaky', hard: 'window-two' } },
    { id: 'change_cadence', description: 'External polarity reverses every this many updates; zero keeps the regime fixed.', class: 'temporal', levels: { easy: 0, medium: 3, hard: 1 } },
    { id: 'observation_access', description: 'Information returned by a diagnostic checkpoint.', class: 'information', levels: { easy: 'state-and-action', medium: 'action-only', hard: 'alternate-action' } },
    { id: 'forecast_horizon', description: 'Number of future post-update actions forecast prospectively.', class: 'temporal', levels: { easy: 1, medium: 2, hard: 4 } },
    { id: 'inspection_budget', description: 'Maximum historical diagnostic inspections.', class: 'resource', levels: { easy: 3, medium: 2, hard: 1 } },
  ],
  claims: ['Exact finite prediction of a changing learner from limited observations.', 'A forecast is judged against its conditional Bayes target and the realized future separately.', 'No teaching, learner shaping, deployment, or uncontrolled counterpart interaction.'],
  controls: ['A null diagnostic is constant in every world.', 'Seeds divisible by 17 produce a declared diagnostic outage.', 'Stop-now, null-query, and frozen-state forecast baselines.', 'Exact public finite-horizon diagnostic planner.'],
};

const zero = new Ratio(0), one = new Ratio(1);
const clone = value => structuredClone(value);
const closed = (value, keys) => value !== null && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).sort().join(',') === keys.split(',').sort().join(',');

function configure(options) {
  if (!closed(options, Object.keys(options).join(',')) || Object.keys(options).some(key => !['seed', 'privateSeed', 'axes'].includes(key))) throw new Error('unknown creation option');
  if (!Number.isSafeInteger(options.seed ?? 1) || !Number.isSafeInteger(options.privateSeed ?? 1)) throw new Error('safe integer seeds required');
  const supplied = options.axes ?? {};
  if (supplied === null || typeof supplied !== 'object' || Array.isArray(supplied) || Object.keys(supplied).some(key => !definition.axes.some(axis => axis.id === key))) throw new Error('unknown axis');
  return { seed: Math.abs(options.seed ?? 1), privateSeed: Math.abs(options.privateSeed ?? 1), axes: Object.fromEntries(definition.axes.map(axis => {
    const level = supplied[axis.id] ?? 'easy';
    if (!Object.hasOwn(axis.levels, level)) throw new Error('unknown axis level');
    return [axis.id, axis.levels[level]];
  })) };
}

/** Apply real state transitions; stream entries are exogenous and cannot be edited by an action. */
export function trajectory(view, learner) {
  let score = learner.initialScore, recent = [learner.initialScore];
  return view.stream.map((input, index) => {
    const phase = view.axes.change_cadence === 0 ? 0 : Math.floor(index / view.axes.change_cadence);
    const polarity = learner.polarity * (phase % 2 === 0 ? 1 : -1);
    const update = polarity * input;
    if (view.axes.update_law === 'cumulative') score += update;
    else if (view.axes.update_law === 'leaky') score = Math.trunc(score / 2) + update;
    else if (view.axes.update_law === 'window-two') { recent = recent.concat([update]).slice(-2); score = recent.reduce((sum, value) => sum + value, 0); }
    else throw new Error('unknown update law');
    return { checkpoint: index, input, polarity, score, action: score >= view.rules.threshold ? 1 : 0 };
  });
}

export function diagnostic(view, learner, query) {
  if (query === 'null' || view.rules.diagnosticOutage) return 'withheld';
  const item = view.queries.find(value => value.id === query);
  if (!item) throw new Error('unknown diagnostic');
  const point = trajectory(view, learner)[item.checkpoint];
  if (view.axes.observation_access === 'alternate-action' && point.checkpoint % 2 === 1) return 'withheld';
  return view.axes.observation_access === 'state-and-action' ? `score:${point.score};action:${point.action}` : `action:${point.action}`;
}

export function posterior(view) {
  const weights = view.learners.map(learner => view.history.every(event => diagnostic(view, learner, event.query) === event.signal) ? learner.priorWeight : 0);
  const total = weights.reduce((sum, value) => sum + value, 0);
  if (!total) throw new Error('impossible diagnostic history');
  return weights.map(weight => new Ratio(weight, total));
}

export function forecast(view) {
  const weights = posterior(view);
  const runs = view.learners.map(learner => trajectory(view, learner));
  return Array.from({ length: view.axes.forecast_horizon }, (_, offset) => weights.reduce((sum, weight, index) => sum.plus(weight.times(new Ratio(runs[index][view.rules.historyLength + offset].action))), zero));
}

export function plan(view) {
  const initial = view.learners.map((learner, index) => index).filter(index => view.history.every(event => diagnostic(view, view.learners[index], event.query) === event.signal));
  const outputs = view.learners.map(learner => trajectory(view, learner).slice(view.rules.historyLength).map(point => point.action));
  const signals = view.queries.map(query => view.learners.map(learner => diagnostic(view, learner, query.id)));
  const cache = new Map();
  const visit = (support, budget, available) => {
    const key = `${support.join('.')}/${budget}/${available.join('.')}`;
    if (cache.has(key)) return cache.get(key);
    const total = support.reduce((sum, index) => sum + view.learners[index].priorWeight, 0);
    const stop = Array.from({ length: view.axes.forecast_horizon }, (_, offset) => {
      const positive = support.reduce((sum, index) => sum + view.learners[index].priorWeight * outputs[index][offset], 0);
      const probability = new Ratio(positive, total);
      return probability.times(one.minus(probability));
    }).reduce((sum, value) => sum.plus(value), zero).over(new Ratio(view.axes.forecast_horizon));
    const candidates = budget === 0 ? [] : available.map(query => {
      const partitions = [...new Set(support.map(index => signals[query][index]))];
      const value = partitions.reduce((sum, signal) => {
        const group = support.filter(index => signals[query][index] === signal);
        const weight = group.reduce((result, index) => result + view.learners[index].priorWeight, 0);
        return sum.plus(new Ratio(weight, total).times(visit(group, budget - 1, available.filter(index => index !== query)).value));
      }, zero);
      return { query: view.queries[query].id, value };
    });
    const best = candidates.reduce((answer, candidate) => candidate.value.compare(answer.value) < 0 ? candidate : answer, { query: null, value: stop });
    const result = { ...best, stop, candidates };
    cache.set(key, result);
    return result;
  };
  return visit(initial, view.budget.remaining, view.queries.map((query, index) => index).filter(index => !view.history.some(event => event.query === view.queries[index].id)));
}

const answer = view => ({ kind: 'forecast', probabilities: forecast(view).map(String) });
export function reference(view) { const optimum = plan(view); return optimum.query === null ? answer(view) : { kind: 'inspect', query: optimum.query }; }
export const baselines = {
  stop: answer,
  null_query: view => view.budget.remaining && !view.history.some(event => event.query === 'null') ? { kind: 'inspect', query: 'null' } : answer(view),
  frozen_state: view => {
    const weights = posterior(view);
    const positive = view.learners.reduce((sum, learner, index) => sum.plus(weights[index].times(new Ratio(trajectory(view, learner)[view.rules.historyLength - 1].action))), zero);
    return { kind: 'forecast', probabilities: Array.from({ length: view.axes.forecast_horizon }, () => String(positive)) };
  },
};

export function create(options = {}) {
  const config = configure(options), axes = config.axes;
  let state = config.seed >>> 0 || 0x6d2b79f5;
  const draw = bound => { state ^= state << 13; state ^= state >>> 17; state ^= state << 5; return (state >>> 0) % bound; };
  // Allocate fixed process parameters before catalogue size or forecast length can consume draws.
  const threshold = draw(3) - 1;
  let streamState = draw(0x100000000) || 0x6d2b79f5;
  const learners = Array.from({ length: axes.learner_count }, (_, index) => ({ id: `learner_${index}`, initialScore: (Math.floor(index / 2) + 1) * (index % 2 ? 1 : -1) + draw(3) - 1, polarity: index % 2 ? 1 : -1, priorWeight: 1 + draw(3) }));
  const historyLength = 6;
  const stream = Array.from({ length: historyLength + axes.forecast_horizon }, () => {
    streamState ^= streamState << 13; streamState ^= streamState >>> 17; streamState ^= streamState << 5;
    return (streamState >>> 0) % 7 - 3;
  });
  const queries = Array.from({ length: historyLength }, (_, checkpoint) => ({ id: `checkpoint_${checkpoint}`, checkpoint })).concat([{ id: 'null', checkpoint: null }]);
  const rules = { historyLength, threshold, diagnosticOutage: config.seed % 17 === 0,
    stream: 'Every stream value is a fixed externally supplied training signal. Inspect and forecast never change the stream or learner.',
    sampling: 'A uniform finite ticket from zero through sum(priorWeight)-1 selects the learner proportional to priorWeight. Seed values deterministically index this ticket cycle; a fixed seed is a replay, not a random draw.',
    update: 'At zero-based index t, phase=floor(t/change_cadence), or zero when cadence=0. Polarity is learner.polarity times (-1)^phase. Update is polarity times input. Cumulative adds to score; leaky uses trunc(score/2)+update; window-two sums the two most recent updates, with initialScore the initial one-entry window.',
    action: 'The post-update action is one exactly when score >= threshold; otherwise zero.',
    objective: 'Minimize expected mean future binary Brier loss using at most inspection_budget historical diagnostics. Each query is available once. All candidate learner definitions and prior weights are public; realized identity is withheld.',
    forecast: 'One exact fraction giving P(action=1) for each future checkpoint, in chronological order. No target future feedback precedes final submission.' };
  const total = learners.reduce((sum, learner) => sum + learner.priorWeight, 0);
  const ticket = config.privateSeed % total;
  const hiddenIndex = learners.findIndex((learner, index) => learners.slice(0, index + 1).reduce((sum, item) => sum + item.priorWeight, 0) > ticket);
  let history = [], remaining = axes.inspection_budget, regret = zero, terminal = null;
  const view = () => clone({ family: definition.id, phase: terminal ? 'terminal' : 'diagnosis', axes, learners, stream, queries, rules, history,
    budget: { initial: axes.inspection_budget, remaining },
    actionSchema: { inspect: { kind: 'inspect', query: 'unused historical checkpoint id or null' }, forecast: { kind: 'forecast', probabilities: 'one fraction in [0,1] per future checkpoint' } } });
  return {
    view,
    get done() { return terminal !== null; },
    submit(action) {
      if (terminal) throw new Error('episode already terminal');
      const current = view();
      if (closed(action, 'kind,query') && action.kind === 'inspect') {
        const query = queries.find(item => item.id === action.query);
        if (!query || remaining === 0 || history.some(event => event.query === query.id)) throw new Error('diagnostic must be unused and affordable');
        const optimum = plan(current);
        const gap = optimum.candidates.find(candidate => candidate.query === query.id).value.minus(optimum.value);
        const event = { kind: 'observation', query: query.id, signal: diagnostic(current, learners[hiddenIndex], query.id) };
        remaining -= 1; history = history.concat([event]); regret = regret.plus(gap);
        return clone(event);
      }
      if (!closed(action, 'kind,probabilities') || action.kind !== 'forecast' || !Array.isArray(action.probabilities) || action.probabilities.length !== axes.forecast_horizon) throw new Error('invalid forecast action');
      const probabilities = Array.from({ length: axes.forecast_horizon }, (_, index) => {
        if (!Object.hasOwn(action.probabilities, index)) throw new Error('every forecast position is required');
        return Ratio.parse(action.probabilities[index]);
      });
      if (probabilities.some(value => value.compare(one) > 0)) throw new Error('probabilities must be in [0,1]');
      const expected = forecast(current), optimum = plan(current), truth = trajectory(current, learners[hiddenIndex]).slice(historyLength);
      const excess = probabilities.reduce((sum, probability, offset) => { const delta = probability.minus(expected[offset]); return sum.plus(delta.times(delta)); }, zero).over(new Ratio(axes.forecast_horizon));
      const brier = probabilities.reduce((sum, probability, offset) => { const delta = probability.minus(new Ratio(truth[offset].action)); return sum.plus(delta.times(delta)); }, zero).over(new Ratio(axes.forecast_horizon));
      const queryRegret = regret.plus(optimum.stop.minus(optimum.value));
      const score = one.over(one.plus(queryRegret).plus(excess));
      terminal = { kind: 'terminal', metrics: { score: String(score), exact: score.compare(one) === 0 ? '1' : '0', forecastExcess: String(excess), inquiryRegret: String(queryRegret), brier: String(brier), conditionalBayesRisk: String(optimum.stop), inspections: String(axes.inspection_budget - remaining), remainingSupport: String(posterior(current).filter(value => value.n > 0n).length) } };
      return clone(terminal);
    },
    audit() { return clone({ family: definition.id, hiddenLearner: learners[hiddenIndex].id, trajectory: trajectory(view(), learners[hiddenIndex]), expectedForecast: forecast(view()).map(String), history, terminal }); },
  };
}
