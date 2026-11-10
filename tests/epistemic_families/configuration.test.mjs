import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { Configuration, CONFIG_SCHEMA } from '../../arena/epistemic_families/configuration.mjs';
import { Catalog, FAMILY_IDS, ROOT } from '../../arena/epistemic_families/catalog.mjs';
import { FamilyCLI } from '../../tools/epistemic_families.mjs';

test('every registered YAML resolves all axes and reaches generation, execution and replay', async () => {
  const registry = JSON.parse(fs.readFileSync(path.join(ROOT, 'envs/epistemic_families/registry.json'), 'utf8'));
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'epistemic-yaml-'));
  assert.equal(registry.configuration.schema, CONFIG_SCHEMA);
  await Promise.all(FAMILY_IDS.map(async family => {
    const file = path.join(ROOT, registry.configuration.pathTemplate.replace('{family}', family));
    const raw = Configuration.parse(fs.readFileSync(file, 'utf8'));
    const module = await Catalog.load(family);
    assert.equal(raw.family, family);
    const expected = { seed: raw.seed ?? 0, privateSeed: raw.privateSeed ?? 0, axes: Object.fromEntries(module.definition.axes.map(axis => [axis.id, raw.axes[axis.id] ?? 'easy'])) };
    const validated = await FamilyCLI.run(['validate-config', file]);
    assert.equal(validated.status, 'passed');
    assert.deepEqual(validated.configuration, expected);
    assert.deepEqual(new Set(Object.keys(validated.configuration.axes)), new Set(module.definition.axes.map(axis => axis.id)));
    const view = await FamilyCLI.run(['show', family, '--config', file]);
    assert.deepEqual(view, module.create(expected).view());
    const serializedView = JSON.parse(JSON.stringify(view));

    const instanceDirectory = path.join(parent, `${family}-instance`);
    await FamilyCLI.run(['generate', family, '--config', file, '--output', instanceDirectory]);
    const instance = JSON.parse(fs.readFileSync(path.join(instanceDirectory, 'controller/instance.json'), 'utf8'));
    assert.deepEqual(instance.configuration, expected);
    const agentText = fs.readFileSync(path.join(instanceDirectory, 'agent/initial-view.json'), 'utf8');
    assert.deepEqual(JSON.parse(agentText), serializedView);
    assert.equal(agentText.includes('privateSeed'), false);

    const runDirectory = path.join(parent, `${family}-run`);
    const result = await FamilyCLI.run(['run', family, '--config', file, '--output', runDirectory]);
    assert.equal(result.status, 'completed', family);
    assert.equal(result.replay.status, 'passed');
    const episode = JSON.parse(fs.readFileSync(path.join(runDirectory, 'episode.json'), 'utf8'));
    assert.deepEqual(episode.configuration, expected);
    assert.deepEqual(episode.events[0].view, serializedView);
    assert.equal((await FamilyCLI.run(['replay', runDirectory])).status, 'passed');
  }));
});

test('YAML settings survive partial overrides and ordered difficulty replaces the full vector', async () => {
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'epistemic-yaml-overrides-'));
  const file = path.join(parent, 'mixed axes.yaml');
  fs.writeFileSync(file, 'schema: epistemic-family-config/1\nfamily: inquiry_control\nseed: 19\nprivateSeed: 23\naxes:\n  world_count: medium\n  cost_pressure: hard\n  presentation: medium\n  query_topology: hard\n');
  const changed = await FamilyCLI.run(['show', 'inquiry_control', '--config', file, '--seed', '29', '--axes', '{"presentation":"easy"}']);
  const module = await Catalog.load('inquiry_control');
  assert.deepEqual(changed, module.create({ seed: 29, privateSeed: 23, axes: { world_count: 'medium', cost_pressure: 'hard', presentation: 'easy', query_topology: 'hard' } }).view());
  const directory = path.join(parent, 'run');
  await FamilyCLI.run(['run', 'inquiry_control', '--config', file, '--private-seed', '31', '--difficulty', 'hard,easy,medium,easy', '--output', directory]);
  const episode = JSON.parse(fs.readFileSync(path.join(directory, 'episode.json'), 'utf8'));
  assert.deepEqual(episode.configuration, { seed: 19, privateSeed: 31, axes: { world_count: 'hard', cost_pressure: 'easy', presentation: 'medium', query_topology: 'easy' } });
});

test('invalid YAML structure fails instead of silently choosing settings', () => {
  const valid = 'schema: epistemic-family-config/1\nfamily: inquiry_control\nseed: 3\nprivateSeed: 7\naxes: {}\n';
  const invalid = [
    '',
    '[]',
    valid + 'seed: 4\n',
    valid.replace('axes: {}', 'axes:\n  world_count: easy\n  world_count: hard'),
    valid + '---\n' + valid,
    valid + 'unknown: value\n',
    valid.replace('epistemic-family-config/1', 'epistemic-family-config/2'),
    valid.replace('axes: {}', 'axes: null'),
    valid.replace('axes: {}', 'axes: [easy]'),
    valid.replace('axes: {}', 'axes: !custom {}'),
    valid.replace('seed: 3', 'seed: null'),
    valid.replace('seed: 3', 'seed: true'),
    valid.replace('seed: 3', 'seed: "3"'),
    valid.replace('seed: 3', 'seed: -1'),
    valid.replace('seed: 3', 'seed: 4294967296'),
    valid.replace('privateSeed: 7', 'privateSeed: 1.5'),
    valid.replace('seed: 3\nprivateSeed: 7', 'seed: &seed 3\nprivateSeed: *seed'),
  ];
  invalid.forEach(source => assert.throws(() => Configuration.parse(source), undefined, source));
});

test('unknown family, axes and levels fail before CLI overrides can conceal them', async () => {
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'epistemic-yaml-invalid-'));
  const prefix = 'schema: epistemic-family-config/1\nfamily: inquiry_control\n';
  const sources = [
    prefix.replace('inquiry_control', 'missing_family') + 'axes: {}\n',
    prefix + 'axes: {world_counnt: easy}\n',
    prefix + 'axes: {world_count: impossible}\n',
    prefix + 'axes: {world_count: true}\n',
    prefix + 'axes: {world_count: null}\n',
  ];
  await Promise.all(sources.map(async (source, index) => {
    const file = path.join(parent, `${index}.yaml`);
    fs.writeFileSync(file, source);
    await assert.rejects(FamilyCLI.run(['validate-config', file]));
    await assert.rejects(FamilyCLI.run(['show', 'inquiry_control', '--config', file, '--difficulty', 'easy,easy,easy,easy']));
  }));
});

test('config conflicts and unsupported commands fail before creating output', async () => {
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'epistemic-yaml-conflicts-'));
  const file = path.join(ROOT, 'envs/epistemic_families/inquiry_control.yaml');
  const output = path.join(parent, 'unused');
  await assert.rejects(FamilyCLI.run(['run', 'memory_inquiry', '--config', file, '--output', output]), /family does not match/);
  await assert.rejects(FamilyCLI.run(['run', 'inquiry_control', '--config', file, '--instance', 'unused.json', '--output', output]), /config cannot be combined with instance/);
  await assert.rejects(FamilyCLI.run(['run', 'inquiry_control', '--config', file, '--axes', '{}', '--difficulty', 'easy,easy,easy,easy', '--output', output]), /choose a difficulty vector or named axes/);
  await assert.rejects(FamilyCLI.run(['run', 'inquiry_control', '--config', file, '--axes', 'null', '--output', output]), /axes override required/);
  await assert.rejects(FamilyCLI.run(['run', 'inquiry_control', '--config', file, '--axes', '["easy"]', '--output', output]), /axes override required/);
  await assert.rejects(FamilyCLI.run(['run', 'inquiry_control', '--config', file, '--axes', '{"world_count":null}', '--output', output]), /axis override levels must be strings/);
  await assert.rejects(FamilyCLI.run(['matrix', 'inquiry_control', '--config', file]), /--config requires/);
  await assert.rejects(FamilyCLI.run(['show', 'inquiry_control', '--config', file, '--config', file]), /repeated option/);
  assert.equal(fs.existsSync(output), false);
});

test('editing a preset after generation does not change the saved instance or invalidate replay', async () => {
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'epistemic-yaml-replay-'));
  const file = path.join(parent, 'memory.yaml');
  const source = 'schema: epistemic-family-config/1\nfamily: memory_inquiry\nseed: 3\nprivateSeed: 7\naxes:\n  retention: easy\n';
  fs.writeFileSync(file, source);
  const instanceDirectory = path.join(parent, 'instance'), runDirectory = path.join(parent, 'run');
  await FamilyCLI.run(['generate', 'memory_inquiry', '--config', file, '--output', instanceDirectory]);
  const result = await FamilyCLI.run(['run', 'memory_inquiry', '--config', file, '--output', runDirectory]);
  assert.equal(result.status, 'completed');
  fs.writeFileSync(file, source.replace('privateSeed: 7', 'privateSeed: 31337').replace('retention: easy', 'retention: hard'));
  assert.equal((await FamilyCLI.run(['replay', runDirectory])).status, 'passed');
  const record = JSON.parse(fs.readFileSync(path.join(runDirectory, 'episode.json'), 'utf8'));
  const savedView = await FamilyCLI.run(['show', 'memory_inquiry', '--instance', path.join(instanceDirectory, 'controller/instance.json')]);
  assert.deepEqual(savedView, record.events[0].view);
  assert.equal(record.configuration.privateSeed, 7);
  assert.equal(record.configuration.axes.retention, 'easy');
  const hashes = Catalog.sources();
  assert.ok(hashes['arena/epistemic_families/configuration.mjs']);
  assert.ok(hashes['package-lock.json']);
  assert.equal(Object.keys(hashes).some(name => name.endsWith('.yaml')), false);
});

test('CLI accepts configuration paths with spaces and returns a failing exit code for invalid files', () => {
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'epistemic yaml CLI '));
  const file = path.join(parent, 'config with spaces.yaml');
  fs.writeFileSync(file, 'schema: epistemic-family-config/1\nfamily: inquiry_control\nseed: 3\naxes: {}\n');
  const accepted = spawnSync(process.execPath, [path.join(ROOT, 'tools/epistemic_families.mjs'), 'validate-config', file], { encoding: 'utf8', windowsHide: true });
  assert.equal(accepted.status, 0, accepted.stderr);
  assert.equal(JSON.parse(accepted.stdout).status, 'passed');
  fs.appendFileSync(file, '\nseed: 5\n');
  const rejected = spawnSync(process.execPath, [path.join(ROOT, 'tools/epistemic_families.mjs'), 'validate-config', file], { encoding: 'utf8', windowsHide: true });
  assert.equal(rejected.status, 1);
  assert.match(rejected.stderr, /invalid YAML configuration/);
  assert.equal(rejected.stdout, '');
});
