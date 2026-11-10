import { Ratio } from '../inquiry/selection_laws.mjs';

export const definition = {
  id: 'inquiry_control', title: 'Sequential inquiry under a budget',
  description: 'A presenter permutes an unchanged diagnostic menu; an investigator chooses paid queries and stops with a calibrated decision.',
  axes: [
    { id: 'world_count', description: 'Number of competing latent states.', class: 'structural', levels: { easy: 4, medium: 6, hard: 8 } },
    { id: 'cost_pressure', description: 'Cost of each query from a six-unit budget.', class: 'resource', levels: { easy: 1, medium: 2, hard: 3 } },
    { id: 'presentation', description: 'Which components of a diagnostic result survive presentation.', class: 'information', levels: { easy: 'full', medium: 'pair-coarsened', hard: 'zero-or-erasure' } },
    { id: 'query_topology', description: 'Balanced, overlapping or nested diagnostic partitions.', class: 'structural', levels: { easy: 'balanced', medium: 'overlapping', hard: 'nested' } },
  ],
  claims: ['Executable presenter and investigator roles with order-only presentation control.', 'Exact finite-horizon query-choice and forecast scoring with presentation-invariant reference planning.', 'Signal coarsening can destroy identifiability; query order preserves the available facts.', 'Presenter realized cost is an outcome, not an unpaired causal effect estimate.', 'Does not establish open-ended scientific inquiry or natural-language understanding.'],
  controls: ['Constant-output null query.', 'Positive multiples of seed 11 give an entirely uninformative query family; seed zero remains informative.', 'First-row investigator and scripted null-first presenter.', 'Paired identical-private-ticket permutations isolate order effects on a fixed investigator.', 'Exhaustive decision-tree reference over public partitions.'],
};

const one = new Ratio(1), zero = new Ratio(0);
const closed = (value, keys) => value !== null && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).sort().join(',') === keys.split(',').sort().join(',');
const clone = value => structuredClone(value);

function configure(options) {
  if (!closed(options, Object.keys(options).join(',')) || Object.keys(options).some(key => !['seed', 'privateSeed', 'axes'].includes(key))) throw new Error('unknown creation option');
  if (!Number.isSafeInteger(options.seed ?? 1) || !Number.isSafeInteger(options.privateSeed ?? 1)) throw new Error('safe integer seeds required');
  const supplied = options.axes ?? {};
  if (supplied === null || typeof supplied !== 'object' || Array.isArray(supplied) || Object.keys(supplied).some(key => !definition.axes.some(axis => axis.id === key))) throw new Error('unknown axis');
  const axes = Object.fromEntries(definition.axes.map(axis => {
    const level = supplied[axis.id] ?? 'easy';
    if (!Object.hasOwn(axis.levels, level)) throw new Error('unknown axis level');
    return [axis.id, { level, value: axis.levels[level] }];
  }));
  return { axes, seed: Math.abs(options.seed ?? 1), privateSeed: Math.abs(options.privateSeed ?? 1) };
}

function posterior(view) {
  const surviving = view.worlds.map((world, index) => index).filter(index => view.history.every(event => view.queries.find(query => query.id === event.query).signals[index] === event.signal));
  const total = surviving.reduce((sum, index) => sum + view.priorWeights[index], 0);
  return view.worlds.map((world, index) => new Ratio(surviving.includes(index) ? view.priorWeights[index] : 0, total));
}

function planner(view) {
  const cache = new Map();
  const initial = view.worlds.map((world, index) => index).filter(index => view.history.every(event => view.queries.find(query => query.id === event.query).signals[index] === event.signal));
  const visit = (surviving, budget, available) => {
    const key = `${surviving.join('.')}/${budget}/${available.map(query => query.id).join('.')}`;
    if (cache.has(key)) return cache.get(key);
    const total = surviving.reduce((sum, index) => sum + view.priorWeights[index], 0);
    const maximum = Math.max(...surviving.map(index => view.priorWeights[index]));
    const stop = new Ratio(view.rules.errorCost).times(new Ratio(total - maximum, total));
    const candidates = available.filter(query => query.cost <= budget).map(query => {
      const signals = [...new Set(surviving.map(index => query.signals[index]))];
      const future = signals.reduce((sum, signal) => {
        const group = surviving.filter(index => query.signals[index] === signal);
        const mass = group.reduce((value, index) => value + view.priorWeights[index], 0);
        return sum.plus(new Ratio(mass, total).times(visit(group, budget - query.cost, available.filter(other => other.id !== query.id)).value));
      }, zero);
      return { query: query.id, value: new Ratio(query.cost).plus(future) };
    });
    const best = candidates.reduce((answer, query) => query.value.compare(answer.value) < 0 ? query : answer, { query: null, value: stop });
    const result = { ...best, stop, candidates };
    cache.set(key, result);
    return result;
  };
  return visit(initial, view.budget.remaining, view.queries.filter(query => !view.history.some(event => event.query === query.id)).sort((left, right) => left.id.localeCompare(right.id)));
}

function answer(view) {
  const probabilities = posterior(view);
  const decision = probabilities.reduce((best, probability, index) => probability.compare(probabilities[best]) > 0 ? index : best, 0);
  return { kind: 'answer', decision: view.worlds[decision], forecast: probabilities.map(String) };
}

export function reference(view) {
  if (view.role === 'presenter') return { kind: 'present', queryOrder: view.queries.map(query => query.id).sort((left, right) => left === 'null' ? 1 : right === 'null' ? -1 : left.localeCompare(right)) };
  const optimum = planner(view);
  return optimum.query === null ? answer(view) : { kind: 'query', query: optimum.query };
}

function firstRow(view) {
  if (view.role === 'presenter') return reference(view);
  if (posterior(view).filter(probability => probability.n > 0n).length === 1) return answer(view);
  const query = view.queries.find(item => item.cost <= view.budget.remaining && !view.history.some(event => event.query === item.id));
  return query ? { kind: 'query', query: query.id } : answer(view);
}

export const baselines = {
  stop: view => view.role === 'presenter' ? reference(view) : answer(view),
  null_query: view => {
    if (view.role === 'presenter') return reference(view);
    const query = view.queries.find(item => item.id === 'null' && item.cost <= view.budget.remaining && !view.history.some(event => event.query === item.id));
    return query ? { kind: 'query', query: query.id } : answer(view);
  },
  uniform: view => view.role === 'presenter' ? reference(view) : ({ kind: 'answer', decision: view.worlds[0], forecast: view.worlds.map(() => `1/${view.worlds.length}`) }),
  first_row: view => firstRow(view),
  misleading_presenter: view => view.role === 'presenter'
    ? { kind: 'present', queryOrder: view.queries.slice().sort((left, right) => new Set(left.signals).size - new Set(right.signals).size || left.id.localeCompare(right.id)).map(query => query.id) }
    : firstRow(view),
};

export function create(options = {}) {
  const config = configure(options), count = config.axes.world_count.value, cost = config.axes.cost_pressure.value;
  const shifted = Array.from({ length: count }, (_, index) => (index + config.seed % count) % count);
  const priorWeights = shifted.map(index => 1 + ((index * 7 + config.seed) % 3));
  const signalsFor = query => shifted.map(index => {
    const raw = config.axes.query_topology.value === 'balanced'
      ? (query === 0 ? index % 4 : query === 1 ? Math.floor(index / 2) % 4 : (index + query) % 4)
      : config.axes.query_topology.value === 'overlapping'
        ? (query === 0 ? Math.floor(index / 2) : (index * (query % 2 + 1) + Math.floor(index / 3) + query) % 4)
        : Math.max(0, Math.min(3, index - query));
    if (config.seed > 0 && config.seed % 11 === 0) return 'withheld';
    return config.axes.presentation.value === 'full' ? `s${raw}` : config.axes.presentation.value === 'pair-coarsened' ? `s${Math.floor(raw / 2)}` : raw === 0 ? 'zero' : 'withheld';
  });
  const queries = Array.from({ length: 5 }, (_, index) => ({ id: `q${index}`, cost, signals: signalsFor(index) })).concat([{ id: 'null', cost, signals: shifted.map(() => 'constant') }]);
  const totalWeight = priorWeights.reduce((sum, weight) => sum + weight, 0);
  const ticket = config.privateSeed % totalWeight;
  const hiddenIndex = priorWeights.findIndex((weight, index) => priorWeights.slice(0, index + 1).reduce((sum, value) => sum + value, 0) > ticket);
  let history = [], remaining = 6, regret = zero, terminal = null, queryOrder = null;
  const view = () => clone({
    family: definition.id, phase: terminal ? 'terminal' : queryOrder === null ? 'presentation' : 'inquiry', role: terminal ? 'complete' : queryOrder === null ? 'presenter' : 'investigator', axes: config.axes,
    worlds: shifted.map((value, index) => `w${index}`), priorWeights, queries: queryOrder === null ? queries : queryOrder.map(id => queries.find(query => query.id === id)), history,
    presentation: { operation: 'query-order-permutation', queryOrder },
    budget: { initial: 6, remaining },
    rules: { errorCost: 12, prior: 'Normalize priorWeights. A uniform private ticket selects a world by its prior weight. Query signals are deterministic in each world, indexed in worlds order.', presentation: config.axes.presentation.value, presenter: 'Submit exactly one permutation of every query id. No facts, signals, costs, priors, or resources may be changed. Then the role switches to investigator.', presenterObjective: 'Maximize the investigator\'s realized query cost plus 12 if its final world decision is wrong. The outcome alone is not a causal order-effect estimate; that requires a paired fixed-investigator comparison.', objective: 'The investigator minimizes query cost plus 12 times decision error probability, and reports the exact posterior. A query may be used once. Erasure is an observed signal.' },
    actionSchema: queryOrder === null ? { present: { kind: 'present', queryOrder: 'a permutation containing every published query id exactly once' } } : { query: { kind: 'query', query: 'unused affordable query id' }, answer: { kind: 'answer', decision: 'world id', forecast: 'one exact nonnegative fraction per world, summing to one' } },
  });
  return {
    view,
    get done() { return terminal !== null; },
    submit(action) {
      if (terminal) throw new Error('episode already terminal');
      const current = view();
      if (queryOrder === null) {
        if (!closed(action, 'kind,queryOrder') || action.kind !== 'present' || !Array.isArray(action.queryOrder) || action.queryOrder.length !== queries.length || new Set(action.queryOrder).size !== queries.length || action.queryOrder.some(id => !queries.some(query => query.id === id))) throw new Error('presenter may only permute every query exactly once');
        queryOrder = action.queryOrder.slice();
        return clone({ kind: 'presentation', role: 'investigator', queryOrder });
      }
      if (closed(action, 'kind,query') && action.kind === 'query') {
        const query = queries.find(item => item.id === action.query);
        if (!query || query.cost > remaining || history.some(event => event.query === query.id)) throw new Error('query must be unused and affordable');
        const plan = planner(current);
        const gap = plan.candidates.find(item => item.query === query.id).value.minus(plan.value);
        const event = { kind: 'observation', query: query.id, signal: query.signals[hiddenIndex], cost: query.cost };
        remaining -= query.cost; regret = regret.plus(gap); history = history.concat([event]);
        return clone(event);
      }
      if (!closed(action, 'kind,decision,forecast') || action.kind !== 'answer' || !current.worlds.includes(action.decision) || !Array.isArray(action.forecast) || action.forecast.length !== count) throw new Error('invalid answer action');
      const forecast = action.forecast.map(value => Ratio.parse(value));
      if (forecast.some(value => value.compare(one) > 0) || forecast.reduce((sum, value) => sum.plus(value), zero).compare(one) !== 0) throw new Error('normalized forecast required');
      const target = posterior(current), decisionIndex = current.worlds.indexOf(action.decision), plan = planner(current);
      const decisionLoss = new Ratio(12).times(one.minus(target[decisionIndex]));
      const finalRegret = regret.plus(decisionLoss.minus(plan.value));
      const excess = target.reduce((sum, probability, index) => { const delta = forecast[index].minus(probability); return sum.plus(delta.times(delta)); }, zero);
      const score = one.over(one.plus(finalRegret).plus(excess));
      const realizedDecisionLoss = decisionIndex === hiddenIndex ? 0 : 12;
      terminal = { kind: 'terminal', metrics: { score: String(score), investigatorScore: String(score), exact: score.compare(one) === 0 ? '1' : '0', regret: String(finalRegret), forecastExcess: String(excess), queryCost: String(6 - remaining), expectedDecisionLoss: String(decisionLoss), realizedDecisionLoss: String(realizedDecisionLoss), presenterRealizedObjective: String(6 - remaining + realizedDecisionLoss), remainingSupport: String(target.filter(value => value.n > 0n).length) } };
      return clone(terminal);
    },
    audit() { return clone({ family: definition.id, hiddenWorld: `w${hiddenIndex}`, privateTicketCount: totalWeight, queryOrder, targetPosterior: posterior(view()).map(String), history, terminal }); },
  };
}
