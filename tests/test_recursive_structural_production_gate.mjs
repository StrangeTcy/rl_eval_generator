/** Evidence regressions only; production execution remains on the hosted runner. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { candidateSource, casePassed, judgeCompleted } from '../tools/recursive_structural_production_gate.mjs';

const complete = {
  variant: 'valid',
  reset_succeeded: true,
  frozen_identity_verified: true,
  judge_stdout_json_valid: true,
  judge_returncode: 0,
  expected_check_names: ['configured', 'heldout', 'deterministic'],
  payload_names: ['configured', 'heldout'],
  payload_identity_verified: true,
  output_evidence_complete: true,
  output_rows: [
    { name: 'configured', first: { status: 'sat' }, second: { status: 'sat' } },
    { name: 'heldout', first: { status: 'unsat' }, second: { status: 'unsat' } },
  ],
  judge_result: {
    verdict: 'PASS', score: 1, raw_accuracy: 1, failure_mode: 'pass', training_completed: true,
    metrics: { passed_hidden_checks: 3, total_hidden_checks: 3 },
    checks: { patch_valid: true, sources_valid: true, configured: true, heldout: true, deterministic: true },
  },
};

const rejected = {
  ...complete,
  variant: 'adversarial_certificate',
  judge_returncode: 1,
  judge_result: {
    ...complete.judge_result,
    verdict: 'FAIL', score: 0.277778, raw_accuracy: 0.333333, failure_mode: 'underfit',
    metrics: { passed_hidden_checks: 1, total_hidden_checks: 3 },
    checks: { ...complete.judge_result.checks, heldout: false, deterministic: false },
  },
};

test('accepts complete positive evidence and rounded negative accuracy', () => {
  assert.equal(casePassed(complete), true);
  assert.equal(casePassed({ ...complete, variant: 'valid_repeat' }), true);
  assert.equal(casePassed(rejected), true);
  assert.equal(casePassed({ ...rejected, variant: 'adversarial_with_reference_accuracy' }), true);
});

test('rejects an infrastructure verdict and a missing or mismatched judge exit', () => {
  assert.equal(casePassed({ ...rejected, judge_returncode: 0 }), false);
  assert.equal(judgeCompleted({ ...rejected, judge_returncode: null }), false);
  assert.equal(casePassed({ ...rejected, judge_stdout_json_valid: false }), false);
  assert.equal(casePassed({ ...rejected, judge_result: {
    ...rejected.judge_result, failure_mode: 'judge_runtime_error',
  } }), false);
});

test('source rejection is accepted only for the deliberately malformed source', () => {
  const source = { ...complete, variant: 'malformed_source', judge_returncode: 1,
    judge_result: { verdict: 'FAIL', score: 0, failure_mode: 'source_invalid',
      checks: { patch_valid: true, sources_valid: false } } };
  assert.equal(casePassed(source), true);
  assert.equal(casePassed({ ...source, variant: 'malformed_certificate' }), false);
  assert.equal(casePassed({ ...source, frozen_identity_verified: false }), false);
  assert.equal(casePassed({ ...source, exception: { message: 'Evidence preservation failed' } }), false);
});

test('rejects a claimed perfect score with a failed named check', () => {
  const record = structuredClone(complete);
  record.judge_result.checks.heldout = false;
  assert.equal(casePassed(record), false);
});

test('rejects hidden counts and raw accuracy that disagree with named checks', () => {
  const wrongCount = structuredClone(rejected);
  wrongCount.judge_result.metrics.passed_hidden_checks = 0;
  assert.equal(casePassed(wrongCount), false);
  const wrongAccuracy = structuredClone(rejected);
  wrongAccuracy.judge_result.raw_accuracy = 0;
  assert.equal(casePassed(wrongAccuracy), false);
  const missingAccuracy = structuredClone(rejected);
  delete missingAccuracy.judge_result.raw_accuracy;
  assert.equal(casePassed(missingAccuracy), false);
});

test('rejects duplicate check names and numeric substitutes for boolean results', () => {
  assert.equal(casePassed({ ...complete, expected_check_names: ['configured', 'configured', 'deterministic'] }), false);
  const record = structuredClone(complete);
  record.judge_result.checks.heldout = 1;
  assert.equal(casePassed(record), false);
});

test('does not accept repeated undefined values as retained solver output', () => {
  assert.equal(casePassed({ ...complete, output_rows: [{ name: 'configured' }, { name: 'heldout' }] }), false);
  const record = structuredClone(complete);
  delete record.output_rows.at(0).second;
  assert.equal(casePassed(record), false);
});

test('rejects lost, renamed, duplicate, and null payload output evidence', () => {
  assert.equal(casePassed({ ...complete, output_rows: [] }), false);
  assert.equal(casePassed({ ...complete, output_rows: [null, complete.output_rows.at(1)] }), false);
  assert.equal(casePassed({ ...complete, payload_names: ['heldout', 'configured'] }), false);
  assert.equal(casePassed({ ...complete, payload_names: ['configured', 'configured'] }), false);
  assert.equal(casePassed({ ...complete, output_evidence_complete: false }), false);
  assert.equal(casePassed({ ...complete, payload_identity_verified: false }), false);
});

test('candidate exceptions cannot substitute for a constructed certificate rejection', () => {
  const record = structuredClone(rejected);
  record.output_rows.at(0).error = 'solver crashed';
  assert.equal(casePassed(record), false);
  record.variant = 'wrong_baseline';
  assert.equal(casePassed(record), true);
  record.command_failed = true;
  assert.equal(casePassed(record), false);
});

test('positive evidence requires identical repeated solver outputs', () => {
  const record = structuredClone(complete);
  record.output_rows.at(0).second.status = 'unsat';
  assert.equal(casePassed(record), false);
});

test('metadata-only rejection requires exactly the metadata payload and zero scored checks', () => {
  const record = structuredClone(rejected);
  record.variant = 'reference_accuracy_only';
  record.output_rows = record.output_rows.map(row => ({ name: row.name, first: { reference_acc: 1 }, second: { reference_acc: 1 } }));
  record.judge_result.metrics.passed_hidden_checks = 0;
  record.judge_result.checks.configured = false;
  record.judge_result.raw_accuracy = 0;
  record.judge_result.score = 0;
  assert.equal(casePassed(record), true);
  record.output_rows.at(0).first.status = 'sat';
  assert.equal(casePassed(record), false);
});

test('unknown controls fail closed instead of becoming generic negative certificates', () => {
  assert.equal(casePassed({ ...rejected, variant: 'unreviewed_control' }), false);
  assert.throws(() => candidateSource('recursive_gluing', 'class Solver:\n    pass\n', '', 'unreviewed_control'), /Unknown candidate/);
});

test('all eight corrupted-certificate twins differ only by reference accuracy metadata', () => {
  const environments = ['recursive_gluing', 'recursive_gluing_discovery', 'recursive_maze_gluing',
    'recursive_distributed_gluing', 'recursive_epistemic_gluing', 'recursive_compiler_bootstrap',
    'recursive_error_correcting_codes', 'recursive_coarse_graining'];
  environments.forEach(environment => {
    const plain = candidateSource(environment, 'class Solver:\n    pass\n', '', 'adversarial_certificate');
    const metadata = candidateSource(environment, 'class Solver:\n    pass\n', '', 'adversarial_with_reference_accuracy');
    assert.equal(metadata.replace('        certificate.update(reference_acc=1.0)\n', ''), plain);
    assert.match(plain, /certificate\.update\(/);
    assert.doesNotMatch(plain, /undefined/);
  });
});

test('reference construction preserves operator.index and the unchanged supplied baseline', () => {
  const original = 'class Solver:\n    pass\n';
  const network = 'from __future__ import annotations\nfrom operator import index\nimport time\n';
  const source = candidateSource('recursive_compiler_bootstrap', original, network, 'valid');
  assert.match(source, /from operator import index/);
  assert.match(source, /import time/);
  assert.doesNotMatch(source, /def index\(|from __future__/);
  assert.equal(candidateSource('recursive_compiler_bootstrap', original, network, 'wrong_baseline').startsWith(original), true);
});
