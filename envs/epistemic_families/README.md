# Epistemic family YAML configurations

These files configure the nine interactive epistemic families. Each file selects
a public seed, a private seed, and one level for every named difficulty axis.
The checked-in settings use `seed: 3`, `privateSeed: 7`, and `easy` on every axis.

| Family | Configuration |
|---|---|
| Reconstruct another agent | [agent_reconstruction.yaml](agent_reconstruction.yaml) |
| Choose an investigation | [inquiry_control.yaml](inquiry_control.yaml) |
| Construct a hidden law | [hypothesis_discovery.yaml](hypothesis_discovery.yaml) |
| Diagnose an evidence process | [evidence_process.yaml](evidence_process.yaml) |
| Forecast an adapting agent | [adaptive_agents.yaml](adaptive_agents.yaml) |
| Delegate through a hierarchy | [recursive_delegation.yaml](recursive_delegation.yaml) |
| Predict and revise for an evaluator | [evaluator_prediction.yaml](evaluator_prediction.yaml) |
| Revise connected beliefs | [belief_revision.yaml](belief_revision.yaml) |
| Investigate after limited retention | [memory_inquiry.yaml](memory_inquiry.yaml) |

## Setup and first run

Use Node.js 24. Run these commands from the repository root:

```sh
npm ci
node tools/epistemic_families.mjs validate-config envs/epistemic_families/memory_inquiry.yaml
node tools/epistemic_families.mjs show memory_inquiry --config envs/epistemic_families/memory_inquiry.yaml
node tools/epistemic_families.mjs run memory_inquiry --config envs/epistemic_families/memory_inquiry.yaml --output epistemic-memory-run
node tools/epistemic_families.mjs replay epistemic-memory-run
```

`show` prints the initial public view. `run` uses the built-in `reference` policy
by default and writes an episode, source hashes, a checksum, and replay evidence.
These runs exercise the environment and scorer; they are not model evaluations.
Each output directory must be new, and its parent directory must already exist.

To generate an instance package for an external policy:

```sh
node tools/epistemic_families.mjs generate memory_inquiry --config envs/epistemic_families/memory_inquiry.yaml --output epistemic-memory-instance
```

The generated `agent/` directory contains public initial material, and
`controller/instance.json` contains the private configuration. Keep YAML configs,
private seeds, controller files, and full audit records on the controller side.
The policy receives only the current JSON view on each invocation, including the
memory family's restricted view after its retention boundary.

## Setting difficulty

Change any axis value to `easy`, `medium`, or `hard`. Comments beside each axis
describe its effect and the concrete value associated with each level. The
definitions in `arena/epistemic_families/<family>.mjs` remain the source of truth;
the YAML selects those levels without duplicating executable definitions.
Level names do not establish an empirical ordering of difficulty for every model.

Command-line options override the YAML settings:

```sh
node tools/epistemic_families.mjs show memory_inquiry --config envs/epistemic_families/memory_inquiry.yaml --seed 19 --private-seed 23 --axes '{"retention":"hard","retrievals":"hard"}'
node tools/epistemic_families.mjs show inquiry_control --config envs/epistemic_families/inquiry_control.yaml --difficulty medium,hard,easy,medium
```

`--axes` merges the supplied named levels over the YAML axes. `--difficulty`
replaces the axes with a complete ordered vector. Its order is the order reported
by `describe FAMILY`, which also supplies all current level definitions:

```sh
node tools/epistemic_families.mjs list
node tools/epistemic_families.mjs describe inquiry_control
node tools/epistemic_families.mjs matrix inquiry_control --mode pairwise
```

Use either `--axes` or `--difficulty` in one invocation. `--config` and
`--instance` cannot be combined: a generated instance already records its
configuration and source identity. The family argument must match the YAML's
`family` field. Validation rejects unrecognized fields, axes, and levels.
It also rejects duplicate keys, multiple YAML documents, aliases, custom tags,
and invalid seeds. Seeds must be integers from 0 through 4294967295. The `axes`
mapping is required; omitted axis entries default to `easy`, and omitted seeds
default to zero.

The resolved settings are saved in generated instances and episode records.
Editing a YAML preset later does not change those saved settings or prevent
their replay. Replay still requires the same implementation and dependency
manifest hashes as the original recording.

## Validation workflow

The GitHub Actions workflow
[epistemic-families-validation.yml](../../.github/workflows/epistemic-families-validation.yml)
validates the configurations and exercises reference episodes with replay checks
across all nine families. It also provides a manual `workflow_dispatch` trigger.
Regression tests cover default and all-hard settings. The workflow saves a
pairwise axis coverage plan for each family; that plan is a configuration
inventory, not a record of model evaluations.

Run the same regression suite locally with `npm test`.

## Model campaign workflows

The [Mercury](../../.github/workflows/epistemic-mercury-campaign.yml) and
[reasoning Atria](../../.github/workflows/epistemic-reasoning-atria-campaign.yml)
workflows provide manual planning, reference runs and live model evaluations
across all nine families. They support configured, single-axis and pairwise
difficulty plans, bounded provider requests, episode evidence and checkpoint
resume. See the [campaign guide](../../docs/workflows/epistemic-family-campaigns.md)
for inputs, secrets, resource ceilings and continuation instructions.

These interactive environments use their own
[registry.json](registry.json) and `tools/epistemic_families.mjs` launcher.
The existing Python patch-task registry and `generate_env.py` use a different
environment contract; these files are consumed by the interactive launcher.
