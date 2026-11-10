import { Ratio } from '../inquiry/selection_laws.mjs';

export const definition = {
  id: 'recursive_delegation', title: 'Recursive delegation with private signals',
  description: 'Inspect a hierarchy, send an upstream mandate, and forecast the output of recursively optimizing participants with distinct objectives and information.',
  axes: [
    { id: 'depth', description: 'Maximum number of delegation edges below the first participant.', class: 'structural', levels: { easy: 1, medium: 2, hard: 3 } },
    { id: 'branching', description: 'Number of distinct downstream participants at each non-leaf.', class: 'action_space', levels: { easy: 1, medium: 2, hard: 3 } },
    { id: 'alignment', description: 'Magnitude of signed participant preference offsets from the principal goal.', class: 'strategic', levels: { easy: 0, medium: 1, hard: 2 } },
    { id: 'private_information', description: 'Participant signal partition of six possible states.', class: 'information', levels: { easy: 'full', medium: 'shifted-pairs', hard: 'erased' } },
    { id: 'inspection_budget', description: 'Number of paid signal inspections available to the principal.', class: 'resource', levels: { easy: 2, medium: 1, hard: 0 } },
  ],
  claims: ['Executable finite recursive principal-agent decisions under distinct utilities and private signal partitions.', 'Exact public planning and outcome prediction under the declared local belief rule.', 'No claim of unrestricted equilibrium reasoning or natural-language delegation.'],
  controls: ['Constant null inspection.', 'No-inspection, perfect-compliance, and flattened-tree policies.', 'Seed multiples of 13 have a constant principal goal.', 'Inspection changes principal knowledge only; participants never receive inspection results.'],
};

const zero = new Ratio(0), one = new Ratio(1);
const clone = value => structuredClone(value);
const closed = (value, fields) => value !== null && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).sort().join(',') === fields.split(',').sort().join(',');

function configure(options) {
  if (!closed(options, Object.keys(options).join(',')) || Object.keys(options).some(key => !['seed', 'privateSeed', 'axes'].includes(key))) throw new Error('unknown creation option');
  if (!Number.isSafeInteger(options.seed ?? 1) || !Number.isSafeInteger(options.privateSeed ?? 1)) throw new Error('safe integer seeds required');
  const supplied = options.axes ?? {};
  if (supplied === null || typeof supplied !== 'object' || Array.isArray(supplied) || Object.keys(supplied).some(id => !definition.axes.some(axis => axis.id === id))) throw new Error('unknown axis');
  return { seed: Math.abs(options.seed ?? 1), privateSeed: Math.abs(options.privateSeed ?? 1), axes: Object.fromEntries(definition.axes.map(axis => {
    const level = supplied[axis.id] ?? 'easy';
    if (!Object.hasOwn(axis.levels, level)) throw new Error('unknown axis level');
    return [axis.id, { level, value: axis.levels[level] }];
  })) };
}

export function signal(view, participantId, worldIndex) {
  if (participantId === 'null') return 'constant';
  const participant = view.participants.find(item => item.id === participantId);
  if (!participant || !Number.isInteger(worldIndex) || worldIndex < 0 || worldIndex >= view.worlds.length) throw new Error('unknown participant or world');
  const channel = view.axes.private_information.value;
  return channel === 'full' ? `s${worldIndex}` : channel === 'shifted-pairs' ? `p${Math.floor(((worldIndex + participant.channelOffset) % view.worlds.length) / 2)}` : 'withheld';
}

function engine(view) {
  const memo = new Map();
  const visit = (participantId, request, worldIndex) => {
    const observed = signal(view, participantId, worldIndex), key = `${participantId}/${request}/${observed}`;
    if (memo.has(key)) return realize(memo.get(key), worldIndex);
    const participant = view.participants.find(item => item.id === participantId);
    const possible = view.worlds.map((world, index) => index).filter(index => signal(view, participantId, index) === observed);
    const mass = possible.reduce((sum, index) => sum + view.priorWeights[index], 0);
    const alternatives = [0, 1, 2].map(output => ({ kind: 'local', output, child: null, request: null, cost: participant.localCosts[output] })).concat(
      participant.children.flatMap(child => [0, 1, 2].map(command => ({ kind: 'delegate', output: null, child, request: command, cost: view.rules.delegationCost }))));
    const choices = alternatives.map(alternative => {
      const loss = possible.reduce((sum, index) => {
        const output = alternative.kind === 'local' ? alternative.output : visit(alternative.child, alternative.request, index).output;
        const ideal = Math.max(0, Math.min(2, view.worlds[index].goal + participant.bias));
        return sum + view.priorWeights[index] * (view.rules.ownGoalWeight * (ideal - output) ** 2 + view.rules.mandateWeight * (request - output) ** 2 + alternative.cost);
      }, 0);
      return { alternative, loss: new Ratio(loss, mass) };
    });
    const chosen = choices.reduce((best, candidate) => candidate.loss.compare(best.loss) < 0 ? candidate : best);
    const decision = { participant: participant.id, upstream: participant.parent, incomingRequest: request, privateSignal: observed,
      ownBias: participant.bias, kind: chosen.alternative.kind, downstream: chosen.alternative.child, outgoingRequest: chosen.alternative.request,
      expectedLocalLoss: String(chosen.loss) };
    // Cache the policy, not its realized downstream output: a delegated child can distinguish worlds that its parent cannot.
    const policy = { alternative: chosen.alternative, decision };
    memo.set(key, policy);
    return realize(policy, worldIndex);
  };
  const realize = (policy, worldIndex) => {
    if (policy.alternative.kind === 'local') return { output: policy.alternative.output, route: [policy.decision.participant], decisions: [policy.decision] };
    const child = visit(policy.alternative.child, policy.alternative.request, worldIndex);
    return { output: child.output, route: [policy.decision.participant, ...child.route], decisions: [policy.decision, ...child.decisions] };
  };
  const run = (participantId, request, worldIndex) => {
    const key = `${participantId}/${request}/${signal(view, participantId, worldIndex)}`;
    return memo.has(key) ? realize(memo.get(key), worldIndex) : visit(participantId, request, worldIndex);
  };
  // Recursive calls must realize cached policies for the current state too.
  return { run };
}

export function execute(view, request, worldIndex) {
  if (![0, 1, 2].includes(request)) throw new Error('request must be 0, 1, or 2');
  return clone(engine(view).run(view.root, request, worldIndex));
}

function tableFor(view) {
  // Each invocation is a fresh execution of the public participant program, not a stored outcome catalogue.
  const program = engine(view);
  return [0, 1, 2].map(request => view.worlds.map((world, index) => program.run(view.root, request, index).output));
}

function support(view) {
  return view.worlds.map((world, index) => index).filter(index => view.history.every(event => signal(view, event.participant, index) === event.signal));
}

function decision(view, surviving, table) {
  const mass = surviving.reduce((sum, index) => sum + view.priorWeights[index], 0);
  const choices = [0, 1, 2].map(request => ({ request, value: new Ratio(surviving.reduce((sum, index) => sum + view.priorWeights[index] * view.rules.errorCost * (view.worlds[index].goal - table[request][index]) ** 2, 0), mass) }));
  return choices.reduce((best, choice) => choice.value.compare(best.value) < 0 ? choice : best);
}

function planner(view, table) {
  const memo = new Map();
  const visit = (surviving, remaining, available) => {
    const key = `${surviving.join('.')}/${remaining}/${available.join('.')}`;
    if (memo.has(key)) return memo.get(key);
    const stop = decision(view, surviving, table);
    const mass = surviving.reduce((sum, index) => sum + view.priorWeights[index], 0);
    const candidates = remaining === 0 ? [] : available.map(participant => {
      const observations = [...new Set(surviving.map(index => signal(view, participant, index)))];
      const continuation = observations.reduce((sum, observed) => {
        const branch = surviving.filter(index => signal(view, participant, index) === observed);
        const weight = branch.reduce((value, index) => value + view.priorWeights[index], 0);
        return sum.plus(new Ratio(weight, mass).times(visit(branch, remaining - 1, available.filter(id => id !== participant)).value));
      }, zero);
      return { participant, value: new Ratio(view.rules.inspectionCost).plus(continuation) };
    });
    const best = candidates.reduce((answer, candidate) => candidate.value.compare(answer.value) < 0 ? candidate : answer, { participant: null, value: stop.value });
    const result = { ...best, candidates, stop };
    memo.set(key, result);
    return result;
  };
  return visit(support(view), view.budget.remaining, view.inspections.filter(id => !view.history.some(event => event.participant === id)));
}

function answer(view, table = tableFor(view)) {
  const surviving = support(view), mass = surviving.reduce((sum, index) => sum + view.priorWeights[index], 0);
  const chosen = decision(view, surviving, table);
  return { kind: 'delegate', request: chosen.request, forecast: [0, 1, 2].map(output => String(new Ratio(surviving.filter(index => table[chosen.request][index] === output).reduce((sum, index) => sum + view.priorWeights[index], 0), mass))) };
}

export function reference(view) {
  const table = tableFor(view), plan = planner(view, table);
  return plan.participant === null ? answer(view, table) : { kind: 'inspect', participant: plan.participant };
}

export const baselines = {
  no_inspection: view => answer(view),
  assume_compliance: view => answer(view, [0, 1, 2].map(request => view.worlds.map(() => request))),
  flatten_tree: view => {
    const flattened = clone(view);
    flattened.participants.find(item => item.id === view.root).children = [];
    return answer(flattened);
  },
};

export function create(options = {}) {
  const config = configure(options), participants = [];
  const grow = (parent, depth) => {
    const index = participants.length, id = `p${index}`;
    const participant = { id, parent, depth, children: [], bias: ((index + config.seed) % 3 - 1) * config.axes.alignment.value,
      channelOffset: (index + config.seed) % 6, localCosts: [0, 1, 2].map(output => (depth < config.axes.depth.value ? 7 : 0) + ((config.seed + index * 3 + output * (index % 3 + 1)) % 5)) };
    participants.push(participant);
    if (depth < config.axes.depth.value) participant.children = Array.from({ length: config.axes.branching.value }, () => grow(id, depth + 1));
    return id;
  };
  const root = grow('principal', 0), deepest = participants.filter(item => item.depth === config.axes.depth.value);
  const inspections = [...new Set([root, deepest[0].id, deepest[deepest.length - 1].id, 'null'])];
  const worlds = Array.from({ length: 6 }, (_, index) => ({ id: `w${index}`, goal: config.seed % 13 === 0 ? 1 : (index + config.seed) % 3 }));
  const priorWeights = worlds.map((world, index) => 1 + ((index * 7 + config.seed) % 3));
  const mass = priorWeights.reduce((sum, value) => sum + value, 0), ticket = config.privateSeed % mass;
  const hiddenIndex = priorWeights.findIndex((weight, index) => priorWeights.slice(0, index + 1).reduce((sum, value) => sum + value, 0) > ticket);
  let history = [], remaining = config.axes.inspection_budget.value, regret = zero, terminal = null;
  const view = () => clone({ family: definition.id, phase: terminal ? 'terminal' : 'inspection', axes: config.axes, worlds, priorWeights, root, participants, inspections, history,
    budget: { initial: config.axes.inspection_budget.value, remaining },
    rules: { ownGoalWeight: 2, mandateWeight: 3, delegationCost: 1, inspectionCost: 1, errorCost: 12,
      signals: 'full: state index; shifted-pairs: floor(((state index + channelOffset) mod 6)/2); erased: withheld.',
      sampling: 'A uniform finite ticket from zero through sum(priorWeights)-1 selects the state proportional to priorWeights. Seed values deterministically index this ticket cycle; a fixed seed is a replay, not a random draw.',
      participantObjective: 'Minimize E[2*(clamp(goal+bias,0,2)-output)^2 + 3*(incomingRequest-output)^2 + transaction cost]. Local transaction cost is localCosts[output]; delegation costs one.',
      localBeliefRule: 'Normalize priorWeights within the participant private-signal cell. Commands enter utility and are not used as evidence. A participant predicts each child under that child own signal and recursively sends a chosen command.',
      alternatives: 'Each participant chooses local outputs 0,1,2, then each child in declared order with commands 0,1,2. Ties use this order. A delegated child returns its realized output up the entire selected path.',
      objective: 'Minimize inspection costs plus 12 times squared principal goal error. Send one request to the root and forecast returned output. Inspections reveal private signals only to the principal, are each usable once, and do not execute or change participants.',
    },
    actionSchema: { inspect: { kind: 'inspect', participant: 'unused id in inspections with positive remaining budget' }, delegate: { kind: 'delegate', request: 'integer 0, 1, or 2', forecast: 'three exact nonnegative fractions summing to one, in output 0,1,2 order' } },
  });
  return {
    view,
    get done() { return terminal !== null; },
    submit(action) {
      if (terminal) throw new Error('episode already terminal');
      const current = view();
      if (closed(action, 'kind,participant') && action.kind === 'inspect') {
        if (!inspections.includes(action.participant) || remaining === 0 || history.some(event => event.participant === action.participant)) throw new Error('inspection must be available and unused');
        const plan = planner(current, tableFor(current));
        const gap = plan.candidates.find(item => item.participant === action.participant).value.minus(plan.value);
        const event = { kind: 'observation', participant: action.participant, signal: signal(current, action.participant, hiddenIndex), cost: 1 };
        history = history.concat([event]); remaining--; regret = regret.plus(gap);
        return clone(event);
      }
      if (!closed(action, 'kind,request,forecast') || action.kind !== 'delegate' || !Number.isInteger(action.request) || action.request < 0 || action.request > 2 || !Array.isArray(action.forecast) || action.forecast.length !== 3) throw new Error('invalid delegation action');
      const forecast = Array.from({ length: 3 }, (_, index) => {
        if (!Object.hasOwn(action.forecast, index)) throw new Error('every forecast position is required');
        return Ratio.parse(action.forecast[index]);
      });
      if (forecast.some(value => value.compare(one) > 0) || forecast.reduce((sum, value) => sum.plus(value), zero).compare(one) !== 0) throw new Error('normalized forecast required');
      const table = tableFor(current), plan = planner(current, table), surviving = support(current), mass = surviving.reduce((sum, index) => sum + priorWeights[index], 0);
      const expectedLoss = new Ratio(surviving.reduce((sum, index) => sum + priorWeights[index] * 12 * (worlds[index].goal - table[action.request][index]) ** 2, 0), mass);
      const finalRegret = regret.plus(expectedLoss.minus(plan.value));
      const target = [0, 1, 2].map(output => new Ratio(surviving.filter(index => table[action.request][index] === output).reduce((sum, index) => sum + priorWeights[index], 0), mass));
      const excess = target.reduce((sum, probability, index) => { const delta = probability.minus(forecast[index]); return sum.plus(delta.times(delta)); }, zero);
      const realized = execute(current, action.request, hiddenIndex), score = one.over(one.plus(finalRegret).plus(excess));
      terminal = { kind: 'terminal', metrics: { score: String(score), exact: score.compare(one) === 0 ? '1' : '0', regret: String(finalRegret), forecastExcess: String(excess), expectedPrincipalLoss: String(expectedLoss), inspectionCost: String(config.axes.inspection_budget.value - remaining), remainingSupport: String(surviving.length), realizedOutput: String(realized.output), realizedDepth: String(realized.route.length - 1), realizedPrincipalLoss: String(12 * (worlds[hiddenIndex].goal - realized.output) ** 2) }, request: action.request, forecast: clone(action.forecast) };
      return clone(terminal);
    },
    audit() { const current = view(); return clone({ family: definition.id, hiddenWorld: worlds[hiddenIndex].id, hiddenIndex, history, terminal, execution: terminal ? execute(current, terminal.request, hiddenIndex) : null }); },
  };
}
