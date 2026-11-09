/** Finite truthful-message selection with exact posterior and decision scores. */
import { createHash } from 'node:crypto';

export class Ratio {
  constructor(numerator, denominator = 1n) {
    const n = BigInt(numerator), d = BigInt(denominator);
    if (d <= 0n) throw new Error('positive denominator required');
    const common = Ratio.common(n < 0n ? -n : n, d);
    this.n = n / common; this.d = d / common;
  }
  static common(a, b) { return b ? Ratio.common(b, a % b) : a; }
  static parse(text) {
    if (typeof text !== 'string' || /[\r\n]/.test(text) || !/^(0|[1-9][0-9]{0,127})(?:\/([1-9][0-9]{0,127}))?$/.test(text)) throw new Error('bounded nonnegative fraction required');
    const parts = text.split('/');
    return new Ratio(parts[0], parts[1] ?? '1');
  }
  plus(q) { return new Ratio(this.n * q.d + q.n * this.d, this.d * q.d); }
  minus(q) { return new Ratio(this.n * q.d - q.n * this.d, this.d * q.d); }
  times(q) { return new Ratio(this.n * q.n, this.d * q.d); }
  over(q) { if (q.n <= 0n) throw new Error('positive divisor required'); return new Ratio(this.n * q.d, this.d * q.n); }
  compare(q) { const difference = this.n * q.d - q.n * this.d; return difference < 0n ? -1 : difference > 0n ? 1 : 0; }
  toString() { return this.d === 1n ? String(this.n) : `${this.n}/${this.d}`; }
}

export class SelectionTask {
  constructor(spec) {
    if (Object.keys(spec).sort().join(',') !== 'observed,prior,truthMasks,weights') throw new Error('closed selection specification required');
    if (!Array.isArray(spec.prior) || spec.prior.length < 2 || spec.prior.length > 8 || spec.prior.some(value => !Number.isInteger(value) || value < 1 || value > 100)) throw new Error('two to eight positive prior weights required');
    if (!Array.isArray(spec.truthMasks) || spec.truthMasks.length < 1 || spec.truthMasks.length > 16 || spec.truthMasks.some(mask => !Number.isInteger(mask) || mask < 1 || mask >= 2 ** spec.prior.length)) throw new Error('valid nonempty truth masks required');
    if (!Array.isArray(spec.weights) || spec.weights.length !== spec.prior.length || spec.weights.some((row, world) => !Array.isArray(row) || row.length !== spec.truthMasks.length || row.some((weight, message) => !Number.isInteger(weight) || weight < 0 || weight > 100 || (weight > 0 && !(spec.truthMasks[message] & (1 << world)))) || row.reduce((a, b) => a + b, 0) === 0)) throw new Error('each world needs a truthful finite selection law');
    if (!Number.isInteger(spec.observed) || spec.observed < 0 || spec.observed >= spec.truthMasks.length || !spec.weights.some(row => row[spec.observed] > 0)) throw new Error('observed message must have positive probability');
    this.spec = structuredClone({ prior: spec.prior, truthMasks: spec.truthMasks, weights: spec.weights, observed: spec.observed });
    this.closed = false;
    this.id = createHash('sha256').update(JSON.stringify(this.spec)).digest('hex');
  }

  view() {
    return JSON.stringify({
      schema: 'truthful-selection-task/1',
      taskId: this.id,
      instruction: 'Infer the world after the displayed message was selected. All selectable messages are literally true. Row weights are normalized separately in each world. Choose a world minimizing zero-one loss and report its full posterior distribution. Different priors are allowed and do not establish deception.',
      worlds: this.spec.prior.map((_, world) => world),
      priorWeights: this.spec.prior,
      truthMasks: this.spec.truthMasks,
      selectionWeights: this.spec.weights,
      observedMessage: this.spec.observed,
      answerGrammar: 'answer WORLD p_world_0 p_world_1 ...; exact fractions summing to one',
    });
  }

  posterior(mode = 'selection') {
    if (!['selection', 'content'].includes(mode)) throw new Error('unknown conditioning rule');
    const mass = this.spec.prior.map((weight, world) => {
      const row = this.spec.weights[world];
      const likelihood = mode === 'selection'
        ? new Ratio(row[this.spec.observed], row.reduce((a, b) => a + b, 0))
        : new Ratio(this.spec.truthMasks[this.spec.observed] & (1 << world) ? 1 : 0);
      return new Ratio(weight).times(likelihood);
    });
    const total = mass.reduce((sum, value) => sum.plus(value), new Ratio(0));
    return mass.map(value => value.over(total));
  }

  answer(mode = 'selection') {
    const posterior = this.posterior(mode);
    const decision = posterior.reduce((best, value, index) => value.compare(posterior[best]) > 0 ? index : best, 0);
    return `answer ${decision} ${posterior.map(String).join(' ')}`;
  }

  submit(raw) {
    if (this.closed) throw new Error('task already scored');
    if (typeof raw !== 'string' || raw.length > 4096 || /[\r\n]/.test(raw) || !/^answer [0-7](?: (?:0|[1-9][0-9]{0,127})(?:\/[1-9][0-9]{0,127})?){2,8}$/.test(raw)) throw new Error('invalid answer grammar');
    const fields = raw.split(' '), decision = Number(fields[1]);
    const forecast = fields.slice(2).map(Ratio.parse);
    if (forecast.length !== this.spec.prior.length || decision >= forecast.length || forecast.some(value => value.compare(new Ratio(1)) > 0) || forecast.reduce((sum, value) => sum.plus(value), new Ratio(0)).compare(new Ratio(1)) !== 0) throw new Error('normalized forecast and valid decision required');
    const posterior = this.posterior();
    const maximum = posterior.reduce((best, value) => value.compare(best) > 0 ? value : best, new Ratio(0));
    const excess = posterior.reduce((sum, value, index) => {
      const delta = forecast[index].minus(value);
      return sum.plus(delta.times(delta));
    }, new Ratio(0));
    const bayesRisk = new Ratio(1).minus(posterior.reduce((sum, value) => sum.plus(value.times(value)), new Ratio(0)));
    this.closed = true;
    return {
      schema: 'truthful-selection-score/1', taskId: this.id,
      posterior: posterior.map(String), decision,
      expectedDecisionLoss: String(new Ratio(1).minus(posterior[decision])),
      decisionRegret: String(maximum.minus(posterior[decision])),
      expectedBrier: String(bayesRisk.plus(excess)),
      bayesBrier: String(bayesRisk), forecastExcess: String(excess),
      literalFalsehoodProbability: '0',
    };
  }
}

export class SelectionFamily {
  static create(severity, law = 'favors-0', prior = 'common') {
    if (!Number.isInteger(severity) || severity < 2 || severity > 20) throw new Error('severity must be an integer from two to twenty');
    if (!['favors-0', 'favors-1', 'uninformative'].includes(law) || !['common', 'observer-0', 'observer-1'].includes(prior)) throw new Error('unknown family arm');
    const a = law === 'favors-0' ? severity : 1;
    const b = law === 'favors-1' ? severity : 1;
    return {
      prior: prior === 'observer-0' ? [2, 1] : prior === 'observer-1' ? [1, 2] : [1, 1],
      truthMasks: [3, 1, 2],
      weights: [[a, severity + 1 - a, 0], [b, 0, severity + 1 - b]],
      observed: 0,
    };
  }
}
