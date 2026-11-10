import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { Catalog, FAMILY_IDS, ROOT } from '../../arena/epistemic_families/catalog.mjs';
import { Session } from '../../arena/epistemic_families/session.mjs';
import { AxisMatrix } from '../../arena/epistemic_families/runtime.mjs';
import { FamilyCLI } from '../../tools/epistemic_families.mjs';

test('nine registered families have complete real axis definitions', async () => {
  const registry = JSON.parse(fs.readFileSync(path.join(ROOT, 'envs/epistemic_families/registry.json')));
  assert.deepEqual(Object.keys(registry.families), FAMILY_IDS);
  const definitions = await Catalog.definitions();
  assert.equal(definitions.length, 9);
  definitions.forEach(definition => {
    definition.axes.forEach(axis => assert.equal(new Set(Object.values(axis.levels).map(value => JSON.stringify(value))).size, 3));
    const matrix = AxisMatrix.expand(definition, 'pairwise');
    assert.equal(AxisMatrix.coverage(definition, matrix).complete, true);
    assert.ok(matrix.some(row => Object.values(row).every(value => value === 'hard')));
  });
});

test('all defaults and all-hard settings execute and replay through one session interface', async () => {
  for (const id of FAMILY_IDS) {
    const module = await Catalog.load(id);
    for (const level of ['easy', 'hard']) {
      const axes = Object.fromEntries(module.definition.axes.map(axis => [axis.id, level]));
      const record = await Session.run(id, { seed: 3, privateSeed: 7, axes });
      assert.equal(record.status, 'completed', `${id}/${level}: ${record.failure}`);
      assert.equal((await Session.replay(record)).status, 'passed');
    }
  }
});

test('difficulty vectors are ordered and unknown axes/levels fail closed', async () => {
  const definition = (await Catalog.load('inquiry_control')).definition;
  assert.deepEqual(Object.values(Catalog.options(definition, { difficulty: 'easy,medium,hard,easy' }).axes), ['easy', 'medium', 'hard', 'easy']);
  assert.throws(() => Catalog.options(definition, { difficulty: 'easy' }));
  assert.throws(() => Catalog.options(definition, { axes: { ghost: 'easy' } }));
  assert.throws(() => Catalog.options(definition, { axes: { world_count: 'typo' } }));
  assert.throws(() => Catalog.options(definition, { seed: -1 }));
  await assert.rejects(Catalog.load('../inquiry_control'));
});

test('generated packages keep controller configuration separate and refuse overwrite', async () => {
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'epistemic-generate-'));
  const directory = path.join(parent, 'instance');
  await Catalog.generate('memory_inquiry', { seed: 9, privateSeed: 31337 }, directory);
  const publicText = fs.readFileSync(path.join(directory, 'agent/initial-view.json'), 'utf8');
  assert.equal(publicText.includes('privateSeed'), false);
  assert.equal(fs.existsSync(path.join(directory, 'controller/instance.json')), true);
  await assert.rejects(Catalog.generate('memory_inquiry', {}, directory), /EEXIST/);
  assert.equal(fs.readFileSync(path.join(directory, 'agent/initial-view.json'), 'utf8'), publicText);
});

test('CLI run records exact source hashes and rejects resealed semantic corruption', async () => {
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'epistemic-run-')), directory = path.join(parent, 'run');
  const result = await FamilyCLI.run(['run', 'inquiry_control', '--output', directory]);
  assert.equal(result.status, 'completed');
  const record = JSON.parse(fs.readFileSync(path.join(directory, 'episode.json')));
  record.events[0].view.family = 'wrong';
  await assert.rejects(Session.replay(record), /view mismatch/);
  await assert.rejects(FamilyCLI.run(['run', 'inquiry_control', '--output', directory]), /EEXIST/);
  assert.equal((await FamilyCLI.run(['replay', directory])).status, 'passed');
});

test('external policy gets only each current view in a fresh working directory', async () => {
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'epistemic-policy-test-'));
  const policy = path.join(parent, 'policy.mjs');
  const catalogUrl = new URL('../../arena/epistemic_families/catalog.mjs', import.meta.url).href;
  fs.writeFileSync(policy, `import fs from 'node:fs'; import { Catalog } from ${JSON.stringify(catalogUrl)}; const view=JSON.parse(fs.readFileSync(0,'utf8')); if(view.phase==='recall' && view.exposure.length) throw new Error('exposure leaked'); process.stdout.write(JSON.stringify((await Catalog.load(view.family)).reference(view)));`);
  const record = await Session.run('memory_inquiry', { seed: 7, privateSeed: 3, axes: { retention: 'hard' } }, [process.execPath, policy]);
  assert.equal(record.status, 'completed');
  assert.equal(new Set(record.events.map(event => event.transport.cwd)).size, record.events.length);
  assert.equal((await Session.replay(record)).status, 'passed');
});
