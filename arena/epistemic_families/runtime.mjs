import { createHash } from 'node:crypto';
export { Ratio } from '../inquiry/selection_laws.mjs';

export class RNG {
  constructor(seed) { Contract.integer(seed, 0, 0xffffffff, 'seed'); this.state = seed >>> 0 || 0x6d2b79f5; }
  next(n) { Contract.integer(n, 1, 0x100000000, 'range'); this.state ^= this.state << 13; this.state ^= this.state >>> 17; this.state ^= this.state << 5; return (this.state >>> 0) % n; }
  shuffle(values) { const result = [...values]; for (let i = result.length - 1; i > 0; i--) { const j = this.next(i + 1); [result[i], result[j]] = [result[j], result[i]]; } return result; }
}

export class Contract {
  static object(value, label = 'object') { if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} required`); return value; }
  static fields(value, required, optional = []) {
    this.object(value, 'action');
    if (required.some(key => !Object.hasOwn(value, key)) || Object.keys(value).some(key => ![...required, ...optional].includes(key))) throw new Error('unknown or missing field');
  }
  static integer(value, minimum, maximum, label = 'integer') { if (!Number.isSafeInteger(value) || value < minimum || value > maximum) throw new Error(`${label} outside ${minimum}..${maximum}`); return value; }
  static configuration(definition, options = {}) {
    this.fields(options, [], ['seed', 'privateSeed', 'axes']);
    const seed = this.integer(options.seed ?? 0, 0, 0xffffffff, 'seed');
    const privateSeed = this.integer(options.privateSeed ?? 0, 0, 0xffffffff, 'private seed');
    this.object(options.axes ?? {}, 'axes');
    if (Object.keys(options.axes ?? {}).some(id => !definition.axes.some(axis => axis.id === id))) throw new Error('unknown axis');
    const axes = Object.fromEntries(definition.axes.map(axis => {
      const level = options.axes?.[axis.id] ?? 'easy';
      if (typeof level !== 'string' || !Object.hasOwn(axis.levels, level)) throw new Error(`unknown level for ${axis.id}`);
      return [axis.id, level];
    }));
    const parameters = Object.fromEntries(definition.axes.map(axis => [axis.id, structuredClone(axis.levels[axes[axis.id]])]));
    return { seed, privateSeed, axes, parameters };
  }
  static hash(value) { return createHash('sha256').update(typeof value === 'string' || Buffer.isBuffer(value) ? value : JSON.stringify(value)).digest('hex'); }
  static serializable(value) { const encoded = JSON.stringify(value); if (encoded === undefined || encoded.includes('null') && this.nonfinite(value)) throw new Error('nonfinite or unserializable output'); return JSON.parse(encoded); }
  static nonfinite(value) { return typeof value === 'number' ? !Number.isFinite(value) : value !== null && typeof value === 'object' ? Object.values(value).some(item => this.nonfinite(item)) : false; }
}

export class AxisMatrix {
  static expand(definition, mode = 'pairwise') {
    const axes = definition.axes;
    const first = Object.fromEntries(axes.map(axis => [axis.id, Object.keys(axis.levels)[0]]));
    if (mode === 'default') return [first];
    if (mode === 'all') return axes.reduce((rows, axis) => rows.flatMap(row => Object.keys(axis.levels).map(level => ({ ...row, [axis.id]: level }))), [{}]);
    if (!['single', 'pairwise'].includes(mode)) throw new Error('matrix mode must be default, single, pairwise, or all');
    const rows = [first, ...axes.flatMap(axis => Object.keys(axis.levels).slice(1).map(level => ({ ...first, [axis.id]: level })))];
    if (mode === 'pairwise') axes.forEach((left, i) => axes.slice(i + 1).forEach(right => Object.keys(left.levels).forEach(a => Object.keys(right.levels).forEach(b => rows.push({ ...first, [left.id]: a, [right.id]: b })))));
    ['medium', 'hard'].forEach(level => { if (axes.every(axis => Object.hasOwn(axis.levels, level))) rows.push(Object.fromEntries(axes.map(axis => [axis.id, level]))); });
    return [...new Map(rows.map(row => [JSON.stringify(row), row])).values()];
  }
  static coverage(definition, rows) {
    const missing = [];
    definition.axes.forEach((left, i) => definition.axes.slice(i + 1).forEach(right => Object.keys(left.levels).forEach(a => Object.keys(right.levels).forEach(b => {
      if (!rows.some(row => row[left.id] === a && row[right.id] === b)) missing.push({ left: left.id, right: right.id, levels: [a, b] });
    }))));
    return { strength: 2, complete: missing.length === 0, missing };
  }
}
