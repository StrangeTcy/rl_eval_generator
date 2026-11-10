import fs from 'node:fs';
import { parseDocument } from 'yaml';
import { Catalog } from './catalog.mjs';
import { Contract } from './runtime.mjs';

export const CONFIG_SCHEMA = 'epistemic-family-config/1';

export class Configuration {
  static parse(source) {
    const document = parseDocument(source, { version: '1.2', schema: 'core', strict: true, uniqueKeys: true });
    const problems = [...document.errors, ...document.warnings];
    if (problems.length !== 0) throw new Error(`invalid YAML configuration: ${problems.map(problem => problem.message).join('; ')}`);
    const value = document.toJS({ maxAliasCount: 0 });
    Contract.fields(value, ['schema', 'family', 'axes'], ['seed', 'privateSeed']);
    if (value.schema !== CONFIG_SCHEMA) throw new Error(`configuration schema must be ${CONFIG_SCHEMA}`);
    Contract.object(value.axes, 'configuration axes');
    if (Object.values(value.axes).some(level => typeof level !== 'string')) throw new Error('configuration axis levels must be strings');
    if (Object.hasOwn(value, 'seed')) Contract.integer(value.seed, 0, 0xffffffff, 'seed');
    if (Object.hasOwn(value, 'privateSeed')) Contract.integer(value.privateSeed, 0, 0xffffffff, 'private seed');
    return value;
  }

  static async load(file, expectedFamily, overrides = {}) {
    const { schema, family, ...options } = this.parse(fs.readFileSync(file, 'utf8'));
    if (expectedFamily !== undefined && family !== expectedFamily) throw new Error('configuration family does not match requested family');
    const { definition } = await Catalog.load(family);
    const configured = Catalog.options(definition, options);
    let configuration;
    if (overrides.difficulty !== undefined) {
      if (overrides.axes !== undefined) throw new Error('choose a difficulty vector or named axes');
      const { axes, ...seeds } = configured;
      configuration = Catalog.options(definition, { ...seeds, ...overrides });
    } else {
      if (overrides.axes !== undefined) Contract.object(overrides.axes, 'axes override');
      if (Object.values(overrides.axes ?? {}).some(level => typeof level !== 'string')) throw new Error('axis override levels must be strings');
      configuration = Catalog.options(definition, { ...configured, ...overrides, axes: { ...configured.axes, ...overrides.axes } });
    }
    return { schema, family, configuration };
  }
}
