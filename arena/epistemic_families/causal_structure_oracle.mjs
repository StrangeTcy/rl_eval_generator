import { Contract, Ratio } from './runtime.mjs';

// Independent controller oracle: enumerate undirected Prüfer trees, choose a
// root, then propagate values outward. No reference-policy code is imported.
export class CausalOracle {
  static nodes(nodes) {
    if (!Array.isArray(nodes) || nodes.includes(undefined) || nodes.length < 3 || nodes.length > 5 || new Set(nodes).size !== nodes.length || nodes.some(node => typeof node !== 'string' || !/^[A-Za-z][A-Za-z0-9_]{0,47}$/.test(node))) throw new Error('three to five distinct bounded node labels required');
    return nodes;
  }

  static validateModel(model, nodes, maxChildren) {
    this.nodes(nodes);
    Contract.integer(maxChildren, 1, 4, 'maxChildren');
    Contract.fields(model, ['root', 'edges']);
    if (!nodes.includes(model.root) || !Array.isArray(model.edges) || model.edges.includes(undefined) || model.edges.length !== nodes.length - 1) throw new Error('one root and n-1 edges required');
    const parents = new Map(), children = new Map(nodes.map(node => [node, []]));
    model.edges.forEach(edge => {
      Contract.fields(edge, ['from', 'to', 'flip']);
      Contract.integer(edge.flip, 0, 1, 'binary flip');
      if (!nodes.includes(edge.from) || !nodes.includes(edge.to) || edge.from === edge.to || edge.to === model.root || parents.has(edge.to)) throw new Error('valid unique non-root parent required');
      parents.set(edge.to, edge.from);
      children.get(edge.from).push(edge.to);
    });
    if ([...children.values()].some(items => items.length > maxChildren)) throw new Error('branching bound exceeded');
    const reached = new Set(), pending = [model.root];
    while (pending.length) {
      const node = pending.shift();
      if (reached.has(node)) throw new Error('cycle in causal model');
      reached.add(node); pending.push(...children.get(node));
    }
    if (reached.size !== nodes.length) throw new Error('causal model must be one connected rooted tree');
    return { root: model.root, edges: model.edges.map(edge => ({ from: edge.from, to: edge.to, flip: edge.flip })).sort((a, b) => nodes.indexOf(a.to) - nodes.indexOf(b.to)) };
  }

  static intervention(nodes, intervention) {
    if (!Array.isArray(intervention) || intervention.includes(undefined) || intervention.length > nodes.length) throw new Error('bounded intervention required');
    const fixed = new Map();
    intervention.forEach(item => {
      Contract.fields(item, ['node', 'value']);
      Contract.integer(item.value, 0, 1, 'binary intervention');
      if (!nodes.includes(item.node) || fixed.has(item.node)) throw new Error('known distinct intervention nodes required');
      fixed.set(item.node, item.value);
    });
    return fixed;
  }

  static distribution(nodes, model, intervention = []) {
    const canonical = this.validateModel(model, nodes, 4), fixed = this.intervention(nodes, intervention);
    const children = new Map(nodes.map(node => [node, []]));
    canonical.edges.forEach(edge => children.get(edge.from).push(edge));
    const counts = new Map();
    for (const rootBit of [0, 1]) {
      const values = new Map([[canonical.root, fixed.get(canonical.root) ?? rootBit]]), pending = [canonical.root];
      while (pending.length) {
        const parent = pending.shift();
        children.get(parent).forEach(edge => {
          values.set(edge.to, fixed.get(edge.to) ?? (values.get(parent) ^ edge.flip));
          pending.push(edge.to);
        });
      }
      const assignment = nodes.map(node => values.get(node)).join('');
      counts.set(assignment, (counts.get(assignment) ?? 0) + 1);
    }
    return [...counts].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([assignment, count]) => ({ assignment, probability: String(new Ratio(count, 2)) }));
  }

  static trees(nodes, maxChildren = 4, offsets = nodes.map(() => 0)) {
    this.nodes(nodes); Contract.integer(maxChildren, 1, 4, 'maxChildren');
    if (!Array.isArray(offsets) || offsets.includes(undefined) || offsets.length !== nodes.length) throw new Error('one binary offset per node required');
    offsets.forEach(value => Contract.integer(value, 0, 1, 'offset'));
    const n = nodes.length, trees = [];
    const decode = sequence => {
      const degrees = Array(n).fill(1), links = [];
      sequence.forEach(node => { degrees[node] += 1; });
      sequence.forEach(node => {
        const leaf = degrees.findIndex(degree => degree === 1);
        links.push([leaf, node]); degrees[leaf] -= 1; degrees[node] -= 1;
      });
      links.push(degrees.flatMap((degree, index) => degree === 1 ? [index] : []));
      const neighbors = Array.from({ length: n }, () => []);
      links.forEach(([a, b]) => { neighbors[a].push(b); neighbors[b].push(a); });
      for (let root = 0; root < n; root += 1) {
        const reached = new Set([root]), pending = [root], edges = [];
        let permitted = true;
        while (pending.length) {
          const from = pending.shift(), descendants = neighbors[from].filter(to => !reached.has(to));
          if (descendants.length > maxChildren) permitted = false;
          descendants.forEach(to => { reached.add(to); pending.push(to); edges.push({ from: nodes[from], to: nodes[to], flip: offsets[from] ^ offsets[to] }); });
        }
        if (permitted) trees.push({ root: nodes[root], edges: edges.sort((a, b) => nodes.indexOf(a.to) - nodes.indexOf(b.to)) });
      }
    };
    const extend = prefix => {
      if (prefix.length === n - 2) { decode(prefix); return; }
      for (let node = 0; node < n; node += 1) extend([...prefix, node]);
    };
    extend([]);
    return trees.sort((a, b) => {
      const left = JSON.stringify(a), right = JSON.stringify(b);
      return left < right ? -1 : left > right ? 1 : 0;
    });
  }

  static count(nodes, maxChildren = 4) { return this.trees(nodes, maxChildren).length; }

  static compatible(view) {
    const offsets = [...view.passive[0].assignment].map(Number);
    return this.trees(view.nodes, view.grammar.maxChildren, offsets).filter(model =>
      JSON.stringify(this.distribution(view.nodes, model)) === JSON.stringify(view.passive)
      && view.observations.every(event => JSON.stringify(this.distribution(view.nodes, model, [{ node: event.node, value: 0 }])) === JSON.stringify(event.distribution)));
  }

  static predictive(nodes, models, intervention) {
    if (!models.length) throw new Error('nonempty causal support required');
    const mass = new Map();
    models.forEach(model => this.distribution(nodes, model, intervention).forEach(row => {
      const probability = Ratio.parse(row.probability).over(new Ratio(models.length));
      mass.set(row.assignment, (mass.get(row.assignment) ?? new Ratio(0)).plus(probability));
    }));
    return [...mass].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([assignment, probability]) => ({ assignment, probability: String(probability) }));
  }

  static risk(view, models) {
    return view.targets.reduce((total, target) => {
      const concentration = this.predictive(view.nodes, models, target.intervention).reduce((sum, row) => { const p = Ratio.parse(row.probability); return sum.plus(p.times(p)); }, new Ratio(0));
      return total.plus(new Ratio(1).minus(concentration));
    }, new Ratio(0)).over(new Ratio(view.targets.length));
  }

  static informative(view, models) {
    return view.experimentDomain.filter(node => !view.observations.some(event => event.node === node)).filter(node =>
      new Set(models.map(model => JSON.stringify(this.distribution(view.nodes, model, [{ node, value: 0 }])))).size > 1);
  }
}
