/** Candidate-specific forecasts of a finite synthetic document evaluator. */
export const definition = {
  id: 'evaluator_prediction', title: 'Predict a document evaluator',
  description: 'Revise synthetic factual reports and forecast a withheld rubric score; report factual quality separately.',
  axes: [
    { id: 'criteria', description: 'Number of criteria used by every evaluator.', class: 'structural', levels: { easy: 3, medium: 4, hard: 5 } },
    { id: 'rubrics', description: 'Number of distinct possible criterion-weight vectors.', class: 'information', levels: { easy: 2, medium: 4, hard: 6 } },
    { id: 'candidates', description: 'Number of reports available for selection and revision.', class: 'action_space', levels: { easy: 2, medium: 4, hard: 6 } },
    { id: 'revisions', description: 'Maximum visible document edits; greater depth expands planning as well as resources.', class: 'resource', levels: { easy: 0, medium: 1, hard: 2 } },
    { id: 'uncertainty', description: 'Prior weight on the first rubric; every other rubric has weight one.', class: 'information', levels: { easy: 9, medium: 3, hard: 1 } },
  ],
  claims: ['Finite rubric prediction and revision under a declared prior.', 'Prediction after selection and factual quality are distinct measured outcomes.'],
  controls: ['No target scores before terminal submission.', 'No-revision and factual-quality-first policies.', 'A first-rubric certainty ablation.', 'Complete public finite revision planner.'],
};

class Random {
  constructor(seed) { if (!Number.isInteger(seed)) throw new Error('integer seed required'); this.state = seed >>> 0 || 0x6d2b79f5; }
  next(n) { this.state ^= this.state << 13; this.state ^= this.state >>> 17; this.state ^= this.state << 5; return (this.state >>> 0) % n; }
  shuffle(values) { const result = [...values]; for (let i = result.length - 1; i > 0; i--) { const j = this.next(i + 1); [result[i], result[j]] = [result[j], result[i]]; } return result; }
}
const clone = value => structuredClone(value);
const close = (object, keys) => object && typeof object === 'object' && !Array.isArray(object) && Object.keys(object).sort().join(',') === [...keys].sort().join(',');
const resolveAxes = options => {
  if (!close(options.axes ?? {}, Object.keys(options.axes ?? {}))) throw new Error('axis object required');
  if (Object.keys(options.axes ?? {}).some(id => !definition.axes.some(axis => axis.id === id))) throw new Error('unknown axis');
  return Object.fromEntries(definition.axes.map(axis => {
    const level = options.axes?.[axis.id] ?? 'easy';
    if (!Object.hasOwn(axis.levels, level)) throw new Error('unknown axis level');
    return [axis.id, axis.levels[level]];
  }));
};

export const features = (document, source, criteria) => {
  const facts = new Map(source.facts.map(fact => [fact.id, fact.value]));
  const correct = document.claims.filter(claim => facts.get(claim.fact) === claim.value);
  const covered = new Set(correct.map(claim => claim.fact));
  const required = source.required;
  return [correct.length / document.claims.length,
    required.filter(id => covered.has(id)).length / required.length,
    Math.min(1, required.length / document.claims.length),
    document.caveat ? 1 : 0, document.example ? 1 : 0].slice(0, criteria);
};
export const quality = (document, source) => {
  const values = features(document, source, 3);
  return (values[0] + values[1]) / 2;
};
export const rubricScore = (document, source, weights) => {
  const values = features(document, source, weights.length);
  return values.reduce((sum, value, i) => sum + value * weights[i], 0) / weights.reduce((sum, weight) => sum + weight, 0);
};

const editsFor = (document, source, criteria) => {
  const facts = new Map(source.facts.map(fact => [fact.id, fact.value]));
  const changes = [];
  document.claims.forEach((claim, index) => {
    if (facts.get(claim.fact) !== claim.value) changes.push({ id: `correct_${index}`, operation: 'correct', index, fact: claim.fact, value: facts.get(claim.fact) });
    if (document.claims.slice(0, index).some(previous => previous.fact === claim.fact)) changes.push({ id: `remove_${index}`, operation: 'remove', index });
  });
  source.required.forEach(fact => {
    if (!document.claims.some(claim => claim.fact === fact && claim.value === facts.get(fact))) changes.push({ id: `add_${fact}`, operation: 'add', fact, value: facts.get(fact) });
  });
  if (criteria >= 4 && !document.caveat) changes.push({ id: 'add_caveat', operation: 'caveat' });
  if (criteria >= 5 && !document.example) changes.push({ id: 'add_example', operation: 'example' });
  return changes;
};
const edited = (document, edit) => {
  const result = clone(document);
  if (edit.operation === 'correct') result.claims[edit.index].value = edit.value;
  else if (edit.operation === 'remove') result.claims.splice(edit.index, 1);
  else if (edit.operation === 'add') result.claims.push({ fact: edit.fact, value: edit.value });
  else if (edit.operation === 'caveat') result.caveat = true;
  else if (edit.operation === 'example') result.example = true;
  else throw new Error('unknown edit operation');
  return result;
};
const expected = (document, view) => view.rubrics.reduce((sum, rubric) => sum + rubric.prior * rubricScore(document, view.source, rubric.weights), 0);
const terminal = (view, mode = 'expected') => {
  const predictions = view.documents.map(document => ({ candidateId: document.id,
    score: mode === 'certainty' ? rubricScore(document, view.source, view.rubrics[0].weights) : expected(document, view) }));
  const selected = view.documents.reduce((best, document) => {
    const value = mode === 'quality' ? quality(document, view.source) : predictions.find(row => row.candidateId === document.id).score;
    return value > best.value + 1e-12 ? { id: document.id, value } : best;
  }, { id: view.documents[0].id, value: -1 });
  return { kind: 'submit', selectedId: selected.id, predictions };
};

const planned = (view, documents, remaining) => {
  const current = Math.max(...documents.map(document => expected(document, view)));
  let best = { value: current, action: null };
  if (remaining === 0) return best;
  documents.forEach((document, index) => editsFor(document, view.source, view.axes.criteria).forEach(edit => {
    const next = documents.map((item, position) => position === index ? edited(item, edit) : item);
    const value = planned(view, next, remaining - 1).value;
    if (value > best.value + 1e-12) best = { value, action: { kind: 'revise', candidateId: document.id, editId: edit.id,
      predictedBefore: expected(document, view), predictedAfter: expected(next[index], view) } };
  }));
  return best;
};

export const reference = view => planned(view, view.documents, view.remainingRevisions).action ?? terminal(view);
export const baselines = {
  no_revision: view => terminal(view),
  quality_first: view => terminal(view, 'quality'),
  first_rubric_certainty: view => terminal(view, 'certainty'),
};

export class EvaluatorGame {
  #target;
  #documents;
  #source;
  #rubrics;
  #history;
  #remaining;
  #result;
  #revisionForecasts;
  constructor(options = {}) {
    this.axes = resolveAxes(options);
    const random = new Random(options.seed ?? 0), privateRandom = new Random(options.privateSeed ?? 0);
    const factCount = this.axes.criteria + 1;
    this.#source = { facts: Array.from({ length: factCount }, (_, i) => ({ id: `catalog_${i}`, label: `Catalog item ${i} has the marked property`, value: random.next(2) })), required: [] };
    this.#source.required = this.#source.facts.slice(0, 3).map(fact => fact.id);
    this.#documents = Array.from({ length: this.axes.candidates }, (_, index) => {
      const chosen = random.shuffle(this.#source.facts.slice(0, 3)).slice(0, 2 + random.next(2));
      const claims = chosen.map((fact, position) => ({ fact: fact.id, value: position === 0 && index % 2 === 0 ? 1 - fact.value : fact.value }));
      if (index % 3 === 1) claims.push(clone(claims[0]), clone(claims[0]));
      return { id: `report_${index}`, claims, caveat: random.next(2) === 1, example: random.next(2) === 1 };
    });
    const base = random.shuffle(Array.from({ length: this.axes.criteria }, (_, index) => index + 1));
    const vectors = [...Array.from({ length: base.length }, (_, shift) => [...base.slice(shift), ...base.slice(0, shift)]),
      ...Array.from({ length: base.length }, (_, shift) => { const reversed = [...base].reverse(); return [...reversed.slice(shift), ...reversed.slice(0, shift)]; })];
    const unique = vectors.filter((vector, index) => vectors.findIndex(other => JSON.stringify(other) === JSON.stringify(vector)) === index).slice(0, this.axes.rubrics);
    const total = this.axes.uncertainty + unique.length - 1;
    this.#rubrics = unique.map((weights, index) => ({ id: `rubric_${index}`, weights, prior: (index === 0 ? this.axes.uncertainty : 1) / total }));
    const ticket = privateRandom.next(total);
    this.#target = ticket < this.axes.uncertainty ? 0 : ticket - this.axes.uncertainty + 1;
    this.#history = []; this.#revisionForecasts = []; this.#remaining = this.axes.revisions; this.done = false; this.#result = null;
  }
  view() {
    return clone({ family: definition.id, phase: this.done ? 'terminal' : 'prediction_and_revision', axes: this.axes,
      rules: 'A fixed hidden rubric scores the reports. Every possible weight vector and its prior is public. Source facts are true. Criterion features are: fraction of claims correct, fraction of required facts correctly covered, min(1, required-count/claim-count), presence of a caveat, presence of an example; use the first criteria-count features. Rubric score is the weighted feature mean in [0,1]. Factual quality is the mean of accuracy and coverage, independent of rubric weights. Each revision must predict that candidate score before and after the edit before the edit is applied. Revisions reveal only edited documents. No target evaluator score is returned until terminal submission.',
      source: this.#source, documents: this.#documents, rubrics: this.#rubrics,
      permittedEdits: this.#documents.map(document => ({ candidateId: document.id, edits: editsFor(document, this.#source, this.axes.criteria) })),
      remainingRevisions: this.#remaining, history: this.#history,
      actionSchema: { revise: { kind: 'revise', candidateId: 'document ID', editId: 'currently permitted edit ID', predictedBefore: 'score in [0,1]', predictedAfter: 'score in [0,1]' },
        submit: { kind: 'submit', selectedId: 'document ID', predictions: 'one {candidateId,score in [0,1]} per current document' } } });
  }
  submit(action) {
    if (this.done) throw new Error('episode closed');
    if (action?.kind === 'revise') {
      if (!close(action, ['kind', 'candidateId', 'editId', 'predictedBefore', 'predictedAfter']) || this.#remaining < 1 ||
          [action.predictedBefore, action.predictedAfter].some(value => !Number.isFinite(value) || value < 0 || value > 1)) throw new Error('invalid or exhausted revision');
      const index = this.#documents.findIndex(document => document.id === action.candidateId);
      if (index < 0) throw new Error('unknown candidate');
      const edit = editsFor(this.#documents[index], this.#source, this.axes.criteria).find(item => item.id === action.editId);
      if (!edit) throw new Error('unavailable edit');
      const next = edited(this.#documents[index], edit);
      this.#revisionForecasts.push({ before: clone(this.#documents[index]), after: clone(next), predictedBefore: action.predictedBefore, predictedAfter: action.predictedAfter });
      this.#documents[index] = next; this.#remaining--;
      const observation = { kind: 'revision', candidateId: next.id, document: clone(next), remainingRevisions: this.#remaining };
      this.#history.push({ action: clone(action), observation: clone(observation) });
      return observation;
    }
    if (!close(action, ['kind', 'selectedId', 'predictions']) || action.kind !== 'submit' || !Array.isArray(action.predictions) || action.predictions.length !== this.#documents.length ||
        new Set(action.predictions.map(row => row?.candidateId)).size !== this.#documents.length || action.predictions.some(row => !close(row, ['candidateId', 'score']) || !this.#documents.some(document => document.id === row.candidateId) || !Number.isFinite(row.score) || row.score < 0 || row.score > 1)) throw new Error('one bounded forecast per document required');
    const selected = this.#documents.find(document => document.id === action.selectedId);
    if (!selected) throw new Error('unknown selected document');
    const view = this.view();
    const rows = this.#documents.map(document => {
      const forecast = action.predictions.find(row => row.candidateId === document.id).score;
      const mean = expected(document, view), actual = rubricScore(document, this.#source, this.#rubrics[this.#target].weights);
      const conditionalMSE = this.#rubrics.reduce((sum, rubric) => sum + rubric.prior * (forecast - rubricScore(document, this.#source, rubric.weights)) ** 2, 0);
      return { candidateId: document.id, forecast, expectedScore: mean, targetScore: actual, factualQuality: quality(document, this.#source),
        forecastExcess: (forecast - mean) ** 2, conditionalMSE, realizedSquaredError: (forecast - actual) ** 2 };
    });
    const chosen = rows.find(row => row.candidateId === selected.id);
    const editErrors = this.#revisionForecasts.flatMap(row => [['before', 'predictedBefore'], ['after', 'predictedAfter']].map(([documentKey, predictionKey]) => ({
      excess: (row[predictionKey] - expected(row[documentKey], view)) ** 2,
      realized: (row[predictionKey] - rubricScore(row[documentKey], this.#source, this.#rubrics[this.#target].weights)) ** 2,
    })));
    const metrics = { forecastExcess: rows.reduce((sum, row) => sum + row.forecastExcess, 0) / rows.length,
      forecastMSE: rows.reduce((sum, row) => sum + row.realizedSquaredError, 0) / rows.length,
      conditionalForecastMSE: rows.reduce((sum, row) => sum + row.conditionalMSE, 0) / rows.length,
      selectedForecastExcess: chosen.forecastExcess, selectedForecastMSE: chosen.realizedSquaredError,
      expectedSelectionRegret: Math.max(...rows.map(row => row.expectedScore)) - chosen.expectedScore,
      realizedSelectionRegret: Math.max(...rows.map(row => row.targetScore)) - chosen.targetScore,
      factualQuality: chosen.factualQuality, factualQualityRegret: Math.max(...rows.map(row => row.factualQuality)) - chosen.factualQuality,
      evaluatorScore: chosen.targetScore, revisionsUsed: this.axes.revisions - this.#remaining,
      revisionForecastCount: editErrors.length,
      revisionForecastExcess: editErrors.length ? editErrors.reduce((sum, row) => sum + row.excess, 0) / editErrors.length : 0,
      revisionForecastMSE: editErrors.length ? editErrors.reduce((sum, row) => sum + row.realized, 0) / editErrors.length : 0 };
    this.done = true; this.#result = { kind: 'terminal', metrics, selectedId: selected.id, candidates: rows };
    this.#history.push({ action: clone(action) });
    return clone(this.#result);
  }
  audit() { return clone({ targetRubric: this.#rubrics[this.#target], documents: this.#documents, revisionForecasts: this.#revisionForecasts, history: this.#history, result: this.#result }); }
}
export const create = options => new EvaluatorGame(options);
