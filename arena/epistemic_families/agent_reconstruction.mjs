import { Ratio } from '../inquiry/selection_laws.mjs';

export const definition = {
  id: 'agent_reconstruction', title: 'Reconstruct a strategic agent',
  description: 'Identify a finite agent model from diagnostic play and forecast its behavior in a new payoff game.',
  axes: [
    { id: 'models', description: 'Number of candidate preference and belief hierarchies.', class: 'structural', levels: { easy: 3, medium: 5, hard: 7 } },
    { id: 'recursion', description: 'Nested opponent models evaluated beneath the target agent.', class: 'structural', levels: { easy: 0, medium: 1, hard: 2 } },
    { id: 'actions', description: 'Available actions for each participant in every generated payoff game.', class: 'action_space', levels: { easy: 2, medium: 3, hard: 4 } },
    { id: 'visibility', description: 'Diagnostic report retained from agent execution.', class: 'information', levels: { easy: 'action-and-margin', medium: 'action', hard: 'action-parity' } },
    { id: 'budget', description: 'Maximum paid diagnostic queries.', class: 'resource', levels: { easy: 4, medium: 2, hard: 1 } },
  ],
  claims: ['Finite preference-and-belief reconstruction with real recursive best-response execution.', 'Behavioral ambiguity is preserved in exact model and held-out action forecasts.', 'Does not establish open-ended understanding of people or unrestricted theory of mind.'],
  controls: ['Zero-payoff null query.', 'Every thirteenth seed makes all diagnostic contexts uninformative.', 'Stop, null-query, certainty and no-recursion baselines.', 'Exact finite-horizon public query planner.'],
};

const zero = new Ratio(0), one = new Ratio(1);
const copy = value => structuredClone(value);
const closed = (value, fields) => value !== null && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).sort().join(',') === fields.split(',').sort().join(',');
const probabilityVector = (value, count) => {
  if (!Array.isArray(value) || value.length !== count) throw new Error('forecast dimension mismatch');
  const parsed = Array.from({ length: count }, (_, index) => {
    if (!Object.hasOwn(value, index)) throw new Error('every forecast position is required');
    return Ratio.parse(value[index]);
  });
  if (parsed.some(item => item.compare(one) > 0) || parsed.reduce((sum, item) => sum.plus(item), zero).compare(one) !== 0) throw new Error('normalized forecast required');
  return parsed;
};
const configure = options => {
  if (options === null || typeof options !== 'object' || Array.isArray(options) || Object.keys(options).some(key => !['seed', 'privateSeed', 'axes'].includes(key))) throw new Error('closed creation options required');
  if (!Number.isSafeInteger(options.seed ?? 1) || !Number.isSafeInteger(options.privateSeed ?? 1)) throw new Error('safe integer seeds required');
  const supplied = options.axes ?? {};
  if (supplied === null || typeof supplied !== 'object' || Array.isArray(supplied) || Object.keys(supplied).some(key => !definition.axes.some(axis => axis.id === key))) throw new Error('unknown axis');
  const axes = Object.fromEntries(definition.axes.map(axis => {
    const level = supplied[axis.id] ?? 'easy';
    if (!Object.hasOwn(axis.levels, level)) throw new Error('unknown axis level');
    return [axis.id, axis.levels[level]];
  }));
  return { axes, seed: Math.abs(options.seed ?? 1), privateSeed: Math.abs(options.privateSeed ?? 1) };
};

/** Execute a complete subjective belief hierarchy, with alternating player roles. */
export function reason(context, mind) {
  const opponent = mind.belief === null ? null : reason(context, mind.belief);
  const opponentWeights = opponent === null ? mind.baseOpponentWeights : mind.baseOpponentWeights.map((_, action) => action === opponent.action ? 1 : 0);
  const denominator = mind.stateWeights.reduce((sum, weight) => sum + weight, 0) * opponentWeights.reduce((sum, weight) => sum + weight, 0);
  const utilities = context.actions.map((_, action) => new Ratio(context.payoffs.reduce((total, state, stateIndex) => total + state.reduce((sum, row, opponentAction) => {
    const payoff = mind.player === 0 ? state[action][opponentAction] : state[opponentAction][action];
    return sum + mind.stateWeights[stateIndex] * opponentWeights[opponentAction] * (mind.selfWeight * payoff[mind.player] + mind.otherWeight * payoff[1 - mind.player]);
  }, 0), 0), denominator));
  const chosen = utilities.reduce((best, value, action) => value.compare(utilities[best]) > 0 ? action : best, 0);
  const alternative = utilities.reduce((best, value, action) => action === chosen ? best : best === null || value.compare(best) > 0 ? value : best, null);
  return { action: chosen, utilities: utilities.map(String), margin: String(utilities[chosen].minus(alternative)), opponent };
}

export function diagnostic(context, model, visibility) {
  const result = reason(context, model.mind);
  if (visibility === 'action-and-margin') return `${result.action}:${result.margin}`;
  if (visibility === 'action') return String(result.action);
  if (visibility === 'action-parity') return String(result.action % 2);
  throw new Error('unknown visibility');
}

const surviving = view => view.models.map((_, index) => index).filter(index => view.history.every(event => diagnostic(view.queries.find(query => query.id === event.query).context, view.models[index], view.axes.visibility) === event.signal));
const distribution = (view, support) => {
  const total = support.reduce((sum, index) => sum + view.models[index].priorWeight, 0);
  if (total === 0) throw new Error('public history has zero likelihood');
  return view.models.map((model, index) => new Ratio(support.includes(index) ? model.priorWeight : 0, total));
};
export const posterior = view => distribution(view, surviving(view));
const heldoutDistribution = (view, probabilities) => view.targetContext.actions.map((_, action) => probabilities.reduce((sum, probability, index) => reason(view.targetContext, view.models[index].mind).action === action ? sum.plus(probability) : sum, zero));
const answer = view => {
  const probabilities = posterior(view);
  const decision = probabilities.reduce((best, probability, index) => probability.compare(probabilities[best]) > 0 ? index : best, 0);
  return { kind: 'answer', decision: view.models[decision].id, modelForecast: probabilities.map(String), actionForecast: heldoutDistribution(view, probabilities).map(String) };
};

export function plan(view) {
  const cache = new Map();
  const signals = new Map(view.queries.map(query => [query.id, view.models.map(model => diagnostic(query.context, model, view.axes.visibility))]));
  const visit = (support, remaining, available) => {
    const key = `${support.join('.')}/${remaining}/${available.map(query => query.id).join('.')}`;
    if (cache.has(key)) return cache.get(key);
    const total = support.reduce((sum, index) => sum + view.models[index].priorWeight, 0);
    const maximum = Math.max(...support.map(index => view.models[index].priorWeight));
    const stop = new Ratio(view.rules.errorCost).times(new Ratio(total - maximum, total));
    const candidates = remaining === 0 ? [] : available.map(query => {
      const groups = [...new Set(support.map(index => signals.get(query.id)[index]))];
      const continuation = groups.reduce((sum, signal) => {
        const group = support.filter(index => signals.get(query.id)[index] === signal);
        const weight = group.reduce((value, index) => value + view.models[index].priorWeight, 0);
        return sum.plus(new Ratio(weight, total).times(visit(group, remaining - 1, available.filter(item => item.id !== query.id)).value));
      }, zero);
      return { query: query.id, value: new Ratio(query.cost).plus(continuation) };
    });
    const best = candidates.reduce((best, candidate) => candidate.value.compare(best.value) < 0 ? candidate : best, { query: null, value: stop });
    const result = { ...best, stop, candidates };
    cache.set(key, result);
    return result;
  };
  return visit(surviving(view), view.budget.remaining, view.queries.filter(query => !view.history.some(event => event.query === query.id)));
}

export const reference = view => { const optimum = plan(view); return optimum.query === null ? answer(view) : { kind: 'query', query: optimum.query }; };
export const baselines = {
  stop: view => answer(view),
  null_query: view => view.budget.remaining > 0 && !view.history.some(event => event.query === 'null') ? { kind: 'query', query: 'null' } : answer(view),
  certainty: view => ({ kind: 'answer', decision: view.models[0].id, modelForecast: view.models.map((_, index) => index === 0 ? '1' : '0'), actionForecast: view.targetContext.actions.map((_, action) => reason(view.targetContext, view.models[0].mind).action === action ? '1' : '0') }),
  no_recursion: view => {
    const flat = copy(view);
    flat.models.forEach(model => { model.mind.belief = null; });
    if (surviving(flat).length === 0) flat.history = [];
    return answer(flat);
  },
};

export function create(options = {}) {
  const config = configure(options), axes = config.axes;
  let randomState = (config.seed >>> 0) || 0x6d2b79f5;
  const draw = bound => { randomState ^= randomState << 13; randomState ^= randomState >>> 17; randomState ^= randomState << 5; return (randomState >>> 0) % bound; };
  const mind = (model, depth, player) => ({
    player, selfWeight: 1 + (model + depth) % 3, otherWeight: (model + 2 * depth) % 4 - 1,
    stateWeights: [1 + (model + draw(4)) % 5, 1 + (2 * model + draw(4)) % 5],
    baseOpponentWeights: Array.from({ length: axes.actions }, () => 1 + draw(4)),
    belief: depth === axes.recursion ? null : mind(model, depth + 1, 1 - player),
  });
  const models = Array.from({ length: axes.models }, (_, index) => ({ id: `m${index}`, priorWeight: 1 + draw(3), mind: mind(index, 0, 0) }));
  const context = (id, empty) => ({ id, actions: Array.from({ length: axes.actions }, (_, index) => `a${index}`),
    payoffs: Array.from({ length: 2 }, () => Array.from({ length: axes.actions }, () => Array.from({ length: axes.actions }, () => empty ? [0, 0] : [draw(15) - 4, draw(15) - 4]))) });
  const queries = Array.from({ length: 4 }, (_, index) => ({ id: `q${index}`, cost: 1, context: context(`diagnostic${index}`, config.seed % 13 === 0) })).concat([{ id: 'null', cost: 1, context: context('zero-payoff', true) }]);
  const targetContext = context('heldout', false);
  const totalWeight = models.reduce((sum, model) => sum + model.priorWeight, 0), ticket = config.privateSeed % totalWeight;
  const hidden = models.findIndex((model, index) => models.slice(0, index + 1).reduce((sum, item) => sum + item.priorWeight, 0) > ticket);
  let history = [], remaining = axes.budget, regret = zero, terminal = null;
  const view = () => copy({ family: definition.id, phase: terminal === null ? 'reconstruction' : 'terminal', axes,
    models, queries, targetContext, history, budget: { initial: axes.budget, remaining },
    rules: { errorCost: 12, objective: 'Minimize query cost plus 12 times model-identification error; forecast both the model and its held-out action.',
      execution: 'Each mind maximizes subjective expected selfWeight * own payoff + otherWeight * opponent payoff over two states. stateWeights and baseOpponentWeights are normalized. A nested belief recursively predicts one opponent action and replaces baseOpponentWeights with a point mass. Player roles alternate. Ties select the lowest action index.',
      evidence: 'A uniform finite ticket from zero through sum(priorWeight)-1 samples the hidden catalogue model proportional to priorWeight. Seed values deterministically index this ticket cycle; a fixed seed is a replay, not a random draw. The model stays fixed and executes on each queried context. Diagnostic margin is selected expected utility minus the best alternative. A query is available once. Queries do not change any mind.',
      scoring: 'Query regret is the sum of conditional Bellman action gaps. Model and action forecasts use exact nonnegative fractions summing to one. Hidden outcomes are withheld until terminal.' },
    actionSchema: { query: { kind: 'query', query: 'unused query id' }, answer: { kind: 'answer', decision: 'model id', modelForecast: 'fractions in models order', actionForecast: 'fractions in targetContext.actions order' } },
  });
  return {
    view, get done() { return terminal !== null; },
    submit(action) {
      if (terminal !== null) throw new Error('episode already terminal');
      const current = view();
      if (closed(action, 'kind,query') && action.kind === 'query') {
        const query = queries.find(item => item.id === action.query);
        if (!query || remaining < 1 || history.some(event => event.query === query.id)) throw new Error('unused affordable query required');
        const optimum = plan(current), candidate = optimum.candidates.find(item => item.query === query.id);
        const event = { kind: 'observation', query: query.id, signal: diagnostic(query.context, models[hidden], axes.visibility), cost: query.cost };
        regret = regret.plus(candidate.value.minus(optimum.value)); remaining -= 1; history = history.concat([event]);
        return copy(event);
      }
      if (!closed(action, 'kind,decision,modelForecast,actionForecast') || action.kind !== 'answer' || !models.some(model => model.id === action.decision)) throw new Error('closed answer action required');
      const modelForecast = probabilityVector(action.modelForecast, models.length), actionForecast = probabilityVector(action.actionForecast, axes.actions);
      const probabilities = posterior(current), behavior = heldoutDistribution(current, probabilities), optimum = plan(current);
      const decision = models.findIndex(model => model.id === action.decision), decisionLoss = new Ratio(12).times(one.minus(probabilities[decision]));
      const modelExcess = modelForecast.reduce((sum, probability, index) => { const delta = probability.minus(probabilities[index]); return sum.plus(delta.times(delta)); }, zero);
      const actionExcess = actionForecast.reduce((sum, probability, index) => { const delta = probability.minus(behavior[index]); return sum.plus(delta.times(delta)); }, zero);
      const finalRegret = regret.plus(decisionLoss.minus(optimum.value));
      const realizedAction = reason(targetContext, models[hidden].mind).action;
      const realizedModelBrier = modelForecast.reduce((sum, probability, index) => { const delta = probability.minus(new Ratio(index === hidden ? 1 : 0)); return sum.plus(delta.times(delta)); }, zero);
      const realizedActionBrier = actionForecast.reduce((sum, probability, index) => { const delta = probability.minus(new Ratio(index === realizedAction ? 1 : 0)); return sum.plus(delta.times(delta)); }, zero);
      const score = one.over(one.plus(finalRegret).plus(modelExcess).plus(actionExcess));
      terminal = { kind: 'terminal', metrics: { score: String(score), exact: score.compare(one) === 0 ? '1' : '0', regret: String(finalRegret), modelForecastExcess: String(modelExcess), actionForecastExcess: String(actionExcess), realizedModelBrier: String(realizedModelBrier), realizedActionBrier: String(realizedActionBrier), queryCost: String(axes.budget - remaining), remainingSupport: String(probabilities.filter(probability => probability.n > 0n).length) } };
      return copy(terminal);
    },
    audit() { const current = view(); return copy({ family: definition.id, hiddenModel: models[hidden].id, targetPosterior: posterior(current).map(String), targetActionForecast: heldoutDistribution(current, posterior(current)).map(String), targetExecution: reason(targetContext, models[hidden].mind), history, terminal }); },
  };
}
