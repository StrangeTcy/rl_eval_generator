import { Contract, Ratio, RNG } from './runtime.mjs';
import { CausalOracle } from './causal_structure_oracle.mjs';
import { CausalReference } from './causal_structure_reference.mjs';
export { CausalOracle } from './causal_structure_oracle.mjs';
export { CausalReference } from './causal_structure_reference.mjs';

export const definition = {
  id: 'causal_structure', title: 'Construct hidden causal structure',
  description: 'Construct a binary causal tree from observationally equivalent worlds, choose singleton interventions, and forecast held-out simultaneous interventions.',
  axes: [
    { id: 'node_count', description: 'Number of labeled binary nodes in the causal tree.', class: 'structural', levels: { easy: 3, medium: 4, hard: 5 } },
    { id: 'max_children', description: 'Maximum children per node; bounds above n-1 are equivalent. This changes the prior model class, not a guaranteed depth ordering.', class: 'structural', levels: { easy: 1, medium: 2, hard: 4 } },
    { id: 'intervention_access', description: 'Permitted singleton intervention nodes: all, first ceil(n/2), or none.', class: 'information', levels: { easy: 'all', medium: 'half', hard: 'none' } },
    { id: 'experiment_budget', description: 'Maximum paid experiments: n, ceil(n/2), or one. Resources cannot help when no informative intervention is accessible.', class: 'resource', levels: { easy: 'all', medium: 'half', hard: 'one' } },
  ],
  claims: ['Constructed models with no supplied candidate menu, within a declared rooted binary-tree grammar.', 'Every prior tree has exactly the same passive distribution for the fixed node offsets.', 'Singleton experiments are distinct from the held-out simultaneous interventions.', 'Forecast calibration, structural ambiguity, root randomness, information acquired, and query stopping are reported separately.', 'The reference uses greedy predictive-risk reduction with structural-information tie-breaking; no optimal-planning regret claim.'],
  controls: ['Independent Prüfer-tree/topological oracle and parent-assignment/ancestor-walk reference.', 'Calibrated premature submission, unjustified certainty, and correlation-only propagation.', 'An inaccessible intervention domain retains structural ambiguity without requiring the hidden tree to be guessed.', 'Branching and budget can have declared null interactions at small node counts or absent access.'],
};

export const reference = view => CausalReference.reference(view);
export const baselines = {
  premature: view => CausalReference.answer(view),
  confident: view => {
    const answer = CausalReference.answer(view);
    return { ...answer, identification: 'identified', predictions: view.targets.map(target => ({ id: target.id, distribution: CausalReference.distribution(view.nodes, answer.model, target.intervention) })) };
  },
  correlation_only: view => {
    const answer = CausalReference.answer(view), offsets = [...view.passive[0].assignment].map(Number);
    return { ...answer, predictions: view.targets.map(target => {
      const first = target.intervention[0], origin = view.nodes.indexOf(first.node), assignment = offsets.map(offset => offset ^ offsets[origin] ^ first.value);
      target.intervention.forEach(item => { assignment[view.nodes.indexOf(item.node)] = item.value; });
      return { id: target.id, distribution: [{ assignment: assignment.join(''), probability: '1' }] };
    }) };
  },
};

export function create(options = {}) {
  const config = Contract.configuration(definition, options), p = config.parameters, rng = new RNG(config.seed);
  const nodes = Array.from({ length: p.node_count }, (_, index) => `v${index}_${rng.next(10000)}`);
  const topologyCount = CausalOracle.count(nodes, p.max_children), privateTicketCount = topologyCount * 2 ** (nodes.length - 1);
  const ticket = config.privateSeed % privateTicketCount, parityTicket = Math.floor(ticket / topologyCount);
  const offsets = nodes.map((_, index) => index === 0 ? 0 : (parityTicket >> (index - 1)) & 1);
  const support = CausalOracle.trees(nodes, p.max_children, offsets), hidden = support[ticket % topologyCount];
  const passive = CausalOracle.distribution(nodes, hidden);
  const experimentDomain = p.intervention_access === 'none' ? [] : nodes.slice(0, p.intervention_access === 'half' ? Math.ceil(nodes.length / 2) : nodes.length);
  const initialBudget = p.experiment_budget === 'all' ? nodes.length : p.experiment_budget === 'half' ? Math.ceil(nodes.length / 2) : 1;
  const targets = nodes.flatMap((left, i) => nodes.slice(i + 1).flatMap((right, offset) => [0, 1].map(value => ({ id: `pair-${i}-${i + offset + 1}-${value}${1 - value}`, intervention: [{ node: left, value }, { node: right, value: 1 - value }] }))));
  let observations = [], remaining = initialBudget, terminal = null, acceptedModel = null;
  const view = () => structuredClone({
    family: definition.id, phase: terminal ? 'terminal' : 'discovery', axes: config.axes, parameters: p, nodes,
    grammar: { maxChildren: p.max_children, root: 'Exactly one root with a fresh fair binary exogenous bit for each population.', edges: 'Each non-root has exactly one parent and equals parent XOR flip, with flip an integer 0 or 1. The graph is a connected directed rooted tree.', prior: 'Uniform over all labeled rooted trees obeying maxChildren and all binary edge-parity assignments. Condition this signed prior on the exact passive distribution and acquired experiments. The private seed selects one signed prior model modulo the signed support size.', intervention: 'do fixes the named variables, replacing their incoming equations. Other structural equations and the fair root source remain unchanged. Two clamps act simultaneously.' },
    passive, experimentDomain, targets, observations, budget: { initial: initialBudget, remaining },
    rules: { experiment: 'Choose an unused affordable node from experimentDomain. Its value is clamped to zero and the complete exact joint distribution is returned; this is an intervention, not conditioning on an observation.', construction: 'Submit a constructed tree consistent with passive and acquired intervention distributions. Any compatible representative is accepted when topology is not identified. Report identified only if exactly one tree is compatible.', predictions: 'For every target id, report the posterior predictive distribution under its simultaneous intervention, averaging uniformly over compatible trees and their fair root bits. Assignment bitstrings follow nodes order. Use positive exact fractional probabilities, no duplicate assignments, and total mass one.', stopping: 'Submit when no information-bearing affordable singleton query remains. Null queries only consume budget; their cost is reported without a planning-regret claim.', scoring: 'ReportingScore separates model-fit errors, identification error and mean forecast excess. PredictiveScore is one minus half expected predictive Brier; intrinsic root randomness may keep it below one even for an identified model. Score divides PredictiveScore by one plus model-fit errors, identification error and unfinished-discovery indicator. Exact marks zero reporting loss. StructuralPredictiveUncertainty is residual predictive risk minus posterior-mean intrinsic risk.' },
    actionSchema: { experiment: { kind: 'experiment', node: 'unused affordable label from experimentDomain' }, submit_model: { kind: 'submit_model', model: '{root:node,edges:[{from:node,to:node,flip:0|1}]}', identification: 'identified|ambiguous', predictions: 'one {id,distribution:[{assignment:binary string,probability:exact fraction}]} per target' } },
  });
  return {
    view,
    get done() { return terminal !== null; },
    submit(action) {
      if (terminal) throw new Error('episode already terminal');
      if (JSON.stringify(action)?.length > 65536) throw new Error('action exceeds size limit');
      Contract.object(action, 'action');
      if (action.kind === 'experiment') {
        Contract.fields(action, ['kind', 'node']);
        if (remaining < 1 || !experimentDomain.includes(action.node) || observations.some(event => event.node === action.node)) throw new Error('unused affordable intervention node required');
        const event = { kind: 'observation', node: action.node, distribution: CausalOracle.distribution(nodes, hidden, [{ node: action.node, value: 0 }]) };
        observations = [...observations, event]; remaining -= 1;
        return structuredClone(event);
      }
      Contract.fields(action, ['kind', 'model', 'identification', 'predictions']);
      if (action.kind !== 'submit_model' || !['identified', 'ambiguous'].includes(action.identification)) throw new Error('constructed-model submission required');
      const model = CausalOracle.validateModel(action.model, nodes, p.max_children);
      if (!Array.isArray(action.predictions) || action.predictions.includes(undefined) || action.predictions.length !== targets.length || new Set(action.predictions.map(item => item?.id)).size !== targets.length) throw new Error('complete distinct target predictions required');
      const parsed = action.predictions.map(prediction => {
        Contract.fields(prediction, ['id', 'distribution']);
        const target = targets.find(item => item.id === prediction.id);
        if (!target || !Array.isArray(prediction.distribution) || prediction.distribution.includes(undefined) || prediction.distribution.length < 1 || prediction.distribution.length > 2 ** (nodes.length - 2) || new Set(prediction.distribution.map(row => row?.assignment)).size !== prediction.distribution.length) throw new Error('bounded nonduplicated target distribution required');
        const rows = prediction.distribution.map(row => {
          Contract.fields(row, ['assignment', 'probability']);
          if (typeof row.assignment !== 'string' || row.assignment.length !== nodes.length || /[^01]/.test(row.assignment) || target.intervention.some(item => Number(row.assignment[nodes.indexOf(item.node)]) !== item.value)) throw new Error('binary assignment respecting target clamps required');
          const probability = Ratio.parse(row.probability);
          if (probability.n === 0n || probability.compare(new Ratio(1)) > 0) throw new Error('positive probability required');
          return { assignment: row.assignment, probability };
        });
        if (rows.reduce((sum, row) => sum.plus(row.probability), new Ratio(0)).compare(new Ratio(1)) !== 0) throw new Error('normalized target distribution required');
        return { id: target.id, rows };
      });
      // All input validation finishes before computing or publishing a terminal state.
      const current = view(), models = CausalOracle.compatible(current);
      const modelFitErrors = (JSON.stringify(CausalOracle.distribution(nodes, model)) === JSON.stringify(passive) ? 0 : 1) + observations.reduce((sum, event) => sum + (JSON.stringify(CausalOracle.distribution(nodes, model, [{ node: event.node, value: 0 }])) === JSON.stringify(event.distribution) ? 0 : 1), 0);
      const forecastExcess = targets.reduce((sum, target) => {
        const expected = CausalOracle.predictive(nodes, models, target.intervention), reported = parsed.find(item => item.id === target.id).rows;
        const outcomes = new Set([...expected.map(row => row.assignment), ...reported.map(row => row.assignment)]);
        return sum.plus([...outcomes].reduce((loss, assignment) => {
          const pExpected = Ratio.parse(expected.find(row => row.assignment === assignment)?.probability ?? '0'), pReported = reported.find(row => row.assignment === assignment)?.probability ?? new Ratio(0);
          const delta = pReported.minus(pExpected); return loss.plus(delta.times(delta));
        }, new Ratio(0)));
      }, new Ratio(0)).over(new Ratio(targets.length));
      const identificationError = action.identification === (models.length === 1 ? 'identified' : 'ambiguous') ? 0 : 1;
      const unfinishedDiscovery = remaining > 0 && CausalOracle.informative(current, models).length > 0 ? 1 : 0;
      const finalPredictiveRisk = CausalOracle.risk(current, models);
      const intrinsicPredictiveRisk = models.reduce((sum, candidate) => sum.plus(CausalOracle.risk(current, [candidate])), new Ratio(0)).over(new Ratio(models.length));
      const expectedPredictiveBrier = finalPredictiveRisk.plus(forecastExcess), predictiveScore = new Ratio(1).minus(expectedPredictiveBrier.over(new Ratio(2)));
      const reportingLoss = new Ratio(modelFitErrors + identificationError).plus(forecastExcess), reportingScore = new Ratio(1).over(new Ratio(1).plus(reportingLoss));
      const score = predictiveScore.over(new Ratio(1 + modelFitErrors + identificationError + unfinishedDiscovery));
      acceptedModel = structuredClone(model);
      terminal = { kind: 'terminal', metrics: { score: String(score), predictiveScore: String(predictiveScore), reportingScore: String(reportingScore), exact: reportingLoss.n === 0n ? '1' : '0', modelFitErrors: String(modelFitErrors), identificationError: String(identificationError), forecastExcess: String(forecastExcess), finalPredictiveRisk: String(finalPredictiveRisk), intrinsicPredictiveRisk: String(intrinsicPredictiveRisk), structuralPredictiveUncertainty: String(finalPredictiveRisk.minus(intrinsicPredictiveRisk)), expectedPredictiveBrier: String(expectedPredictiveBrier), unfinishedDiscovery: String(unfinishedDiscovery), queryStoppingSatisfied: unfinishedDiscovery ? '0' : '1', compatibleModels: String(models.length), experimentsUsed: String(observations.length) } };
      return structuredClone(terminal);
    },
    audit() { return structuredClone({ family: definition.id, hiddenModel: hidden, privateTicketCount, compatibleModels: CausalOracle.compatible(view()), acceptedModel, observations, terminal }); },
  };
}
