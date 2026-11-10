import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Contract, AxisMatrix } from './runtime.mjs';

export const FAMILY_IDS = Object.freeze(['agent_reconstruction', 'inquiry_control', 'hypothesis_discovery', 'evidence_process', 'adaptive_agents', 'recursive_delegation', 'evaluator_prediction', 'belief_revision', 'memory_inquiry']);
export const PROTOCOL = 'epistemic-family-current-view/1';
export const ROOT = fileURLToPath(new URL('../../', import.meta.url));

export class Catalog {
  static async load(id) {
    if (!FAMILY_IDS.includes(id)) throw new Error(`unknown family: ${id}`);
    const module = await import(new URL(`./${id}.mjs`, import.meta.url));
    if (module.definition.id !== id || typeof module.create !== 'function' || typeof module.reference !== 'function') throw new Error(`invalid family contract: ${id}`);
    if (module.definition.axes.length < 4 || new Set(module.definition.axes.map(axis => axis.id)).size !== module.definition.axes.length) throw new Error('at least four unique axes required');
    module.definition.axes.forEach(axis => {
      if (!axis.description || !axis.class || Object.keys(axis.levels).join(',') !== 'easy,medium,hard') throw new Error(`invalid axis definition: ${id}/${axis.id}`);
    });
    return module;
  }
  static async definitions() { return Promise.all(FAMILY_IDS.map(async id => (await this.load(id)).definition)); }
  static options(definition, { difficulty, ...options } = {}) {
    if (difficulty !== undefined) {
      if (options.axes !== undefined) throw new Error('choose a difficulty vector or named axes');
      const levels = difficulty.split(',');
      if (levels.length !== definition.axes.length) throw new Error(`${definition.id} requires ${definition.axes.length} ordered levels`);
      options.axes = Object.fromEntries(definition.axes.map((axis, index) => [axis.id, levels[index]]));
    }
    const { seed, privateSeed, axes } = Contract.configuration(definition, options);
    return { seed, privateSeed, axes };
  }
  static async matrix(id, mode) {
    const { definition } = await this.load(id), vectors = AxisMatrix.expand(definition, mode);
    return { family: id, mode, axes: definition.axes, vectors, pairCoverage: AxisMatrix.coverage(definition, vectors), inference: 'Coverage of configured levels only; not independent model trials or proven difficulty ordering.' };
  }
  static sources() {
    const names = [...FAMILY_IDS.map(id => `arena/epistemic_families/${id}.mjs`), 'arena/epistemic_families/runtime.mjs', 'arena/epistemic_families/catalog.mjs', 'arena/epistemic_families/session.mjs', 'arena/epistemic_families/configuration.mjs', 'arena/inquiry/selection_laws.mjs', 'tools/epistemic_families.mjs', 'envs/epistemic_families/registry.json', 'package.json', 'package-lock.json'];
    return Object.fromEntries(names.map(name => [name, Contract.hash(fs.readFileSync(path.join(ROOT, name)))]));
  }
  static async generate(id, options, directory) {
    const module = await this.load(id), configuration = this.options(module.definition, options), game = module.create(configuration);
    const destination = path.resolve(directory);
    fs.mkdirSync(destination);
    fs.mkdirSync(path.join(destination, 'agent'));
    fs.mkdirSync(path.join(destination, 'controller'));
    const publicView = Contract.serializable(game.view());
    const write = (name, value) => fs.writeFileSync(path.join(destination, name), typeof value === 'string' ? value : JSON.stringify(value, null, 2)+'\n', { flag: 'wx' });
    write('definition.json', module.definition);
    write('controller/instance.json', { protocol: PROTOCOL, family: id, configuration, sourceSha256: this.sources() });
    write('agent/initial-view.json', publicView);
    write('agent/prompt.md', `# ${module.definition.title}\n\n${module.definition.description}\n\nEach invocation receives only the current JSON view. Return one JSON action following actionSchema. The next invocation receives a new current view, including only history permitted by the environment. Exact fractions are used where the schema requests them. Do not assume more reasoning depth, more queries, or a changed belief is always useful.\n\nThe controller owns private configuration and audit records. Only files in this agent directory and the current view belong to the policy interface.\n`);
    write('generation.json', { protocol: PROTOCOL, family: id, configurationHash: Contract.hash(configuration), publicViewHash: Contract.hash(publicView), sourceSha256: this.sources(), runtime: process.version });
    return { directory: destination, family: id, axes: configuration.axes, protocol: PROTOCOL };
  }
}
