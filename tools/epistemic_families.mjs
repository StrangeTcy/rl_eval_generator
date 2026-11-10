#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Catalog, FAMILY_IDS, PROTOCOL } from '../arena/epistemic_families/catalog.mjs';
import { Session } from '../arena/epistemic_families/session.mjs';
import { Contract } from '../arena/epistemic_families/runtime.mjs';
import { Configuration } from '../arena/epistemic_families/configuration.mjs';

export class FamilyCLI {
  static options(args) {
    if (args.length % 2 !== 0) throw new Error('options require --name VALUE pairs');
    const parsed = {};
    for (let i = 0; i < args.length; i += 2) {
      const key = args[i];
      if (!['--seed', '--private-seed', '--axes', '--difficulty', '--output', '--policy', '--mode', '--instance', '--config'].includes(key) || Object.hasOwn(parsed, key)) throw new Error(`unknown or repeated option ${key}`);
      parsed[key] = args[i + 1];
    }
    const options = {};
    if (parsed['--seed'] !== undefined) options.seed = Number(parsed['--seed']);
    if (parsed['--private-seed'] !== undefined) options.privateSeed = Number(parsed['--private-seed']);
    if (parsed['--axes'] !== undefined) options.axes = JSON.parse(parsed['--axes']);
    if (parsed['--difficulty'] !== undefined) options.difficulty = parsed['--difficulty'];
    return { parsed, options };
  }
  static async run(args) {
    const [command, id, ...rest] = args;
    if (command === 'list' && args.length === 1) return { protocol: PROTOCOL, families: await Catalog.definitions() };
    if (command === 'validate-config' && args.length === 2) return { status: 'passed', ...await Configuration.load(id) };
    if (command === 'replay' && args.length === 2) {
      const record = JSON.parse(fs.readFileSync(path.join(id, 'episode.json'))), sources = JSON.parse(fs.readFileSync(path.join(id, 'source-hashes.json')));
      if (JSON.stringify(sources) !== JSON.stringify(Catalog.sources())) throw new Error('source changed since recording');
      if (Contract.hash(fs.readFileSync(path.join(id, 'episode.json'))) !== fs.readFileSync(path.join(id, 'episode.sha256'), 'utf8').trim()) throw new Error('episode checksum mismatch');
      return Session.replay(record);
    }
    if (!FAMILY_IDS.includes(id)) throw new Error('usage: list | describe FAMILY | validate-config YAML_PATH | matrix FAMILY [--mode MODE] | show/generate/run FAMILY [--config YAML_PATH] [--axes JSON | --difficulty VECTOR] [--seed N] [--private-seed N] [--output NEW_DIRECTORY] [--policy NAME_OR_ARGV_JSON] | replay DIRECTORY');
    const module = await Catalog.load(id);
    if (command === 'describe' && rest.length === 0) return module.definition;
    const { parsed, options } = this.options(rest);
    if (parsed['--config'] !== undefined && !['show', 'generate', 'run'].includes(command)) throw new Error('--config requires show, generate, or run; use validate-config YAML_PATH to validate');
    if (parsed['--config'] !== undefined && parsed['--instance'] !== undefined) throw new Error('config cannot be combined with instance');
    if (command === 'matrix') return Catalog.matrix(id, parsed['--mode'] ?? 'pairwise');
    let configuration = parsed['--config'] !== undefined
      ? (await Configuration.load(parsed['--config'], id, options)).configuration
      : Catalog.options(module.definition, options);
    if (parsed['--instance']) {
      if (Object.keys(options).length > 0) throw new Error('instance cannot be combined with config overrides');
      const instance = JSON.parse(fs.readFileSync(parsed['--instance']));
      if (instance.protocol !== PROTOCOL || instance.family !== id || JSON.stringify(instance.sourceSha256) !== JSON.stringify(Catalog.sources())) throw new Error('instance identity/source mismatch');
      configuration = Catalog.options(module.definition, instance.configuration);
    }
    if (command === 'show') return module.create(configuration).view();
    if (command === 'generate') {
      if (!parsed['--output']) throw new Error('generate needs --output NEW_DIRECTORY');
      return Catalog.generate(id, configuration, parsed['--output']);
    }
    if (command === 'run') {
      if (!parsed['--output']) throw new Error('run needs --output NEW_DIRECTORY to retain raw evidence');
      const destination = path.resolve(parsed['--output']);
      fs.mkdirSync(destination);
      const policy = parsed['--policy']?.startsWith('[') ? JSON.parse(parsed['--policy']) : parsed['--policy'] ?? 'reference';
      const sourceHashes = Catalog.sources();
      fs.writeFileSync(path.join(destination, 'source-hashes.json'), JSON.stringify(sourceHashes, null, 2)+'\n', { flag: 'wx' });
      const record = await Session.run(id, configuration, policy);
      const bytes = JSON.stringify(record, null, 2)+'\n';
      fs.writeFileSync(path.join(destination, 'episode.json'), bytes, { flag: 'wx' });
      fs.writeFileSync(path.join(destination, 'episode.sha256'), Contract.hash(bytes)+'\n', { flag: 'wx' });
      const replay = await Session.replay(record);
      fs.writeFileSync(path.join(destination, 'replay.json'), JSON.stringify(replay, null, 2)+'\n', { flag: 'wx' });
      return { directory: destination, family: id, status: record.status, turns: record.events.length, metrics: record.terminal?.metrics ?? null, replay, modelCalls: typeof policy === 'string' ? 0 : null, policy };
    }
    throw new Error('unknown command');
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { const result = await FamilyCLI.run(process.argv.slice(2)); process.stdout.write(JSON.stringify(result, null, 2)+'\n'); if (result.status && result.status !== 'completed' && result.status !== 'passed') process.exitCode = 1; }
  catch (error) { process.stderr.write(error.message+'\n'); process.exitCode = 1; }
}
