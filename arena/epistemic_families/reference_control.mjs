import { Ratio } from './runtime.mjs';

// These are reasoning obligations, not bounds on irreducible or realized loss.
export const REFERENCE_REQUIREMENTS = Object.freeze({
  agent_reconstruction: { exact: { score: '1', exact: '1', regret: '0', modelForecastExcess: '0', actionForecastExcess: '0' } },
  inquiry_control: { exact: { score: '1', investigatorScore: '1', exact: '1', regret: '0', forecastExcess: '0' } },
  hypothesis_discovery: { exact: { reportingScore: '1', exact: '1', reportingLoss: '0', forecastExcess: '0', observedErrors: '0', observedForecastExcess: '0', unobservedForecastExcess: '0', identificationError: '0', unfinishedDiscovery: '0' } },
  evidence_process: { exact: { score: '1', exact: '1', regret: '0', posteriorExcess: '0', claimError: '0' } },
  adaptive_agents: { exact: { score: '1', exact: '1', inquiryRegret: '0', forecastExcess: '0' } },
  recursive_delegation: { exact: { score: '1', exact: '1', regret: '0', forecastExcess: '0' } },
  evaluator_prediction: { numeric: { forecastExcess: 0, selectedForecastExcess: 0, expectedSelectionRegret: 0, revisionForecastExcess: 0 } },
  belief_revision: { numeric: { forecastExcess: 0, statusAccuracy: 1, certificateValidity: 1, correctionPropagationAccuracy: 1, retainedSupportAccuracy: 1 } },
  memory_inquiry: { exact: { forecastExcess: '0', decisionRegret: '0' } },
});

export class ReferenceControl {
  static check(record) {
    if (record.status !== 'completed' || record.policy !== 'reference' || record.terminal?.kind !== 'terminal') throw new Error(`reference control did not complete: ${record.family}`);
    const requirement = REFERENCE_REQUIREMENTS[record.family], metrics = record.terminal.metrics;
    if (!requirement || !metrics) throw new Error(`unknown reference control: ${record.family}`);
    Object.entries(requirement.exact ?? {}).forEach(([key, expected]) => {
      let equal = false;
      try { equal = Ratio.parse(metrics[key]).compare(Ratio.parse(expected)) === 0; } catch { /* Missing and malformed values fail closed. */ }
      if (!equal) throw new Error(`reference control failed: ${record.family}.${key} must equal ${expected}`);
    });
    Object.entries(requirement.numeric ?? {}).forEach(([key, expected]) => {
      if (!Number.isFinite(metrics[key]) || Math.abs(metrics[key] - expected) > 1e-12) throw new Error(`reference control failed: ${record.family}.${key} must equal ${expected} within 1e-12`);
    });
    if (record.family === 'belief_revision') {
      const counts = {
        changedConclusionCount: record.terminal.conclusions.filter(row => row.probability !== row.oldProbability).length,
        retainedSupportedCount: record.terminal.conclusions.filter(row => row.oldProbability === 1 && row.probability === 1).length,
      };
      Object.entries(counts).forEach(([key, expected]) => {
        if (metrics[key] !== expected) throw new Error(`reference control failed: ${record.family}.${key} must equal ${expected}`);
      });
    }
    if (record.family === 'evaluator_prediction') {
      const revisions = record.events.filter(event => event.action?.kind === 'revise').length;
      if (metrics.revisionsUsed !== revisions || metrics.revisionForecastCount !== 2 * revisions) throw new Error('reference control failed: evaluator_prediction.revisionForecastCount does not match revision events');
    }
    return { status: 'passed', family: record.family, metrics: Object.keys({ ...requirement.exact, ...requirement.numeric }) };
  }
}
