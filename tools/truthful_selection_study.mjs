/** Deterministic supplied-policy controls, with replayable scoring evidence. */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { Ratio, SelectionTask, SelectionFamily } from '../arena/inquiry/selection_laws.mjs';

const ROOT = fileURLToPath(new URL('../', import.meta.url));
const SOURCES = ['arena/inquiry/selection_laws.mjs', 'tools/truthful_selection_study.mjs'];

export class SelectionStudy {
  static hash(text) { return createHash('sha256').update(text).digest('hex'); }
  static sourceHashes() { return Object.fromEntries(SOURCES.map(path => [path, this.hash(readFileSync(join(ROOT, path)))])); }

  static design() {
    return {
      schema: 'truthful-selection-design/1',
      severities: [2, 3, 4, 5, 6, 7, 8],
      laws: ['favors-0', 'favors-1', 'uninformative'],
      priors: ['common', 'observer-0', 'observer-1'],
      policies: ['selection', 'content'],
      unit: 'finite probability specification; deterministic parameter grid',
      score: 'expected multiclass Brier and zero-one decision loss conditional on the observed true message',
      evidenceLimit: 'Supplied-law and content-only scripted controls; no evaluated-model capability or population inference.',
    };
  }

  static execute(design) {
    if (JSON.stringify(design) !== JSON.stringify(this.design())) throw new Error('unsupported or altered prospective design');
    return design.severities.flatMap(severity => design.laws.flatMap(law => design.priors.map(prior => {
      const spec = SelectionFamily.create(severity, law, prior);
      const task = new SelectionTask(spec);
      return {
        severity, law, prior, spec, public: JSON.parse(task.view()),
        policies: design.policies.map(policy => {
          const instance = new SelectionTask(spec);
          const answer = instance.answer(policy);
          return { policy, answer, score: instance.submit(answer) };
        }),
      };
    })));
  }

  static summary(cases) {
    const groups = ['favors-0', 'favors-1', 'uninformative'].flatMap(law => ['selection', 'content'].map(policy => {
      const scores = cases.filter(item => item.law === law).map(item => item.policies.find(value => value.policy === policy).score);
      return {
        law, policy, cases: scores.length,
        meanDecisionRegret: String(scores.reduce((sum, score) => sum.plus(Ratio.parse(score.decisionRegret)), new Ratio(0)).over(new Ratio(scores.length))),
        meanForecastExcess: String(scores.reduce((sum, score) => sum.plus(Ratio.parse(score.forecastExcess)), new Ratio(0)).over(new Ratio(scores.length))),
        nonzeroDecisionRegret: scores.filter(score => score.decisionRegret !== '0').length,
        nonzeroForecastExcess: scores.filter(score => score.forecastExcess !== '0').length,
      };
    }));
    const reversals = cases.filter(item => item.law === 'favors-0').filter(item => {
      const twin = cases.find(candidate => candidate.severity === item.severity && candidate.prior === item.prior && candidate.law === 'favors-1');
      return item.policies.find(value => value.policy === 'selection').score.decision !== twin.policies.find(value => value.policy === 'selection').score.decision;
    }).length;
    const disagreements = cases.filter(item => item.prior === 'observer-0').filter(item => {
      const twin = cases.find(candidate => candidate.severity === item.severity && candidate.law === item.law && candidate.prior === 'observer-1');
      return JSON.stringify(item.policies.find(value => value.policy === 'selection').score.posterior) !== JSON.stringify(twin.policies.find(value => value.policy === 'selection').score.posterior);
    }).length;
    return { schema: 'truthful-selection-summary/1', cases: cases.length, scoredAnswers: cases.length * 2, selectionLawDecisionReversals: reversals, priorDisagreementPairs: disagreements, groups };
  }

  static run(directory) {
    const destination = resolve(directory), design = this.design();
    const frozen = { design, sourceSha256: this.sourceHashes(), node: process.version };
    mkdirSync(destination);
    writeFileSync(join(destination, 'design.json'), JSON.stringify(frozen, null, 2) + '\n', { flag: 'wx' });
    const cases = this.execute(design), summary = this.summary(cases);
    const record = { schema: 'truthful-selection-record/1', designSha256: this.hash(JSON.stringify(frozen)), cases, summary };
    const text = JSON.stringify(record, null, 2) + '\n';
    writeFileSync(join(destination, 'records.json'), text, { flag: 'wx' });
    writeFileSync(join(destination, 'records.sha256'), this.hash(text) + '\n', { flag: 'wx' });
    return { directory: destination, ...summary, replay: this.replay(destination) };
  }

  static replay(directory) {
    const frozen = JSON.parse(readFileSync(join(directory, 'design.json'), 'utf8'));
    if (JSON.stringify(frozen.sourceSha256) !== JSON.stringify(this.sourceHashes())) throw new Error('source identity changed');
    if (frozen.node !== process.version) throw new Error('runtime identity changed');
    const text = readFileSync(join(directory, 'records.json'), 'utf8');
    if (this.hash(text) !== readFileSync(join(directory, 'records.sha256'), 'utf8').trim()) throw new Error('record checksum mismatch');
    const recorded = JSON.parse(text);
    const cases = this.execute(frozen.design);
    const expected = { schema: 'truthful-selection-record/1', designSha256: this.hash(JSON.stringify(frozen)), cases, summary: this.summary(cases) };
    if (JSON.stringify(recorded) !== JSON.stringify(expected)) throw new Error('replay divergence');
    return { status: 'passed', casesChecked: cases.length, answersChecked: cases.length * 2 };
  }
}

class CLI {
  run(args) {
    if (args.length === 2 && args[0] === 'run') process.stdout.write(JSON.stringify(SelectionStudy.run(args[1]), null, 2) + '\n');
    else if (args.length === 2 && args[0] === 'replay') process.stdout.write(JSON.stringify(SelectionStudy.replay(args[1])) + '\n');
    else if (args.length === 4 && args[0] === 'show') process.stdout.write(new SelectionTask(SelectionFamily.create(Number(args[1]), args[2], args[3])).view() + '\n');
    else if (args.length === 5 && args[0] === 'score') process.stdout.write(JSON.stringify(new SelectionTask(SelectionFamily.create(Number(args[1]), args[2], args[3])).submit(args[4])) + '\n');
    else throw new Error('usage: truthful_selection_study.mjs run DIRECTORY | replay DIRECTORY | show SEVERITY LAW PRIOR | score SEVERITY LAW PRIOR "answer ..."');
  }
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { new CLI().run(process.argv.slice(2)); }
  catch (error) { process.stderr.write(error.message + '\n'); process.exitCode = 1; }
}
