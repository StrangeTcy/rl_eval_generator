import { Ratio } from '../inquiry/selection_laws.mjs';

export const definition = {
  id: 'hypothesis_discovery', title: 'Construct a symbolic law',
  description: 'Run bounded experiments, construct an executable polynomial expression, and predict unobserved inputs while retaining unresolved alternatives.',
  axes: [
    { id: 'degree', description: 'Maximum degree of a hidden integer polynomial.', class: 'structural', levels: { easy: 1, medium: 2, hard: 3 } },
    { id: 'coefficient_range', description: 'Absolute bound on every canonical coefficient.', class: 'structural', levels: { easy: 1, medium: 2, hard: 3 } },
    { id: 'experiment_budget', description: 'Number of input-output experiments available.', class: 'resource', levels: { easy: 6, medium: 4, hard: 2 } },
    { id: 'observable_domain', description: 'Inputs accessible to experimental interventions.', class: 'information', levels: { easy: [-3, -2, -1, 0, 1, 2, 3], medium: [-1, 0, 1], hard: [0] } },
  ],
  claims: ['Constructed executable ASTs, with no supplied candidate menu.', 'Exact finite polynomial support, separate reporting calibration, and proper predictive quality scoring.', 'Residual and domain-irreducible uncertainty are reported separately from reporting errors; no full query-planning regret claim.', 'Observationally equivalent expressions and unresolved model classes are accepted.', 'Does not establish discovery outside the published bounded grammar.'],
  controls: ['Zero polynomial is a supported null law.', 'Single-input experiments leave nonconstant coefficients unidentified.', 'Expression interpreter and hidden-polynomial evaluator are separate.', 'Matched zero-law probes at zero/one versus plus/minus three distinguish information acquired while keeping reporting calibrated.', 'Zero-law and premature-submission baselines.'],
};

const zero = new Ratio(0), one = new Ratio(1);
const closed = (value, keys) => value !== null && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).sort().join(',') === keys.split(',').sort().join(',');
const clone = value => structuredClone(value);

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

function polynomials(degree, bound) {
  const coefficients = Array.from({ length: 2 * bound + 1 }, (_, index) => index - bound);
  const extend = remaining => remaining === 0 ? [[]] : extend(remaining - 1).flatMap(prefix => coefficients.map(coefficient => prefix.concat([coefficient])));
  return extend(degree + 1);
}

// Hidden laws use Horner evaluation; submitted expressions use the interpreter below.
const evaluatePolynomial = (coefficients, x) => coefficients.reduceRight((value, coefficient) => value * x + coefficient, 0);

function compatible(view) {
  return polynomials(view.grammar.maxDegree, view.grammar.coefficientBound).filter(coefficients => view.observations.every(observation => evaluatePolynomial(coefficients, observation.x) === observation.y));
}

function validateModel(model, grammar) {
  let nodes = 0;
  const compile = (node, depth) => {
    nodes += 1;
    if (depth > grammar.maxDepth || nodes > grammar.maxNodes) throw new Error('expression exceeds grammar bounds');
    if (closed(node, 'op') && node.op === 'x') return [0n, 1n];
    if (closed(node, 'op,value') && node.op === 'const' && Number.isInteger(node.value) && Math.abs(node.value) <= grammar.coefficientBound) return [BigInt(node.value)];
    if (!closed(node, 'op,left,right') || !['add', 'mul'].includes(node.op)) throw new Error('bounded add/mul/x/const AST required');
    const left = compile(node.left, depth + 1), right = compile(node.right, depth + 1);
    const degree = node.op === 'add' ? Math.max(left.length, right.length) - 1 : left.length + right.length - 2;
    const result = Array.from({ length: degree + 1 }, (_, index) => node.op === 'add'
      ? (left[index] ?? 0n) + (right[index] ?? 0n)
      : left.reduce((sum, coefficient, position) => sum + coefficient * (right[index - position] ?? 0n), 0n));
    const canonical = result.slice(0, Math.max(1, result.findLastIndex(coefficient => coefficient !== 0n) + 1));
    if (canonical.length - 1 > grammar.maxDegree) throw new Error('intermediate semantic polynomial degree exceeds grammar');
    return canonical;
  };
  const coefficients = compile(model, 0);
  if (coefficients.some(coefficient => coefficient < -BigInt(grammar.coefficientBound) || coefficient > BigInt(grammar.coefficientBound))) throw new Error('canonical coefficient exceeds grammar');
  return coefficients;
}

function interpret(node, input) {
  if (node.op === 'x') return BigInt(input);
  if (node.op === 'const') return BigInt(node.value);
  const left = interpret(node.left, input), right = interpret(node.right, input);
  return node.op === 'add' ? left + right : left * right;
}

function modelFor(coefficients) {
  return coefficients.reduceRight((expression, coefficient) => expression === null ? { op: 'const', value: coefficient } : { op: 'add', left: { op: 'const', value: coefficient }, right: { op: 'mul', left: { op: 'x' }, right: expression } }, null);
}

function distribution(models, x) {
  const counts = new Map();
  models.forEach(coefficients => {
    const value = evaluatePolynomial(coefficients, x);
    counts.set(value, (counts.get(value) ?? 0) + 1);
  });
  return [...counts.entries()].sort((a, b) => a[0] - b[0]).map(([value, count]) => ({ value, probability: String(new Ratio(count, models.length)) }));
}

function predictiveRisk(models, inputs) {
  if (models.length === 1) return zero;
  return inputs.reduce((sum, x) => {
    const concentration = distribution(models, x).reduce((total, item) => { const probability = Ratio.parse(item.probability); return total.plus(probability.times(probability)); }, zero);
    return sum.plus(one.minus(concentration));
  }, zero).over(new Ratio(inputs.length));
}

function domainIrreducibleRisk(view, models) {
  const classes = new Map();
  models.forEach(coefficients => {
    const signature = view.experimentDomain.map(x => evaluatePolynomial(coefficients, x)).join(',');
    const group = classes.get(signature) ?? [];
    group.push(coefficients); classes.set(signature, group);
  });
  return [...classes.values()].reduce((sum, group) => sum.plus(new Ratio(group.length, models.length).times(predictiveRisk(group, view.evaluationDomain))), zero);
}

function usefulExperiments(view, models) {
  return view.experimentDomain.filter(x => !view.observations.some(observation => observation.x === x)).map(x => {
    const counts = new Map();
    models.forEach(coefficients => { const value = evaluatePolynomial(coefficients, x); counts.set(value, (counts.get(value) ?? 0) + 1); });
    return { x, collision: [...counts.values()].reduce((sum, count) => sum + count * count, 0), distinct: counts.size };
  }).filter(experiment => experiment.distinct > 1);
}

function proposal(view, models) {
  return {
    kind: 'submit_model', model: modelFor(models[0]),
    identification: models.length === 1 ? 'identified' : 'ambiguous',
    predictions: view.evaluationDomain.map(x => ({ x, distribution: distribution(models, x) })),
  };
}

export function reference(view) {
  const models = compatible(view), experiments = usefulExperiments(view, models);
  if (view.budget.remaining > 0 && experiments.length > 0) {
    const experiment = experiments.reduce((best, item) => item.collision < best.collision ? item : best);
    return { kind: 'experiment', x: experiment.x };
  }
  return proposal(view, models);
}

export const baselines = {
  premature: view => proposal(view, compatible(view)),
  zero_law: view => ({
    kind: 'submit_model', model: { op: 'const', value: 0 }, identification: 'identified',
    predictions: view.evaluationDomain.map(x => ({ x, distribution: [{ value: 0, probability: '1' }] })),
  }),
};

export function create(options = {}) {
  const config = configure(options), degree = config.axes.degree.value, bound = config.axes.coefficient_range.value;
  const support = polynomials(degree, bound), hidden = support[config.privateSeed % support.length];
  const domain = config.axes.observable_domain.value;
  const rotation = config.seed % domain.length;
  const experimentDomain = domain.slice(rotation).concat(domain.slice(0, rotation));
  const evaluationDomain = [-4, -2, -1, 0, 1, 2, 4];
  const grammar = { operations: ['add', 'mul', 'x', 'const'], maxDegree: degree, coefficientBound: bound, maxNodes: 63, maxDepth: 12, prior: 'Uniform over all canonical coefficient vectors within the degree and coefficient bounds, including zeros. A private ticket indexes this finite support modulo its size.', expression: 'x={op:"x"}; c={op:"const",value:integer}; binary={op:"add"|"mul",left:expression,right:expression}. Trailing zero coefficients are removed before every degree check; zero is represented as constant zero. Intermediate semantic polynomial degree must remain within maxDegree. Constants and final canonical coefficients obey coefficientBound.' };
  let observations = [], remaining = config.axes.experiment_budget.value, terminal = null, acceptedModel = null;
  const view = () => clone({
    family: definition.id, phase: terminal ? 'terminal' : 'discovery', axes: config.axes, grammar,
    experimentDomain, evaluationDomain, observations,
    budget: { initial: config.axes.experiment_budget.value, remaining },
    rules: { experiment: 'Choose an unused allowed input and receive an exact output.', submission: 'Construct an executable expression consistent with your experiments. For every evaluation input, report the full posterior predictive distribution as sparse integer values with exact fractional probabilities. Ambiguous classes may use any consistent representative model. Submit after no informative affordable experiment remains.', scoring: 'Reporting calibration and information acquired are separate. ReportingScore measures observed model fit, identification status and forecast excess. PredictiveScore is one minus half the conditional expected Brier loss averaged over the fixed evaluationDomain. The primary score is predictiveScore divided by one plus observed model errors, identification error, and premature-stop indicator. FinalPredictiveRisk is posterior Bayes uncertainty; domainIrreduciblePredictiveRisk is expected uncertainty after every allowed input is known, ignoring budget. These uncertainty measures are not reasoning regret. Hidden-law agreement is reported separately and is not required when observations cannot identify it.' },
    actionSchema: { experiment: { kind: 'experiment', x: 'unused integer from experimentDomain' }, submit_model: { kind: 'submit_model', model: 'bounded executable AST', identification: 'identified|ambiguous', predictions: 'one {x,distribution:[{value,probability}]} for every evaluationDomain input' } },
  });
  return {
    view,
    get done() { return terminal !== null; },
    submit(action) {
      if (terminal) throw new Error('episode already terminal');
      if (closed(action, 'kind,x') && action.kind === 'experiment') {
        if (remaining < 1 || !experimentDomain.includes(action.x) || observations.some(observation => observation.x === action.x)) throw new Error('unused affordable experiment input required');
        const event = { kind: 'observation', x: action.x, y: evaluatePolynomial(hidden, action.x) };
        observations = observations.concat([event]); remaining -= 1;
        return clone(event);
      }
      if (!closed(action, 'kind,model,identification,predictions') || action.kind !== 'submit_model' || !['identified', 'ambiguous'].includes(action.identification)) throw new Error('constructed model submission required');
      validateModel(action.model, grammar);
      if (!Array.isArray(action.predictions) || action.predictions.length !== evaluationDomain.length || new Set(action.predictions.map(prediction => prediction?.x)).size !== evaluationDomain.length) throw new Error('complete nonduplicated predictions required');
      const parsed = action.predictions.map(prediction => {
        if (!closed(prediction, 'x,distribution') || !evaluationDomain.includes(prediction.x) || !Array.isArray(prediction.distribution) || prediction.distribution.length < 1 || prediction.distribution.length > support.length || new Set(prediction.distribution.map(item => item?.value)).size !== prediction.distribution.length) throw new Error('invalid prediction distribution');
        const probabilities = prediction.distribution.map(item => {
          if (!closed(item, 'value,probability') || !Number.isSafeInteger(item.value) || Math.abs(item.value) > bound * (1 + 4 + 16 + 64)) throw new Error('bounded integer prediction required');
          return { value: item.value, probability: Ratio.parse(item.probability) };
        });
        if (probabilities.some(item => item.probability.compare(one) > 0) || probabilities.reduce((sum, item) => sum.plus(item.probability), zero).compare(one) !== 0) throw new Error('normalized predictive distribution required');
        return { x: prediction.x, probabilities };
      });
      const current = view(), models = compatible(current);
      const observedErrors = observations.reduce((sum, observation) => sum + (interpret(action.model, observation.x) === BigInt(observation.y) ? 0 : 1), 0);
      const errors = parsed.map(prediction => {
        const target = distribution(models, prediction.x);
        const values = [...new Set(target.map(item => item.value).concat(prediction.probabilities.map(item => item.value)))];
        const excess = values.reduce((sum, value) => {
          const expected = Ratio.parse(target.find(item => item.value === value)?.probability ?? '0');
          const reported = prediction.probabilities.find(item => item.value === value)?.probability ?? zero;
          const delta = reported.minus(expected);
          return sum.plus(delta.times(delta));
        }, zero);
        const bayesRisk = one.minus(target.reduce((sum, item) => { const probability = Ratio.parse(item.probability); return sum.plus(probability.times(probability)); }, zero));
        return { x: prediction.x, excess, bayesRisk };
      });
      const mean = items => items.length ? items.reduce((sum, item) => sum.plus(item.excess), zero).over(new Ratio(items.length)) : zero;
      const observedExcess = mean(errors.filter(item => observations.some(observation => observation.x === item.x)));
      const unobservedExcess = mean(errors.filter(item => !observations.some(observation => observation.x === item.x)));
      const identificationError = action.identification === (models.length === 1 ? 'identified' : 'ambiguous') ? 0 : 1;
      const unfinishedDiscovery = remaining > 0 && usefulExperiments(current, models).length > 0 ? 1 : 0;
      const reportingLoss = new Ratio(observedErrors + identificationError).plus(observedExcess).plus(unobservedExcess);
      const reportingScore = one.over(one.plus(reportingLoss));
      const finalPredictiveRisk = errors.reduce((sum, item) => sum.plus(item.bayesRisk), zero).over(new Ratio(evaluationDomain.length));
      const forecastExcess = mean(errors);
      const expectedPredictiveBrier = finalPredictiveRisk.plus(forecastExcess);
      const predictiveScore = one.minus(expectedPredictiveBrier.over(new Ratio(2)));
      const score = predictiveScore.over(new Ratio(1 + observedErrors + identificationError + unfinishedDiscovery));
      const irreducibleRisk = domainIrreducibleRisk(current, models);
      const hiddenAgreement = new Ratio(evaluationDomain.filter(x => interpret(action.model, x) === BigInt(evaluatePolynomial(hidden, x))).length, evaluationDomain.length);
      acceptedModel = clone(action.model);
      terminal = { kind: 'terminal', metrics: { score: String(score), predictiveScore: String(predictiveScore), reportingScore: String(reportingScore), exact: reportingLoss.compare(zero) === 0 ? '1' : '0', reportingLoss: String(reportingLoss), finalPredictiveRisk: String(finalPredictiveRisk), domainIrreduciblePredictiveRisk: String(irreducibleRisk), remainingReduciblePredictiveRisk: String(finalPredictiveRisk.minus(irreducibleRisk)), expectedPredictiveBrier: String(expectedPredictiveBrier), forecastExcess: String(forecastExcess), observedErrors: String(observedErrors), observedForecastExcess: String(observedExcess), unobservedForecastExcess: String(unobservedExcess), identificationError: String(identificationError), unfinishedDiscovery: String(unfinishedDiscovery), compatibleModels: String(models.length), hiddenModelAgreement: String(hiddenAgreement), experimentsUsed: String(observations.length) } };
      return clone(terminal);
    },
    audit() { return clone({ family: definition.id, hiddenCoefficients: hidden, privateTicketCount: support.length, compatibleCoefficients: compatible(view()), acceptedModel, observations, terminal }); },
  };
}
