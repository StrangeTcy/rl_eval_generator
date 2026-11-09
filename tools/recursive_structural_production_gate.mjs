#!/usr/bin/env node
/** Hosted evidence harness for the unmodified env_runner production CLI.
 * The older Python harness is preserved as historical launch evidence.
 * No model provider, training run, downloaded model, or replacement judge is used.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { isDeepStrictEqual } from 'node:util';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const EVIDENCE = 'docs/artifacts/recursive-structural-validation-2026-11-02';
const REVIEW = 'docs/reports/2026-10-28-structural-source-review.json';
const ENVIRONMENTS = [
  ['recursive_gluing', 'easy,easy,easy,easy'],
  ['recursive_gluing_discovery', 'easy,easy,easy,easy,easy'],
  ['recursive_maze_gluing', 'easy,easy,easy,easy'],
  ['recursive_distributed_gluing', 'easy,easy,easy'],
  ['recursive_epistemic_gluing', 'easy,easy,easy,easy'],
  ['recursive_compiler_bootstrap', 'easy,easy,easy'],
  ['recursive_error_correcting_codes', 'easy,easy,easy'],
  ['recursive_coarse_graining', 'easy,easy,easy'],
];
const VARIANTS = ['valid', 'valid_repeat', 'wrong_baseline', 'incomplete',
  'malformed_source', 'malformed_certificate', 'adversarial_certificate',
  'adversarial_with_reference_accuracy', 'reference_accuracy_only'];
const SCORING_MODES = new Set(['pass', 'underfit', 'overfit_visible_tests', 'specification_gaming']);
const STAGES = ['environment_initialization', 'frozen_identity', 'submission_parsing',
  'certificate_parsing', 'independent_verification', 'production_judge',
  'pytorch_output_roundtrip', 'final_scoring', 'deterministic_repetition'];

function argument(name, fallback) {
  const position = process.argv.indexOf(name);
  return position < 0 ? fallback : process.argv[position + 1];
}
function digest(value) { return crypto.createHash('sha256').update(value).digest('hex'); }
function readJson(filename) { return JSON.parse(fs.readFileSync(filename, 'utf8').replace(/^\uFEFF/, '')); }
function writeJson(filename, value) {
  fs.mkdirSync(path.dirname(filename), { recursive: true });
  fs.writeFileSync(filename, `${JSON.stringify(value, null, 2)}\n`);
}
function relative(filename) { return path.relative(ROOT, filename).split(path.sep).join('/'); }
function descendants(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const filename = path.join(directory, entry.name);
    return entry.isDirectory() ? descendants(filename) : entry.isFile() ? [filename] : [];
  });
}
function within(directory, filename) {
  const suffix = path.relative(path.resolve(directory), path.resolve(filename));
  if (suffix === '' || suffix === '..' || suffix.startsWith(`..${path.sep}`) || path.isAbsolute(suffix)) {
    throw new Error(`Path must be a child of ${directory}: ${filename}`);
  }
  return path.resolve(filename);
}
function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  }
  return value;
}
function unexecuted() {
  return Object.fromEntries(STAGES.map(name => [name, { status: 'unexecuted' }]));
}

/** Only the trusted emitted judge JSON and matching process exit establish execution. */
export function judgeCompleted(record) {
  const result = record.judge_result;
  return !!result && record.judge_stdout_json_valid === true &&
    Number.isFinite(result.score) && result.score >= 0 && result.score <= 1 &&
    ((result.verdict === 'PASS' && result.score === 1 && record.judge_returncode === 0 && result.failure_mode === 'pass') ||
     (result.verdict === 'FAIL' && result.score < 1 && record.judge_returncode === 1 && result.failure_mode !== 'pass'));
}

/** Infrastructure failures and missing evidence can never satisfy a negative control. */
export function casePassed(record) {
  if (!VARIANTS.includes(record.variant) || record.exception || !record.reset_succeeded || !record.frozen_identity_verified ||
      !judgeCompleted(record) || record.command_failed || record.evidence_errors?.length) return false;
  const result = record.judge_result;
  if (record.variant === 'malformed_source') {
    return result.verdict === 'FAIL' && result.failure_mode === 'source_invalid' &&
      result.checks?.patch_valid === true && result.checks?.sources_valid === false;
  }
  const names = record.expected_check_names;
  if (!Array.isArray(names) || names.length === 0 || new Set(names).size !== names.length ||
      !SCORING_MODES.has(result.failure_mode) || result.checks?.patch_valid !== true ||
      result.checks?.sources_valid !== true || result.training_completed !== true ||
      result.metrics?.total_hidden_checks !== names.length ||
      !names.every(name => typeof result.checks?.[name] === 'boolean') ||
      !record.output_evidence_complete || !record.payload_identity_verified ||
      !Array.isArray(record.payload_names) || record.payload_names.length === 0 ||
      new Set(record.payload_names).size !== record.payload_names.length ||
      !Array.isArray(record.output_rows) || record.output_rows.length !== record.payload_names.length ||
      !record.output_rows.every((row, index) => row !== null && typeof row === 'object' &&
        row.name === record.payload_names[index] &&
        (Object.hasOwn(row, 'error') || (Object.hasOwn(row, 'first') && Object.hasOwn(row, 'second'))))) return false;
  const accepted = names.filter(name => result.checks[name]).length;
  if (result.metrics.passed_hidden_checks !== accepted || !Number.isFinite(result.raw_accuracy) ||
      Math.abs(result.raw_accuracy - accepted / names.length) > 0.00000051) return false;
  if (record.variant === 'valid' || record.variant === 'valid_repeat') {
    return result.verdict === 'PASS' && result.score === 1 &&
      result.metrics.passed_hidden_checks === names.length && names.every(name => result.checks[name]) &&
      record.output_rows.every(row => !Object.hasOwn(row, 'error') && isDeepStrictEqual(row.first, row.second));
  }
  if (result.verdict !== 'FAIL' || result.score >= 1 || result.metrics.passed_hidden_checks >= names.length) return false;
  // The supplied baseline is retained verbatim; report its candidate errors explicitly.
  // Constructed certificate controls must reach the verifier with actual outputs.
  if (record.variant !== 'wrong_baseline' && record.output_rows.some(row => Object.hasOwn(row, 'error'))) return false;
  if (record.variant === 'reference_accuracy_only') {
    return result.metrics.passed_hidden_checks === 0 && result.score === 0 &&
      record.output_rows.every(row => isDeepStrictEqual(row.first, { reference_acc: 1 }) &&
        isDeepStrictEqual(row.second, { reference_acc: 1 }));
  }
  return true;
}

export function candidateSource(environment, original, network, variant) {
  if (!VARIANTS.includes(variant)) throw new Error(`Unknown candidate variant: ${variant}`);
  const match = original.match(/^class\s+([A-Za-z_][A-Za-z_0-9]*)\s*:/m);
  if (!match) throw new Error('Generated solver has no unambiguous model class');
  const model = match[1];
  if (variant === 'wrong_baseline') return `${original}\n# Hosted production negative control: unchanged supplied algorithm.\n`;
  if (variant === 'malformed_source') return `class ${model}(\n`;
  if (variant === 'malformed_certificate') return `class ${model}:\n    def solve(self, instance):\n        return ("malformed-certificate",)\n`;
  if (variant === 'incomplete' || variant === 'reference_accuracy_only') {
    return `class ${model}:\n    def solve(self, instance):\n        certificate = instance.copy()\n        certificate.clear()\n` +
      (variant === 'reference_accuracy_only' ? '        certificate.update(reference_acc=1.0)\n' : '') +
      '        return certificate\n';
  }
  // Preserve the reviewed reference implementation. __future__ and json are not
  // production-allowlisted; json is only used by discovery reporting helpers.
  // operator.index and time remain unchanged because both imports are allowed.
  const reviewed = network.replace(/^from __future__ import annotations\r?\n/gm, '')
    .replace(/^import json\r?\n/gm, '');
  const entry = environment === 'recursive_gluing' ? 'reference_solve' : 'reference_certificate';
  const mutations = {
    recursive_gluing: '        certificate.update(status="unsat")\n',
    recursive_gluing_discovery: '        certificate.update(status="unsat")\n',
    recursive_maze_gluing: '        certificate.update(status="unsat")\n',
    recursive_distributed_gluing: '        certificate.update(status="unsat")\n',
    recursive_error_correcting_codes: '        certificate.update(status="unsat")\n',
    recursive_epistemic_gluing: '        certificate.update(reachability=("corrupted-reachability", -1))\n',
    recursive_compiler_bootstrap: '        certificate.update(bootstrap=("corrupted-bootstrap", -1))\n',
    recursive_coarse_graining: '        certificate.update(table=((-1, -1), (-1, -1)))\n',
  };
  return `${reviewed}\n\nclass ${model}:\n    def solve(self, instance):\n        certificate = ${entry}(instance)\n` +
    (variant === 'adversarial_certificate' || variant === 'adversarial_with_reference_accuracy' ? mutations[environment] : '') +
    (variant === 'adversarial_with_reference_accuracy' ? '        certificate.update(reference_acc=1.0)\n' : '') +
    '        return certificate\n';
}

function frozenIdentifiers() {
  const log = fs.readFileSync(path.join(ROOT, EVIDENCE, 'eight-gate-production.log'), 'utf8');
  return Object.fromEntries(ENVIRONMENTS.map(([environment, difficulty]) => {
    const body = log.split(`ENV=${environment} COMMAND=reset`)[1]?.split('RESET_EXIT_STATUS=')[0];
    if (!body) throw new Error(`Missing frozen reset evidence: ${environment}`);
    const record = JSON.parse(body.trim());
    if (record.info.seed !== 41 || record.info.difficulty !== difficulty) throw new Error(`Frozen settings mismatch: ${environment}`);
    return [environment, { generation_id: record.info.generation_id, pair_id: record.info.pair_id,
      seed: 41, difficulty, source: `${EVIDENCE}/eight-gate-production.log` }];
  }));
}

function sourceRecord() {
  const prior = readJson(path.join(ROOT, EVIDENCE, 'validation-record.json'));
  const sourceFiles = [
    ...Object.keys(prior.source_hashes).filter(name => name.startsWith('envs/cat_theo/recursive_')),
    'env_runner.py', 'generate_env.py', 'pyproject.toml', 'requirements.txt', 'requirements.lock',
    'shared/judge_lib.py', 'shared/source_validator.py', 'shared/patch_validator.py',
    'shared/generation_manifest.py', 'shared/latent_spec.py', 'shared/information_policy.py',
    'shared/Dockerfile.judge', '.github/workflows/recursive-structural-production-gate.yml',
    'tools/recursive_structural_production_gate.mjs', REVIEW, `${EVIDENCE}/validation-record.json`,
    'tests/test_recursive_structural_production_gate.mjs',
    `${EVIDENCE}/eight-gate-production.log`,
  ];
  return sourceFiles.map(filename => {
    const bytes = fs.readFileSync(path.join(ROOT, filename));
    const text = bytes.toString('utf8').replace(/\r\n/g, '\n');
    const expected = prior.source_hashes[filename] ?? null;
    const raw = digest(bytes);
    const lf = digest(text);
    const crlf = digest(text.replace(/\n/g, '\r\n'));
    return { path: filename, sha256: raw, normalized_lf_sha256: lf, historical_sha256: expected,
      historical_comparison: expected === null ? 'additional_execution_source' : expected === raw ? 'exact_bytes' :
        expected === lf || expected === crlf ? 'line_endings_only' : 'source_changed' };
  });
}

function stageEvidence(record) {
  const stages = record.stages;
  const result = record.judge_result;
  if (!judgeCompleted(record)) {
    stages.production_judge = { status: 'failed', reason: 'No complete trusted judge JSON with matching process exit' };
    return;
  }
  stages.production_judge = { status: 'passed', evidence: 'Raw stdout JSON and judge return code; production judge imports torch before submission validation' };
  stages.submission_parsing = { status: result.checks?.sources_valid ? 'passed' : 'rejected',
    patch_valid: result.checks?.patch_valid ?? null, sources_valid: result.checks?.sources_valid ?? null,
    evidence: result.stage_outcomes ?? {} };
  if (!record.output_evidence_complete) return;
  stages.pytorch_output_roundtrip = { status: 'passed', evidence: 'Production torch.save output read by production torch.load and preserved as eval_outputs.pt/JSON' };
  const completedScoring = SCORING_MODES.has(result.failure_mode) && result.training_completed === true &&
    Number.isInteger(result.metrics?.total_hidden_checks);
  if (!completedScoring) return;
  const positive = result.verdict === 'PASS';
  stages.certificate_parsing = positive ? { status: 'passed', evidence: 'All production named certificate checks accepted' } :
    { status: 'not_separately_observable', evidence: 'Production verifier combines certificate parsing and semantic rejection; individual parser reasons are not emitted' };
  stages.independent_verification = { status: positive ? 'passed' : 'rejected',
    evidence: 'Production named checks after independent verification', checks: record.named_checks,
    candidate_errors: record.output_rows.filter(row => Object.hasOwn(row, 'error')) };
  stages.final_scoring = { status: 'passed', candidate_verdict: result.verdict, score: result.score,
    raw_accuracy: result.raw_accuracy, expected_rejection: !positive };
  const repeatedOutputs = record.output_rows.every(row => !Object.hasOwn(row, 'error') &&
    isDeepStrictEqual(row.first, row.second));
  stages.deterministic_repetition = { status: repeatedOutputs ? 'passed' : 'failed',
    raw_output_repetition_equal: repeatedOutputs, production_combined_deterministic_check: result.checks?.deterministic,
    note: 'Production deterministic check also requires certificate validity; false for an invalid certificate is expected' };
}

async function runGate() {
  if (process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted') {
    throw new Error('This harness executes only on a GitHub-hosted Actions runner. No local execution is supported.');
  }
  const output = path.resolve(ROOT, argument('--output', 'docs/artifacts/recursive-structural-production-gate'));
  const frozenInputs = path.resolve(ROOT, argument('--frozen-inputs', 'tools/fixtures/recursive-structural-production'));
  within(ROOT, output);
  fs.mkdirSync(output, { recursive: true });
  const commands = [];
  const records = [];
  let commandNumber = 0;
  function command(executable, args, directory, extraEnvironment = {}, timeout = 1900000) {
    const id = `${String(++commandNumber).padStart(4, '0')}-${path.basename(executable)}`;
    const commandDirectory = path.join(directory, 'commands');
    fs.mkdirSync(commandDirectory, { recursive: true });
    const started = new Date().toISOString();
    const result = spawnSync(executable, args, { cwd: ROOT, env: { ...process.env, ...extraEnvironment },
      encoding: 'utf8', timeout, maxBuffer: 128 * 1024 * 1024 });
    const stdout = result.stdout ?? '';
    const stderr = result.stderr ?? '';
    fs.writeFileSync(path.join(commandDirectory, `${id}.stdout`), stdout);
    fs.writeFileSync(path.join(commandDirectory, `${id}.stderr`), stderr);
    const row = { id, executable, arguments: args, cwd: ROOT, started_at: started,
      finished_at: new Date().toISOString(), exit_code: result.status, signal: result.signal,
      error: result.error?.message ?? null, stdout: relative(path.join(commandDirectory, `${id}.stdout`)),
      stderr: relative(path.join(commandDirectory, `${id}.stderr`)) };
    commands.push(row);
    writeJson(path.join(output, 'commands.json'), commands);
    fs.appendFileSync(path.join(output, 'production-judge.log'), `${JSON.stringify(row)}\n`);
    return { ...row, stdout_text: stdout, stderr_text: stderr };
  }
  const expected = frozenIdentifiers();
  const sources = sourceRecord();
  const commit = command('git', ['rev-parse', 'HEAD'], output, {}, 30000).stdout_text.trim();
  const packages = command('python', ['-m', 'pip', 'list', '--format=json'], output, {}, 60000);
  const python = command('python', ['--version'], output, {}, 30000);
  const uname = command('uname', ['-a'], output, {}, 30000);
  const environment = { schema_version: 2, commit, requested_ref: process.env.GATE_TEST_REF ?? process.env.GITHUB_REF,
    workflow_ref: process.env.GITHUB_WORKFLOW_REF, workflow_sha: process.env.GITHUB_WORKFLOW_SHA,
    run_url: `${process.env.GITHUB_SERVER_URL}/${process.env.GITHUB_REPOSITORY}/actions/runs/${process.env.GITHUB_RUN_ID}`,
    run_attempt: process.env.GITHUB_RUN_ATTEMPT, runner_os: 'ubuntu-22.04', runner_environment: process.env.RUNNER_ENVIRONMENT,
    runner_image: process.env.ImageOS, runner_image_version: process.env.ImageVersion,
    platform: uname.stdout_text.trim(), python: python.stdout_text.trim(), node: process.version,
    packages: packages.exit_code === 0 ? JSON.parse(packages.stdout_text) : null,
    source_hashes: sources, frozen_instances: expected,
    source_comparison_note: 'Historical hashes remain unchanged. Exact bytes and line-ending-only differences are reported separately.',
    historical_harness: 'tools/recursive_structural_production_gate.py (preserved; not executed)' };
  writeJson(path.join(output, 'environment.json'), environment);
  writeJson(path.join(output, 'source-hashes.json'), sources);
  const setupErrors = [];
  if (sources.some(row => row.historical_comparison === 'source_changed')) setupErrors.push('Post-fix reviewed environment source changed');
  if (packages.exit_code !== 0 || python.exit_code !== 0 || !commit.match(/^[a-f0-9]{40}$/)) setupErrors.push('Environment capture failed');
  const installed = new Map((environment.packages ?? []).map(item => [item.name.toLowerCase(), item.version]));
  if (installed.get('torch') !== '2.5.1+cpu' || installed.get('torchvision') !== '0.20.1+cpu') setupErrors.push('Declared CPU PyTorch versions are not installed');
  if (!environment.python.startsWith('Python 3.11.')) setupErrors.push('Python 3.11 required');
  const payloadDigests = new Map();

  for (const [envName, difficulty] of ENVIRONMENTS) {
    const network = fs.readFileSync(path.join(ROOT, 'envs', 'cat_theo', envName, 'files/network.py'), 'utf8');
    const checksMatch = network.match(/^CHECK_NAMES\s*=\s*\(([\s\S]*?)^\)/m);
    const expectedChecks = checksMatch ? [...checksMatch[1].matchAll(/"([^"]+)"/g)].map(match => match[1]) : [];
    for (const variant of VARIANTS) {
      const caseDirectory = path.join(output, 'per-environment', envName, variant);
      fs.mkdirSync(caseDirectory, { recursive: true });
      const record = { environment: envName, variant, seed: 41, difficulty, expected_check_names: expectedChecks,
        expected_identity: expected[envName], stages: unexecuted(), reset_succeeded: false,
        frozen_identity_verified: false, evidence_errors: [], output_rows: [], output_evidence_complete: false,
        payload_identity_verified: false };
      let episodeDirectory;
      try {
        const episodeId = `hosted_${envName}_${variant}_${process.env.GITHUB_RUN_ATTEMPT ?? '1'}`;
        record.episode_id = episodeId;
        const runtimeDirectory = path.join(caseDirectory, 'runtime');
        fs.mkdirSync(runtimeDirectory, { recursive: true });
        const runtimeEnvironment = { TMPDIR: runtimeDirectory, PYTHONDONTWRITEBYTECODE: '1',
          HF_HUB_OFFLINE: '1', TRANSFORMERS_OFFLINE: '1', WANDB_MODE: 'disabled' };
        const reset = command('python', ['env_runner.py', 'reset', '--env', envName, '--difficulty', difficulty,
          '--seed', '41', '--episode-id', episodeId, '--max-steps', '1', '--sandbox', 'local', '--keep-workspace'],
        caseDirectory, runtimeEnvironment, 180000);
        if (reset.exit_code !== 0) throw new Error(`Environment reset exited ${reset.exit_code}: ${reset.error ?? reset.stderr_text.slice(-2000)}`);
        const resetResult = JSON.parse(reset.stdout_text);
        episodeDirectory = within(path.join(ROOT, '.episodes'), resetResult.info.episode_dir);
        const statePath = path.join(episodeDirectory, 'state.json');
        const state = readJson(statePath);
        record.reset_succeeded = true;
        record.stages.environment_initialization = { status: 'passed', evidence: 'env_runner reset CLI', generated_identity: state.provenance };
        writeJson(path.join(caseDirectory, 'fresh-reset-state.json'), state);

        // Load the original frozen bytes into the initialized episode. The normal
        // runner verifies all judge and pristine workspace hashes before submit.
        const archive = path.join(frozenInputs, `${envName}.zip`);
        const imported = path.join(caseDirectory, 'frozen-input');
        const extraction = command('unzip', ['-q', archive, '-d', imported], caseDirectory, {}, 60000);
        const onlyPortableSeparatorWarning = extraction.exit_code === 1 &&
          /appears to use backslashes as path separators/.test(extraction.stderr_text);
        if (extraction.exit_code !== 0 && !onlyPortableSeparatorWarning) throw new Error(`Frozen archive could not be loaded: ${archive}`);
        record.frozen_archive_sha256 = digest(fs.readFileSync(archive));
        const frozenState = readJson(path.join(imported, 'state.json'));
        const manifest = readJson(path.join(imported, 'env', 'generation.json'));
        if (manifest.generation_id !== expected[envName].generation_id || manifest.pair_id !== expected[envName].pair_id ||
            frozenState.provenance.generation_id !== manifest.generation_id || frozenState.provenance.pair_id !== manifest.pair_id ||
            frozenState.seed !== 41 || frozenState.difficulty !== difficulty) throw new Error('Frozen identity differs from historical reset evidence');
        const verifiedFiles = Object.entries(manifest.files).map(([name, hash]) => {
          const filename = name.startsWith('agent/workspace/') ?
            path.join(imported, 'original_workspace', name.slice('agent/workspace/'.length)) : path.join(imported, 'env', name);
          return { path: name, expected_sha256: hash, sha256: digest(fs.readFileSync(filename)) };
        });
        writeJson(path.join(caseDirectory, 'frozen-file-verification.json'), verifiedFiles);
        if (verifiedFiles.some(item => item.sha256 !== item.expected_sha256)) throw new Error('Frozen archive fails recorded per-file hashes');
        const treeDigest = digest(verifiedFiles.map(item => `${item.path}:${item.sha256}`).sort().join('\n'));
        if (treeDigest !== manifest.tree_sha256 || treeDigest !== frozenState.provenance.tree_sha256) throw new Error('Frozen archive tree SHA differs from history');
        const frozenJudgeDigest = digest(Object.entries(manifest.judge_files).map(([name, hash]) => `${name}:${hash}`).sort().join('\n'));
        if (frozenJudgeDigest !== manifest.judge_sha256 || frozenJudgeDigest !== frozenState.provenance.judge_sha256 ||
            Object.entries(manifest.judge_files).some(([name, hash]) => manifest.files[name] !== hash)) {
          throw new Error('Frozen judge source hashes differ from historical provenance');
        }
        if (manifest.interventions.length !== 0) throw new Error('Frozen production cases must have no interventions');
        const recomputedGeneration = 'G' + digest(JSON.stringify(canonical({ env: manifest.environment,
          config_path: manifest.config_path, config_sha256: manifest.config_sha256, seed: manifest.seed,
          difficulty_vector: manifest.difficulty_vector, intervention_vector: [],
          generator_version: manifest.generator_version, tree_sha256: treeDigest }))).slice(0, 16);
        if (recomputedGeneration !== manifest.generation_id) throw new Error('Recomputed frozen generation ID differs from manifest');
        if (manifest.pair_id_basis !== 'latent_spec' || 'P' + manifest.latent_spec_sha256.slice(0, 16) !== manifest.pair_id) {
          throw new Error('Frozen latent identity differs from pair ID');
        }
        fs.rmSync(within(episodeDirectory, state.env_dir), { recursive: true });
        fs.rmSync(within(episodeDirectory, state.original_workspace), { recursive: true });
        fs.cpSync(path.join(imported, 'env'), state.env_dir, { recursive: true });
        fs.cpSync(path.join(imported, 'original_workspace'), state.original_workspace, { recursive: true });
        fs.cpSync(path.join(imported, 'original_workspace'), state.workspace, { recursive: true });
        state.provenance = frozenState.provenance;
        writeJson(statePath, state);
        record.frozen_identity_verified = true;
        record.identity = { generation_id: manifest.generation_id, pair_id: manifest.pair_id,
          tree_sha256: manifest.tree_sha256, judge_sha256: manifest.judge_sha256 };
        record.stages.frozen_identity = { status: 'passed', ...record.identity,
          evidence: 'Original archive bytes, historical generation/pair IDs, all recorded file hashes and full tree SHA verified before loading' };
        const solverPath = within(episodeDirectory, path.join(state.workspace, 'solver.py'));
        const original = fs.readFileSync(solverPath, 'utf8');
        const source = candidateSource(envName, original, network, variant);
        fs.writeFileSync(solverPath, source);
        record.solver_sha256 = digest(source);
        fs.writeFileSync(path.join(caseDirectory, 'submitted-solver.py'), source);
        const submitted = command('python', ['env_runner.py', 'submit', '--episode', episodeId,
          '--confirm', '--timeout', '1800'], caseDirectory, runtimeEnvironment);
        record.command_failed = submitted.exit_code !== 0;
        if (submitted.exit_code !== 0) throw new Error(`Submission command exited ${submitted.exit_code}: ${submitted.error ?? submitted.stderr_text.slice(-2000)}`);
        const response = JSON.parse(submitted.stdout_text);
        writeJson(path.join(caseDirectory, 'submission-response.json'), response);
        record.judge_result = response.info.judge_result;
        record.judge_returncode = response.info.returncode;
        record.runner_reward = response.reward;
        record.submission_done = response.done;
        fs.writeFileSync(path.join(caseDirectory, 'judge.stdout'), response.info.judge_stdout ?? '');
        fs.writeFileSync(path.join(caseDirectory, 'judge.stderr'), response.info.judge_stderr ?? '');
        try {
          record.judge_stdout_json_valid = isDeepStrictEqual(JSON.parse(response.info.judge_stdout), response.info.judge_result);
        } catch { record.judge_stdout_json_valid = false; }
        record.named_checks = Object.fromEntries(expectedChecks.map(name => [name, record.judge_result?.checks?.[name] ?? null]));
        const payloads = descendants(runtimeDirectory).filter(filename => path.basename(filename) === '_eval_payload.json');
        const savedOutputs = descendants(runtimeDirectory).filter(filename => path.basename(filename) === 'eval_outputs.pt');
        if (payloads.length === 1 && savedOutputs.length === 1) {
          const payload = readJson(payloads[0]);
          const payloadHash = digest(JSON.stringify(canonical(payload)));
          const priorHash = payloadDigests.get(envName);
          if (!priorHash) payloadDigests.set(envName, payloadHash);
          record.payload_identity_verified = !priorHash || priorHash === payloadHash;
          record.public_payload_sha256 = payloadHash;
          record.payload_names = payload.map(item => item.name);
          fs.copyFileSync(payloads[0], path.join(caseDirectory, 'production-eval-payload.json'));
          fs.copyFileSync(savedOutputs[0], path.join(caseDirectory, 'production-eval-outputs.pt'));
          const decode = command('python', ['-c',
            'import json,sys,torch; print(json.dumps(torch.load(sys.argv[1], weights_only=1)))', savedOutputs[0]],
          caseDirectory, runtimeEnvironment, 60000);
          if (decode.exit_code !== 0) record.evidence_errors.push('Could not decode preserved production PyTorch output');
          else {
            record.output_rows = JSON.parse(decode.stdout_text);
            writeJson(path.join(caseDirectory, 'production-eval-outputs.json'), record.output_rows);
            record.output_evidence_complete = Array.isArray(record.output_rows) && record.output_rows.length === payload.length &&
              isDeepStrictEqual(record.output_rows.map(row => row.name), payload.map(item => item.name));
          }
        }
        stageEvidence(record);
      } catch (error) {
        record.exception = { message: error.message, stack: error.stack };
      } finally {
        if (episodeDirectory && fs.existsSync(episodeDirectory)) {
          try { fs.cpSync(episodeDirectory, path.join(caseDirectory, 'episode'), { recursive: true }); }
          catch (error) { record.evidence_errors.push(`Episode preservation failed: ${error.message}`); }
        }
        record.gate_passed = casePassed(record);
        records.push(record);
        writeJson(path.join(caseDirectory, 'result.json'), record);
        writeJson(path.join(output, 'production-judge-results.json'), { schema_version: 2, commit,
          environment: relative(path.join(output, 'environment.json')), setup_errors: setupErrors,
          records, complete: false, gate_passed: false });
        fs.appendFileSync(path.join(output, 'production-judge.log'), `${JSON.stringify(record)}\n`);
        process.stdout.write(`${envName} ${variant}: ${record.gate_passed ? 'PASS' : 'FAIL'} ${record.exception?.message ?? record.judge_result?.failure_mode ?? 'unexecuted'}\n`);
      }
    }
  }
  const summary = ENVIRONMENTS.map(([name]) => {
    const cases = records.filter(record => record.environment === name);
    const first = cases.find(record => record.variant === 'valid');
    const second = cases.find(record => record.variant === 'valid_repeat');
    const replay = first?.gate_passed && second?.gate_passed &&
      first.solver_sha256 === second.solver_sha256 && first.public_payload_sha256 === second.public_payload_sha256 &&
      isDeepStrictEqual(first.named_checks, second.named_checks) && isDeepStrictEqual(first.output_rows, second.output_rows) &&
      first.judge_result.score === second.judge_result.score;
    const adversarial = cases.find(record => record.variant === 'adversarial_certificate');
    const metadata = cases.find(record => record.variant === 'adversarial_with_reference_accuracy');
    const metadataIgnored = adversarial?.gate_passed && metadata?.gate_passed &&
      adversarial.public_payload_sha256 === metadata.public_payload_sha256 &&
      isDeepStrictEqual(adversarial.named_checks, metadata.named_checks) &&
      adversarial.judge_result.raw_accuracy === metadata.judge_result.raw_accuracy &&
      adversarial.judge_result.score === metadata.judge_result.score;
    const item = { environment: name, cases: cases.length, passed_cases: cases.filter(record => record.gate_passed).length,
      fresh_episode_repetition: replay ? 'passed' : 'failed',
      reference_accuracy_noninterference: metadataIgnored ? 'passed' : 'failed',
      frozen_identity: cases.every(record => record.frozen_identity_verified) ? 'passed' : 'failed',
      named_checks: first?.named_checks ?? {}, production_check_count: first?.expected_check_names?.length ?? 0,
      boundary_evidence: 'Existing judge named local/assembled/held-out/twin/counterfactual checks; no new boundary distribution is claimed',
      disposition: cases.length === VARIANTS.length && cases.every(record => record.gate_passed) && replay && metadataIgnored && setupErrors.length === 0 ?
        'Validated for these frozen production cases' : 'Blocked or failed; inspect per-case stage evidence' };
    writeJson(path.join(output, 'per-environment', name, 'summary.json'), item);
    return item;
  });
  const passed = setupErrors.length === 0 && summary.every(row => row.disposition === 'Validated for these frozen production cases');
  const results = { schema_version: 2, commit, run_url: environment.run_url, setup_errors: setupErrors,
    variants: VARIANTS, scored_environments: ENVIRONMENTS.map(([name]) => name), excluded: ['recursive_holonomy_gluing'],
    records, summary, complete: true, gate_passed: passed };
  writeJson(path.join(output, 'production-judge-results.json'), results);
  const report = [
    '# Recursive structural production gate', '', `Date: ${new Date().toISOString()}`, `Commit: \`${commit}\``,
    `Run: ${environment.run_url}`, `Result: ${passed ? 'PASS' : 'FAIL'}`, '',
    `Observed complete production judge results: ${records.filter(judgeCompleted).length}/${records.length}. The harness uses env_runner reset and submit on GitHub-hosted Ubuntu 22.04 with declared Python 3.11, CPU PyTorch 2.5.1 and torchvision 0.20.1. Exact observed versions and setup failures are in environment.json and production-judge-results.json.`, '',
    'Frozen archives preserve the original generation IDs and per-file bytes. Fresh reset identities are recorded separately; the verified historical snapshot is loaded before submission. No regenerated identity is presented as an original frozen identity.', '',
    '| Environment | Cases passed | Fresh repeat | Metadata noninterference | Disposition |', '|---|---:|---|---|---|',
    ...summary.map(row => `| ${row.environment} | ${row.passed_cases}/${row.cases} | ${row.fresh_episode_repetition} | ${row.reference_accuracy_noninterference} | ${row.disposition} |`), '',
    '## Execution evidence', '',
    'Each case includes the real judge JSON, stdout/stderr, command arguments and exit codes, submitted source, frozen-file verification, episode copy, and preserved PyTorch output where evaluation reached that stage. Source rejection does not imply certificate parsing or final behavioral scoring. Infrastructure failures never count as negative-control success.', '',
    'The production verifiers combine parsing and semantic verification. Accepted named checks establish both. On rejected outputs, separate parsing outcomes are marked not separately observable rather than inferred. Raw outputs and candidate errors are retained. The metadata-only control requires zero accepted hidden checks and zero score.', '',
    'The corrupted-certificate pair differs only by the added reference_acc=1.0 field. Both must be rejected with identical named checks, raw accuracy, and final score. Recorded hidden-check totals and raw accuracy must agree with the named boolean checks; output evidence must preserve every named payload and both submitted repetitions.', '',
    'Existing production named checks cover local visible, configured, assembled positive/negative, held-out, twin, and domain-specific counterfactual cases as listed per environment. Output repetition is checked within each judge and across two fresh valid episodes.', '',
    '## Interpretation', '',
    'Implementation validation covers the executed runner/judge integration and harness regressions. Task-level validation is limited to the frozen inputs and submitted positive/negative controls. Scientific validation is not established: these reference-algorithm submissions do not demonstrate model recursive reasoning, its necessity, generalization, or transfer. Holonomy remains outside this scored gate.', '',
    'Historical evidence and original source hashes remain unchanged. The previous Python harness is preserved but unused. This harness changes no judge, network, scoring threshold, or source validator.', '',
    ...(setupErrors.length ? ['## Setup failures', '', ...setupErrors.map(error => `- ${error}`), ''] : []),
  ].join('\n');
  fs.writeFileSync(path.join(output, 'production-gate-report.md'), report);
  fs.writeFileSync(path.join(output, 'exit-code.txt'), `${passed ? 0 : 1}\n`);
  process.exitCode = passed ? 0 : 1;
}

function selfTest() {
  // These regression checks test evidence classification only. They do not mock
  // torch or claim any production execution.
  const missing = { variant: 'reference_accuracy_only', reset_succeeded: true, frozen_identity_verified: true,
    judge_result: { verdict: 'FAIL', score: 0, failure_mode: 'judge_runtime_error' } };
  if (casePassed(missing)) throw new Error('Missing judge evidence accepted as negative success');
  const rejected = { ...missing, variant: 'malformed_source', judge_stdout_json_valid: true, judge_returncode: 1,
    judge_result: { verdict: 'FAIL', score: 0, failure_mode: 'source_invalid', checks: { patch_valid: true, sources_valid: false } } };
  if (!casePassed(rejected)) throw new Error('Expected source rejection was not recognized');
  if (casePassed({ ...rejected, exception: { message: 'failed after judge execution' } })) throw new Error('Evidence exception accepted');
  if (casePassed({ ...rejected, frozen_identity_verified: false })) throw new Error('Wrong frozen identity accepted');
  if (casePassed({ ...rejected, judge_returncode: 0 })) throw new Error('Mismatched judge return code accepted');
  if (casePassed({ ...rejected, variant: 'reference_accuracy_only' })) throw new Error('Source rejection accepted as metadata verification');
  if (casePassed({ ...rejected, judge_result: { ...rejected.judge_result, failure_mode: 'judge_runtime_error' } })) {
    throw new Error('Infrastructure failure accepted as source rejection');
  }
  const source = candidateSource('recursive_compiler_bootstrap', 'class Solver:\n    pass\n',
    'from __future__ import annotations\nfrom operator import index\n', 'valid');
  if (!source.includes('from operator import index') || source.includes('def index(') || source.includes('from __future__')) {
    throw new Error('Reference import sanitization changed operator.index semantics');
  }
  process.stdout.write('PASS: eight evidence-classification and source-preservation regression assertions\n');
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.includes('--self-test')) selfTest();
  else if (process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted') {
    process.stderr.write('Execution is restricted to a GitHub-hosted Actions runner.\n');
    process.exitCode = 2;
  } else await runGate().catch(error => {
    const output = path.resolve(ROOT, argument('--output', 'docs/artifacts/recursive-structural-production-gate'));
    within(ROOT, output);
    writeJson(path.join(output, 'fatal-error.json'), { message: error.message, stack: error.stack, unexecuted: true });
    fs.writeFileSync(path.join(output, 'production-gate-report.md'), `# Production gate could not complete\n\n${error.message}\n\nNo unexecuted check is a passing result.\n`);
    fs.writeFileSync(path.join(output, 'exit-code.txt'), '1\n');
    process.stderr.write(`${error.stack}\n`);
    process.exitCode = 1;
  });
}
