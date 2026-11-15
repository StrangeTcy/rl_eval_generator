import { Ratio } from './runtime.mjs';

// Public-only reference: enumerate parent assignments and evaluate by walking
// ancestors until the root or the nearest intervention. No oracle imports.
export class CausalReference {
  static distribution(nodes, model, intervention = []) {
    const parents = new Map(model.edges.map(edge => [edge.to, edge])), fixed = new Map(intervention.map(item => [item.node, item.value]));
    const counts = new Map();
    for (const rootBit of [0, 1]) {
      const assignment = nodes.map(node => {
        let cursor = node, parity = 0, steps = 0;
        while (!fixed.has(cursor) && cursor !== model.root) {
          const edge = parents.get(cursor);
          if (!edge || steps++ >= nodes.length) throw new Error('invalid reference ancestry');
          parity ^= edge.flip; cursor = edge.from;
        }
        return (fixed.get(cursor) ?? rootBit) ^ parity;
      }).join('');
      counts.set(assignment, (counts.get(assignment) ?? 0) + 1);
    }
    return [...counts].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([assignment, count]) => ({ assignment, probability: String(new Ratio(count, 2)) }));
  }

  static models(view) {
    const { nodes } = view, offsets = [...view.passive[0].assignment].map(Number), models = [];
    nodes.forEach(root => {
      const children = nodes.filter(node => node !== root);
      const build = (position, edges) => {
        if (position < children.length) {
          const to = children[position];
          nodes.filter(from => from !== to).forEach(from => build(position + 1, [...edges, { from, to, flip: offsets[nodes.indexOf(from)] ^ offsets[nodes.indexOf(to)] }]));
          return;
        }
        if (nodes.some(node => edges.filter(edge => edge.from === node).length > view.grammar.maxChildren)) return;
        const parents = new Map(edges.map(edge => [edge.to, edge.from]));
        if (nodes.some(node => {
          let cursor = node; const seen = new Set();
          while (cursor !== root) {
            if (seen.has(cursor) || !parents.has(cursor)) return true;
            seen.add(cursor); cursor = parents.get(cursor);
          }
          return false;
        })) return;
        const model = { root, edges: edges.slice().sort((a, b) => nodes.indexOf(a.to) - nodes.indexOf(b.to)) };
        if (JSON.stringify(this.distribution(nodes, model)) !== JSON.stringify(view.passive)) return;
        if (view.observations.some(event => JSON.stringify(this.distribution(nodes, model, [{ node: event.node, value: 0 }])) !== JSON.stringify(event.distribution))) return;
        models.push(model);
      };
      build(0, []);
    });
    models.sort((a, b) => { const left = JSON.stringify(a), right = JSON.stringify(b); return left < right ? -1 : left > right ? 1 : 0; });
    if (!models.length) throw new Error('public evidence has no compatible causal tree');
    return models;
  }

  static predictive(nodes, models, intervention) {
    const counts = new Map();
    models.forEach(model => this.distribution(nodes, model, intervention).forEach(row => {
      const tickets = Ratio.parse(row.probability).times(new Ratio(2));
      counts.set(row.assignment, (counts.get(row.assignment) ?? 0n) + tickets.n);
    }));
    return [...counts].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([assignment, count]) => ({ assignment, probability: String(new Ratio(count, 2 * models.length)) }));
  }

  static risk(view, models) {
    return view.targets.reduce((total, target) => {
      const concentration = this.predictive(view.nodes, models, target.intervention).reduce((sum, row) => { const p = Ratio.parse(row.probability); return sum.plus(p.times(p)); }, new Ratio(0));
      return total.plus(new Ratio(1).minus(concentration));
    }, new Ratio(0)).over(new Ratio(view.targets.length));
  }

  static plan(view, models = this.models(view)) {
    const risk = this.risk(view, models), candidates = [];
    if (view.budget.remaining > 0) view.experimentDomain.filter(node => !view.observations.some(event => event.node === node)).forEach(node => {
      const groups = new Map();
      models.forEach(model => {
        const key = JSON.stringify(this.distribution(view.nodes, model, [{ node, value: 0 }]));
        const group = groups.get(key) ?? []; group.push(model); groups.set(key, group);
      });
      if (groups.size < 2) return;
      const expectedRisk = [...groups.values()].reduce((sum, group) => sum.plus(new Ratio(group.length, models.length).times(this.risk(view, group))), new Ratio(0));
      const collision = new Ratio([...groups.values()].reduce((sum, group) => sum + group.length ** 2, 0), models.length ** 2);
      candidates.push({ node, gain: risk.minus(expectedRisk), collision });
    });
    const best = candidates.reduce((chosen, candidate) => chosen === null || candidate.gain.compare(chosen.gain) > 0 || candidate.gain.compare(chosen.gain) === 0 && candidate.collision.compare(chosen.collision) < 0 ? candidate : chosen, null);
    return { node: best?.node ?? null, predictiveRiskReduction: String(best?.gain ?? new Ratio(0)), expectedSupportCollision: String(best?.collision ?? new Ratio(1)), compatibleModels: models.length };
  }

  static answer(view, models = this.models(view)) {
    return { kind: 'submit_model', model: structuredClone(models[0]), identification: models.length === 1 ? 'identified' : 'ambiguous', predictions: view.targets.map(target => ({ id: target.id, distribution: this.predictive(view.nodes, models, target.intervention) })) };
  }

  static reference(view) {
    const models = this.models(view), plan = this.plan(view, models);
    return plan.node === null ? this.answer(view, models) : { kind: 'experiment', node: plan.node };
  }
}
