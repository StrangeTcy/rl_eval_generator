# Evaluation target: structural awareness, not scalar intelligence

This suite is not designed to produce a single intelligence score. A recurring
target is **metis**: applied ingenuity that notices the structure generating the
presented task, preserves invariants across representation changes, resists
misleading frames, and finds valid alternative formulations.

The practical question is not only whether an agent can push harder on the
presented problem. It is whether the agent notices the wall next to the lock:
which interface, invariant, witness, state representation, or resource
protocol actually controls the outcome.

## Intervention families

Many environments are organized around controlled interventions rather than a
single difficulty ladder:

- same semantics, different syntax or labels;
- same public evidence, different narrative framing;
- same rollout orbit, different nominal horizon;
- witness-valid and witness-broken shortcut structure;
- parse and one-step controls before long-horizon interpretation;
- answer-only versus explicitly declared external-scratchpad resources;
- intended interfaces versus valid alternative affordances in weird-machine tasks.

These comparisons are behavioral experiments. They should be reported with the
intervention, seed, horizon, resource protocol, and control status that produced
the result. A score at a longer nominal horizon is not by itself evidence of a
longer internal computation or recurrent architecture.

## Suite taxonomy

| Metis move | Environment pattern |
| --- | --- |
| Representation invariance | Flat versus reflective presentation, relabeling, alpha-renaming |
| Frame resistance | Narrative versus bare-table evidence and seductive-truth controls |
| Shortcut recognition | Witness-valid trajectory cases |
| Shortcut invalidation | Witness-broken sibling cases |
| Interface refusal | Weird-machine and unintended-affordance tasks |
| State tracking under noise | Retention and controlled long-horizon tasks |
| Proof and provenance discipline | Derivation, witness, and explanation-from-evidence tasks |
| Resource awareness | Choosing tools, avoiding brute force, and using tests effectively |

### Trajectory semantics

The trajectory-relay family tests whether an agent can hold an invariant across
representation changes and recognize when syntactically different cases share
the same transition structure. Flat and reflective presentations,
relabelings, witness interventions, and parse/one-step controls separate that
question from raw rollout length. See the direct-answer benchmark description
in the [README](../README.md) and the execution contract in
[`docs/suite_execution.md`](suite_execution.md).

### Epistemic games

The epistemic-games family tests whether an agent follows public evidence rather
than allowing a narrative to become an unstated premise. Narrative and bare
presentations, hidden-world relabelings, and public-only oracle checks separate
Bayesian arithmetic from framing and provenance errors. The oracle validates the
configured reference behavior; it is not evidence about a model's private
reasoning process.

### Weird machines and unintended interfaces

The weird-machine family treats interface refusal as a benchmark principle. An
agent may need to recognize an unintended but valid computational substrate,
representation, or invariant instead of repeatedly applying the intended
interface. This is analogous to noticing an alternative entry point in a
security problem, but the benchmark still grades only declared, reproducible
behavior.

### Evaluation infrastructure

The provider, scheduler, checkpoint, and isolation layers apply the same
structural-awareness discipline to the evaluation process: do not spend money
or assume entitlement when a zero-call inventory, account-specific preflight,
budget guard, or safer execution path can answer the operational question
first. This is an engineering constraint, not a model score.

## Interpretation discipline

The motivating hypothesis is that frontier models can show high local
problem-solving force while missing the substrate or framing that generates the
problem. Treat that as a hypothesis, not an established result. A failure may
instead reflect parsing, prompt format, context truncation, provider behavior,
underspecification, or an invariant the benchmark author did not anticipate.

Controls and provenance are what make a structural-awareness interpretation
credible. Keep direct-answer, solver-synthesis, recurrent-depth, epistemic, and
ML-repair results in separate scoreboards. Report behavioral sensitivity to the
named intervention, not a scalar intelligence claim or an unsupported claim
about hidden model architecture.
