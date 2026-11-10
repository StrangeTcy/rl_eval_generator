import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { parseDocument } from 'yaml';
import { Catalog, FAMILY_IDS, ROOT } from '../../arena/epistemic_families/catalog.mjs';

class Workflow {
  static read(name) {
    const document = parseDocument(fs.readFileSync(path.join(ROOT, '.github/workflows', name), 'utf8'));
    assert.deepEqual(document.errors, []);
    assert.deepEqual(document.warnings, []);
    return document.toJS();
  }
  static shared() { return this.read('epistemic-families-campaign.yml'); }
  static async script(id, overrides = {}, artifacts = [], source = {}) {
    const outputs = {};
    const env = { PROVIDER: 'mercury', EXECUTION_MODE: 'live', MATRIX_MODE: 'pairwise', ATTEMPTS: '1', MAX_REQUESTS: '512', MAX_EPISODES: '25', RESUME_RUN_ATTEMPT: '1', RESUME_RUN_ID: '', GITHUB_RUN_ATTEMPT: '1', RUNNER_TEMP: os.tmpdir(), ...overrides };
    const script = this.shared().jobs.campaign.steps.find(step => step.id === id).with.script;
    const context = { sha: 'a'.repeat(40), runId: 300, repo: { owner: 'owner', repo: 'repo' } };
    const github = {
      paginate: async () => artifacts,
      rest: { actions: { listArtifactsForRepo: 'list', getWorkflowRun: async ({ run_id: runId }) => ({ data: source[runId] ?? { path: '.github/workflows/epistemic-mercury-campaign.yml', event: 'workflow_dispatch', status: 'completed' } }) } },
    };
    await vm.runInNewContext(`(async () => { ${script}\n })()`, {
      process: { env }, github, context, require: createRequire(import.meta.url),
      core: { setOutput: (key, value) => { outputs[key] = value; }, exportVariable: (key, value) => { env[key] = value; } },
    });
    return outputs;
  }
}

test('manual provider workflows expose every family and pass complete inputs to the shared runner', async () => {
  const shared = Workflow.shared();
  ['epistemic-mercury-campaign.yml', 'epistemic-reasoning-atria-campaign.yml'].forEach(name => {
    const wrapper = Workflow.read(name);
    assert.deepEqual(Object.keys(wrapper.on), ['workflow_dispatch']);
    assert.deepEqual(wrapper.on.workflow_dispatch.inputs.family.options, ['all', ...FAMILY_IDS]);
    assert.equal(wrapper.on.workflow_dispatch.inputs.execution_mode.default, 'plan');
    assert.deepEqual(Object.keys(wrapper.jobs.campaign.with).sort(), Object.keys(shared.on.workflow_call.inputs).sort());
    assert.equal(wrapper.concurrency['cancel-in-progress'], false);
    assert.equal(wrapper.permissions.actions, 'read');
  });
  assert.equal(shared.concurrency, undefined);
  const definition = await Catalog.definitions();
  assert.equal(definition.length, FAMILY_IDS.length);
  const liveStep = shared.jobs.campaign.steps.find(step => step.id === 'execute');
  assert.match(liveStep.env.INCEPTION_API_KEY, /execution_mode == 'live'/);
  assert.match(liveStep.env.ATRIA_API_KEY, /execution_mode == 'live'/);
  shared.jobs.campaign.steps.filter(step => step.run).forEach(step => assert.doesNotMatch(step.run, /\$\{\{\s*inputs\./));
});

test('dispatch guard rejects rerun billing and malformed limits before artifact access', async () => {
  await assert.rejects(Workflow.script('checkpoint', { GITHUB_RUN_ATTEMPT: '2' }), /new manual dispatch/);
  await assert.rejects(Workflow.script('checkpoint', { MAX_REQUESTS: '1; echo unsafe' }), /numeric input/);
  await assert.rejects(Workflow.script('checkpoint', { MAX_REQUESTS: '20001' }), /numeric input/);
  await assert.rejects(Workflow.script('checkpoint', { EXECUTION_MODE: 'plan', RESUME_RUN_ID: '100' }), /Planning starts/);
  assert.equal((await Workflow.script('checkpoint')).profile, 'experiments/epistemic_mercury_campaign.yaml');
});

test('checkpoint guard accepts only the newest unexpired checkpoint owned by the provider wrapper', async () => {
  const selected = { id: 10, name: 'epistemic-mercury-state-100-1', expired: false, workflow_run: { id: 100 } };
  const newer = { id: 11, name: 'epistemic-mercury-state-200-1', expired: false, workflow_run: { id: 200 } };
  assert.equal((await Workflow.script('checkpoint', { RESUME_RUN_ID: '100' }, [selected])).artifact, selected.name);
  await assert.rejects(Workflow.script('checkpoint', { RESUME_RUN_ID: '100' }, [{ ...selected, expired: true }]), /missing or expired/);
  await assert.rejects(Workflow.script('checkpoint', { RESUME_RUN_ID: '100' }, [selected, newer]), /newer checkpoint/);
  await assert.rejects(Workflow.script('checkpoint', { RESUME_RUN_ID: '100' }, [selected], { 100: { path: '.github/workflows/other.yml', event: 'workflow_dispatch', status: 'completed' } }), /completed manual run/);
  await assert.rejects(Workflow.script('checkpoint', { RESUME_RUN_ID: '100' }, [selected], { 100: { path: '.github/workflows/epistemic-mercury-campaign.yml', event: 'workflow_dispatch', status: 'in_progress' } }), /completed manual run/);
  const unrelated = { 200: { path: '.github/workflows/other.yml', event: 'workflow_dispatch', status: 'completed' } };
  assert.equal((await Workflow.script('checkpoint', { RESUME_RUN_ID: '100' }, [selected, newer], unrelated)).artifact, selected.name);
  const plan = { ...newer, name: 'epistemic-mercury-plan-200-1' };
  assert.equal((await Workflow.script('checkpoint', { RESUME_RUN_ID: '100' }, [selected, plan])).artifact, selected.name);
});

test('resume checks original campaign SHA instead of the later wrapper revision', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'campaign-workflow-'));
  const file = path.join(directory, 'workflow-identity.json');
  const identity = { provider: 'mercury', repository: 'owner/repo', runId: 100, runAttempt: 1, sourceSha: 'b'.repeat(40) };
  fs.writeFileSync(file, JSON.stringify(identity));
  const env = { EVIDENCE_DIR: directory, RESUME_RUN_ID: '100' };
  assert.equal((await Workflow.script('source', env)).sha, identity.sourceSha);
  fs.writeFileSync(file, JSON.stringify({ ...identity, provider: 'atria' }));
  await assert.rejects(Workflow.script('source', env), /identity mismatch/);
});

test('identity setup failure cannot publish a stale restored checkpoint under a new run ID', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'campaign-workflow-'));
  fs.mkdirSync(path.join(directory, 'campaign'));
  fs.writeFileSync(path.join(directory, 'campaign', 'state.json'), '{}');
  const failed = await Workflow.script('evidence', { EVIDENCE_DIR: directory, IDENTITY_RECORDED: 'false' });
  assert.equal(failed.name, 'epistemic-mercury-diagnostics-300-1');
  const recorded = await Workflow.script('evidence', { EVIDENCE_DIR: directory, IDENTITY_RECORDED: 'true' });
  assert.equal(recorded.name, 'epistemic-mercury-state-300-1');
  const steps = Workflow.shared().jobs.campaign.steps;
  assert.ok(steps.findIndex(step => step.id === 'identity') < steps.findIndex(step => step.uses === 'actions/checkout@v4'));
});
