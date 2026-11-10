/** Revision of an explicit finite logical dependency graph after corrected evidence. */
export const definition = {
  id: 'belief_revision', title: 'Revise conclusions after corrected evidence',
  description: 'Update a finite logical network after premise replacement or withdrawal, preserving conclusions with independent support.',
  axes: [
    { id: 'premises', description: 'Number of binary root propositions.', class: 'structural', levels: { easy: 8, medium: 10, hard: 12 } },
    { id: 'depth', description: 'Number of dependency layers from each corrected premise.', class: 'structural', levels: { easy: 1, medium: 3, hard: 5 } },
    { id: 'supports', description: 'Number of independent supporting branches for the redundant conclusion.', class: 'structural', levels: { easy: 1, medium: 2, hard: 3 } },
    { id: 'corrections', description: 'Number of premise values replaced by corrected observations.', class: 'intervention', levels: { easy: 1, medium: 2, hard: 3 } },
    { id: 'uncertainty', description: 'Number of old observations withdrawn without replacement.', class: 'information', levels: { easy: 0, medium: 1, hard: 2 } },
  ],
  claims: ['Finite propositional consequence revision with complete possible-world verification.', 'Independent support can preserve a conclusion after another supporting premise is corrected.'],
  controls: ['Stale-evidence baseline.', 'Global-disbelief baseline.', 'Premise replacements and withdrawals scored separately.', 'Possible-world witnesses for uncertainty.'],
};

class Random {
  constructor(seed) { if (!Number.isInteger(seed)) throw new Error('integer seed required'); this.state = seed >>> 0 || 0x6d2b79f5; }
  next(n) { this.state ^= this.state << 13; this.state ^= this.state >>> 17; this.state ^= this.state << 5; return (this.state >>> 0) % n; }
  shuffle(values) { const result = [...values]; for (let i = result.length - 1; i > 0; i--) { const j = this.next(i + 1); [result[i], result[j]] = [result[j], result[i]]; } return result; }
}
const clone = value => structuredClone(value);
const close = (object, keys) => object && typeof object === 'object' && !Array.isArray(object) && Object.keys(object).sort().join(',') === [...keys].sort().join(',');
const resolveAxes = options => {
  const selection = options.axes ?? {};
  if (!close(selection, Object.keys(selection)) || Object.keys(selection).some(id => !definition.axes.some(axis => axis.id === id))) throw new Error('axis object with known IDs required');
  return Object.fromEntries(definition.axes.map(axis => {
    const level = selection[axis.id] ?? 'easy';
    if (!Object.hasOwn(axis.levels, level)) throw new Error('unknown axis level');
    return [axis.id, axis.levels[level]];
  }));
};

export const evaluateWorld = (view, assignment) => {
  const values = new Map();
  const premises = new Map(view.premises.map((premise, index) => [premise.id, Number(assignment[index])]));
  view.graph.forEach(node => {
    if (node.op === 'literal') values.set(node.id, premises.get(node.premise) === node.value ? 1 : 0);
    else if (node.op === 'and') values.set(node.id, node.inputs.every(id => values.get(id) === 1) ? 1 : 0);
    else if (node.op === 'or') values.set(node.id, node.inputs.some(id => values.get(id) === 1) ? 1 : 0);
    else throw new Error('unknown logical operation');
  });
  return values;
};
const compatible = (view, assignment, evidence) => evidence.every(item => Number(assignment[view.premises.findIndex(premise => premise.id === item.premise)]) === item.value);

export const posterior = (view, evidence = view.evidence) => {
  const known = new Map(evidence.map(item => [item.premise, item.value]));
  const free = view.premises.filter(premise => !known.has(premise.id));
  const worlds = Array.from({ length: 2 ** free.length }, (_, index) => {
    const bits = index.toString(2).padStart(free.length, '0');
    return view.premises.map(premise => known.has(premise.id) ? known.get(premise.id) : Number(bits[free.findIndex(item => item.id === premise.id)])).join('');
  });
  if (worlds.length === 0) throw new Error('inconsistent evidence');
  const evaluations = worlds.map(assignment => ({ assignment, values: evaluateWorld(view, assignment) }));
  return view.targets.map(nodeId => {
    const positive = evaluations.filter(world => world.values.get(nodeId) === 1);
    const probability = positive.length / evaluations.length;
    return { nodeId, probability, status: probability === 1 ? 'entailed' : probability === 0 ? 'refuted' : 'undetermined',
      witnesses: probability > 0 && probability < 1 ? [positive[0].assignment, evaluations.find(world => world.values.get(nodeId) === 0).assignment] : [] };
  });
};
export const reference = view => view.phase === 'before_correction' ? { kind: 'receive_correction' } : { kind: 'submit', predictions: posterior(view) };
export const baselines = {
  stale_evidence: view => view.phase === 'before_correction' ? { kind: 'receive_correction' } : { kind: 'submit', predictions: posterior(view, view.originalEvidence) },
  global_disbelief: view => view.phase === 'before_correction' ? { kind: 'receive_correction' } : { kind: 'submit', predictions: view.targets.map(nodeId => ({ nodeId, probability: 0, status: 'refuted', witnesses: [] })) },
};

export class RevisionGame {
  #spec;
  #correction;
  #evidence;
  #history;
  #phase;
  #world;
  #result;
  constructor(options = {}) {
    const axes = resolveAxes(options);
    const random = new Random(options.seed ?? 0), privateRandom = new Random(options.privateSeed ?? 0);
    const names = random.shuffle(Array.from({ length: axes.premises }, (_, index) => `proposition_${index}`));
    const premises = names.map(id => ({ id, priorProbability: 0.5 }));
    const original = premises.map(premise => ({ premise: premise.id, value: random.next(2) }));
    const unknownIndices = Array.from({ length: axes.uncertainty }, (_, index) => axes.premises - 1 - index);
    const correctedIndices = Array.from({ length: axes.corrections }, (_, index) => index);
    const stableIndices = Array.from({ length: axes.premises }, (_, index) => index).filter(index => !correctedIndices.includes(index) && !unknownIndices.includes(index));
    const guardIndices = stableIndices.slice(axes.supports - 1);
    // Every axis combination retains distinct unaffected propositions for the
    // independent alternative supports.
    const graph = [], literals = [];
    const nodeId = () => `node_${graph.length}_${random.next(0x100000).toString(16)}`;
    original.forEach(item => { const id = nodeId(); graph.push({ id, op: 'literal', premise: item.premise, value: item.value }); literals.push(id); });
    const chains = correctedIndices.map(index => {
      let current = literals[index];
      for (let layer = 0; layer < axes.depth; layer++) {
        const guard = guardIndices[(index + layer) % guardIndices.length];
        const id = nodeId(); graph.push({ id, op: 'and', inputs: random.shuffle([current, literals[guard]]) }); current = id;
      }
      return current;
    });
    const supports = [chains[0]];
    for (let index = 1; index < axes.supports; index++) {
      supports.push(literals[stableIndices[index - 1]]);
    }
    const redundant = nodeId(); graph.push({ id: redundant, op: 'or', inputs: random.shuffle(supports) });
    const uncertain = nodeId(); graph.push({ id: uncertain, op: 'and', inputs: unknownIndices.length ? unknownIndices.map(index => literals[index]) : [literals[guardIndices[0]]] });
    this.#spec = { axes, premises, graph, targets: random.shuffle([...chains, redundant, uncertain]), originalEvidence: original };
    this.#correction = [...correctedIndices.map(index => ({ operation: 'replace', premise: names[index], oldValue: original[index].value, value: 1 - original[index].value })),
      ...unknownIndices.map(index => ({ operation: 'withdraw', premise: names[index], oldValue: original[index].value }))];
    const current = original.filter((_, index) => !unknownIndices.includes(index)).map((item, index) => correctedIndices.includes(index) ? { ...item, value: 1 - item.value } : clone(item));
    // Withdrawn premises are always at the end, so filtered positions preserve
    // the corrected-prefix indexing above.
    this.#world = original.map((item, index) => unknownIndices.includes(index) ? privateRandom.next(2) : correctedIndices.includes(index) ? 1 - item.value : item.value).join('');
    this.#evidence = original; this.#history = []; this.#phase = 'before_correction'; this.#result = null; this.done = false;
    if (guardIndices.length < 1 || current.length !== axes.premises - axes.uncertainty) throw new Error('unsupported axis combination');
  }
  view() {
    return clone({ family: definition.id, phase: this.#phase, ...this.#spec, evidence: this.#evidence, history: this.#history,
      rules: 'Root propositions are independent fair binary variables before observations. Each graph literal states that one root equals its stated value; AND and OR nodes have their ordinary truth tables. The graph is listed in topological order. Original observations may be replaced or withdrawn by one trusted correction packet. Replacement supersedes the old value; withdrawal removes that evidence. Report probabilities under the remaining observations. Entailed means true in every compatible assignment; refuted means false in every assignment. An undetermined conclusion requires one compatible true witness and one compatible false witness, as bitstrings in the listed premise order. Unaffected evidence remains valid.',
      budgets: { correctionsRemaining: this.#phase === 'before_correction' ? 1 : 0 },
      actionSchema: { receive: { kind: 'receive_correction' }, submit: { kind: 'submit', predictions: 'one {nodeId,probability in [0,1],status: entailed|refuted|undetermined,witnesses:[bitstrings]} per target' } } });
  }
  submit(action) {
    if (this.done) throw new Error('episode closed');
    if (action?.kind === 'receive_correction') {
      if (!close(action, ['kind']) || this.#phase !== 'before_correction') throw new Error('correction unavailable');
      const changes = this.#correction;
      const next = this.#evidence.flatMap(item => {
        const change = changes.find(candidate => candidate.premise === item.premise);
        if (change?.operation === 'withdraw') return [];
        return [{ premise: item.premise, value: change ? change.value : item.value }];
      });
      this.#evidence = next; this.#phase = 'after_correction';
      const observation = { kind: 'correction', changes: clone(changes) };
      this.#history.push({ action: clone(action), observation: clone(observation) });
      return observation;
    }
    if (this.#phase !== 'after_correction') throw new Error('receive corrected evidence before concluding');
    const bitPattern = new RegExp(`^[01]{${this.#spec.premises.length}}$`);
    if (!close(action, ['kind', 'predictions']) || action.kind !== 'submit' || !Array.isArray(action.predictions) || action.predictions.length !== this.#spec.targets.length || new Set(action.predictions.map(row => row?.nodeId)).size !== this.#spec.targets.length ||
        action.predictions.some(row => !close(row, ['nodeId', 'probability', 'status', 'witnesses']) || !this.#spec.targets.includes(row.nodeId) || !Number.isFinite(row.probability) || row.probability < 0 || row.probability > 1 || !['entailed', 'refuted', 'undetermined'].includes(row.status) || !Array.isArray(row.witnesses) || row.witnesses.length > 2 || row.witnesses.some(witness => typeof witness !== 'string' || !bitPattern.test(witness)))) throw new Error('complete bounded conclusion predictions required');
    const view = this.view(), expected = posterior(view), before = posterior(view, view.originalEvidence), reality = evaluateWorld(view, this.#world);
    const rows = expected.map(item => {
      const submitted = action.predictions.find(row => row.nodeId === item.nodeId);
      const observed = reality.get(item.nodeId);
      const validWitnesses = item.status === 'undetermined' ? submitted.witnesses.length === 2 && submitted.witnesses.every(witness => compatible(view, witness, view.evidence)) &&
        new Set(submitted.witnesses.map(witness => evaluateWorld(view, witness).get(item.nodeId))).size === 2 : submitted.witnesses.length === 0;
      return { nodeId: item.nodeId, probability: item.probability, status: item.status, oldProbability: before.find(row => row.nodeId === item.nodeId).probability,
        forecast: submitted.probability, claimedStatus: submitted.status, forecastExcess: (submitted.probability - item.probability) ** 2,
        realizedBrier: (submitted.probability - observed) ** 2, statusCorrect: submitted.status === item.status ? 1 : 0,
        certificateValid: validWitnesses && submitted.status === item.status ? 1 : 0 };
    });
    const changed = rows.filter(row => row.probability !== row.oldProbability);
    const retained = rows.filter(row => row.oldProbability === 1 && row.probability === 1);
    const metrics = { forecastExcess: rows.reduce((sum, row) => sum + row.forecastExcess, 0) / rows.length,
      realizedBrier: rows.reduce((sum, row) => sum + row.realizedBrier, 0) / rows.length,
      statusAccuracy: rows.reduce((sum, row) => sum + row.statusCorrect, 0) / rows.length,
      certificateValidity: rows.reduce((sum, row) => sum + row.certificateValid, 0) / rows.length,
      changedConclusionCount: changed.length, correctionPropagationAccuracy: changed.length ? changed.reduce((sum, row) => sum + row.statusCorrect, 0) / changed.length : 1,
      retainedSupportedCount: retained.length, retainedSupportAccuracy: retained.length ? retained.reduce((sum, row) => sum + row.statusCorrect, 0) / retained.length : 1,
      replacements: this.#spec.axes.corrections, withdrawals: this.#spec.axes.uncertainty };
    this.done = true; this.#phase = 'terminal'; this.#result = { kind: 'terminal', metrics, conclusions: rows };
    this.#history.push({ action: clone(action) });
    return clone(this.#result);
  }
  audit() { return clone({ correction: this.#correction, hiddenAssignment: this.#world, history: this.#history, result: this.#result }); }
}
export const create = options => new RevisionGame(options);
