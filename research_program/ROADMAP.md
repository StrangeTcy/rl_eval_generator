# Epistemic Compiler Research Program

Status: source-mined roadmap plus two new static, provider-free environment slices.  No model performance result is claimed by this document.

## Scientific boundary

The canonical ideas log is the imported 118-node/301-edge graph in `../epistemic-compiler/knowledge/`. Its graph relations are interpretive annotations; external links are leads unless independently verified. Mission 01 is a bounded diagnostic: its own claim ceiling rejects broad claims about sheaf theory, independent agents, judge accuracy, or coordination. The active recursive-gluing redesign is therefore treated as a sibling workstream and is not reimplemented here.

The program keeps five levels separate:

1. source record;
2. interpretation or candidate mechanism;
3. environment proposal;
4. implementation/readiness evidence;
5. measured model result.

## Portfolio

| Priority | Family | Target capability | Existing basis | Main gap | Falsifying experiment |
|---|---|---|---|---|---|
| P0 | `epistemic_deception` | Attribute accurate speech, falsehood, omission, framing, and error while separately choosing an action | `epistemic_games`, shared epistemic semantics | Existing games do not score mechanism and incentive attribution together | Matched falsehood/error and omission/framing twins; a mechanism-blind action policy must lose attribution points |
| P0 | `epistemic_signaling` | Deploy an information-bearing signal under private type and receiver response | `epistemic_games`, `information_policy.py`, strategy `game` | No separate action/deployment score | Change audit policy and receiver payoff; fixed “always disclose” and “always conceal” baselines must fail |
| P0 | judge integrity | Distinguish correct output from provenance, shortcut, and evaluator exploitation | `shared/patch_validator.py`, source validator, twin tools, Mission 01 C01/C02 | Independent reference and alternate-judge coverage remains family-specific | Run reference solver, malformed outputs, visible-test overfits, and alternate oracle on identical cases |
| P1 | reflexive control | Predict opponent adaptation when observations/interventions change behavior | intervention/twin infrastructure and strategy `meta` | Existing interventions mostly test presentation/measurement, not adaptive opponents | Disclosed vs blind audit policy with identical facts and explicit predicted response |
| P1 | latent structure | Discover a hidden representation or invariant and transfer it to held-out cases | category-theoretic, weird-machine, and strategy-IR families | Success can be explained by supplied representation or template retrieval | Equivalent presentation twins, held-out topology/rule composition, minimized counterexamples |
| P1 | epistemic attention | Select what to inspect under endogenous information cost | graph nodes `rational-inattention`, `attention-manipulation` | No dedicated environment in current registry | Inspection-cost intervention versus exhaustive-information control |
| P2 | recursive composition | Discover and compose recursive rules over held-out structures | active recursive-gluing sibling family | Needs current sibling protocol and independent non-gluing transfer families | Held-out depth/topology plus enumeration and memoization baselines |
| P2 | evaluation awareness | Measure protocol-conditioned behavior and metagaming | graph nodes `evaluation-awareness`, `evaluation-gaming`; campaign arms | No unified disclosed/blind/adversarial protocol family | Same task under evaluator disclosure arms and immutable trace comparison |

## Implemented vertical slices

### `epistemic_deception`

- **Mechanism:** explicit speaker knowledge, incentive, proposition, evidence, message, and audit response.
- **Agent observation:** public statement plus an evidence ledger; the mechanism label and ground truth remain hidden.
- **Agent output:** mechanism, speaker knowledge, incentive, recommended action, counterfactual response to independent audit, and short justification.
- **Generator:** deterministic surface variation over office/expedition scenarios, five mechanisms, two incentive regimes, two visibility regimes, two task modes.
- **Judge:** provenance rebuild, safe literal answer extraction, field-level grading, and failure taxonomy (`mechanism_misattribution`, `incentive_blindness`, `adaptive_opponent_missed`).
- **Controls:** accurate vs falsehood, omission vs framing, error vs strategic cases; action correctness cannot substitute for mechanism correctness.
- **Scientific ceiling:** passing establishes exact externally observable attribution on the generated case, not an internal deception detector.

### `epistemic_signaling`

- **Mechanism:** a private strong/weak type chooses disclose/omit/frame while a receiver chooses approve/reject.
- **Agent observation:** public receiver constraints, audit cost, and private type.
- **Agent output:** signal, receiver action prediction, incentive, and communication mechanism.
- **Purpose:** separate deploying a strategic signal from detecting another agent's deception.
- **Scientific ceiling:** passing establishes policy selection against the declared payoff abstraction; it does not establish real-world social intelligence.

Both families use `shared/deception_game.py`, literal answer parsing, provenance rebuilds, and registry-driven generation. The recursive-gluing directories were not changed.

## Capability-to-evidence rules

- **Correct instance solving:** all required answer fields match the independently rebuilt case.
- **Mechanism inference:** `mechanism` matches while action and other fields are scored separately.
- **Incentive reasoning:** the incentive field and action shift under aligned/conflicted controls.
- **Opponent modeling:** `counterfactual` predicts audit adaptation; this is observable behavior, not a private thought report.
- **Generalization:** performance remains high on held-out surface templates, seeds, and scenario mappings.
- **Shortcut rejection:** performance must fall on mechanism twins for a baseline that only keys on role or narrative, while a mechanism-aware solver remains stable.
- **Transfer:** a representation or strategy only transfers when the target family has a separate generator and independently defined judge.

## Dependencies and expansion order

1. Static source review and schema checks.
2. Provider-free generation and judge preflight in an isolated sandbox.
3. Independent reference solvers plus adversarial baselines.
4. Repeated seeds and paired counterfactuals.
5. Authorized model campaigns only after readiness artifacts are complete.
6. Cross-family transfer: deception → signaling → adaptive control, with recursive-gluing kept as an explicit external sibling.

## Deferred or rejected ideas

- Treating Mission 01's `Sheaf-Cocycle` label as a mathematical result: rejected by its claim ceiling.
- Adding more narrative lie-detection prompts: deferred; they do not separate error, omission, framing, incentives, or action.
- Claiming hidden reasoning from explanations: rejected; the suite scores structured external artifacts and independently verifiable answers.
- Calling the current environment zoo a capability taxonomy solely from names or archived pass rates: rejected; `PILOT_EVIDENCE.md` and the Mercury handoff show why case density, single seeds, judge guarantees, and selection must be reported.
