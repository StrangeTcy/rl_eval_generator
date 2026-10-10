#!/usr/bin/env python3
"""Offline instrument for the observational-equivalence reasoning operator.

The experiment question is whether *telling* a model to enumerate the states
compatible with its observations, check whether the evidence separates them, and
preserve the uncertainty when it does not, improves its reasoning about hidden
agent types and beliefs.

This tool answers the half of that question that can be answered without a model,
and answers it in the only form that does not overreach: the arms are the *same*
generated instances, the prompt text differs by exactly the appended procedure
block (byte-checked, and `tools/family.py` proves the two members share a
`pair_id`), and the answer sources are deterministic procedures rather than a
sampled model.  So every number here is a statement about the procedures the
instructions prescribe - what a model would score if it followed them exactly -
and no number here is a model result.  See the claim ceiling in
`spec/observational-equivalence-check.yaml`.

Three arms, one per declared overlay:

  control               the task as shipped, answered by the bounded heuristics the
                        repository already ships in `tools/epistemic_probe.py`
  state_enumeration     enumerate the compatible states and commit to the one the
                        enumeration supports (`state_enumeration` overlay)
  equivalence_check     enumerate, then gate the commit on whether the evidence
                        actually separates the states (`equivalence_check` overlay)
  equivalence_check_literal
                        the same gate, but obeyed literally where the response format
                        has no value for "underdetermined": the answer is withheld,
                        which the existing judges score as an invalid submission.
                        This arm exists to price the transfer clause, nothing else.

Identifiability is derived, never read from a convenient field: for each instance
the tool computes the set of hidden states that could have produced exactly this
public observation, using information the agent is given.  An instance is
non-identifiable when that set has more than one member and they are observationally
indistinguishable.  Whether the *hidden state* or the *answer* is what an
environment conceals is a property of the environment, declared below and checked
against the rendered prompt rather than assumed.

Usage:
    python tools/equivalence_check_study.py --seeds 3,4,5 --out runs/operator_study
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import sys
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from tools import epistemic_probe as probe  # noqa: E402

ARMS = (
    "control",
    "state_enumeration",
    "equivalence_check",
    "equivalence_check_literal",
    "equivalence_check_revised",
)
OPERATOR_TEXT_DIR = ROOT / "spec" / "operators"
#: arm -> the file that holds the block the overlay lays over the env's task template.
#: The instrument and the environment read the *same* file: what this tool hands a
#: procedure is character-for-character what a model would read, so a result here
#: cannot be a transcription of the instruction rather than the instruction.
OVERLAY_FILES = {
    "state_enumeration": "state_enumeration.md",
    "equivalence_check": "equivalence_check.md",
    "equivalence_check_literal": "equivalence_check.md",
    # The revision is priced before its text is laid over any environment template: it
    # is the one arm with no env-side declaration, so a result that favors it cannot
    # be read as if a v2 prompt already exists in the registry.
    "equivalence_check_revised": "equivalence_check_revised.md",
}
PROPOSED_OVERLAY_ID = "equivalence_check_revised"
PROPOSED_BLOCK = """
## Required procedure: observational equivalence before inference (revised)

Before committing to a hidden state, an agent type, or a truth value:

1. Enumerate the states compatible with what is observable here. Use only the
   information given above. Do not invent an observation, and do not drop a state
   because a more familiar one is available.
2. Ask whether the available evidence separates those states, comparing them on every
   observable. A state no observation in this task can reach is not excluded by that
   absence.
3. Where the evidence distinguishes the states, answer from the distinction and name
   the observation doing the work.
4. Where it does not, say so about *this evidence* and no further: report that the
   observation fails to separate the states, while still giving the posterior your
   prior and this evidence jointly support. Underdetermined evidence is not a
   uniform posterior, and it is not a licence to answer "neither" when the stated
   prior already leans somewhere. Keep the answer internally consistent: whatever
   degree of support you report, commit only to what that number implies.

This procedure changes only how you reach an answer. It does not change the task, the
answer format, or what is graded.
"""
#: Which variable the environment hides from the answerer.  `epistemic_games` hides
#: which world is actual, so the answerer's compatible set is the interesting one.
#: The two modal environments name the scenario under evaluation in the prompt, so
#: their answerer's set is a singleton by construction and the uncertainty clause has
#: nothing to bite on - which is the transfer finding, not a missing stratum.
HIDDEN_VARIABLE = {
    "epistemic_games": "actual_world",
    "epistemic_nested_knowledge": "actual_world",
    "epistemic_fragmented_observation": "actual_world",
}


def load_core(env_name: str):
    """Import one environment's `core.py` the way the judge does (path import)."""
    path = ROOT / "envs" / env_name / "files" / "core.py"
    module_name = f"operator_core_{env_name}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def axis_grid(env_name: str, cap: int) -> Tuple[List[Dict[str, str]], List[str]]:
    """Full factorial over the environment's own axes, in config order, capped."""
    config = yaml.safe_load((ROOT / "envs" / env_name / "config.yaml").read_text())
    axes = [(str(a["id"]), list((a.get("levels") or {}).keys())) for a in config["axes"]]
    grid: List[Dict[str, str]] = [{}]
    for axis_id, levels in axes:
        grid = [{**row, axis_id: level} for row in grid for level in levels]
    order = [axis_id for axis_id, _ in axes]
    return grid[:cap], order


def build(core, levels: Dict[str, str], seed: int):
    """Call the environment's own builder, passing only the kwargs it accepts."""
    params = inspect.signature(core.build_instance).parameters
    kwargs = {name: value for name, value in levels.items() if name in params}
    aliases = {"scenario": "template", "prior": "prior_id"}
    for axis_id, value in levels.items():
        if axis_id in aliases and aliases[axis_id] in params and aliases[axis_id] not in kwargs:
            kwargs[aliases[axis_id]] = value
    return core.build_instance(seed=seed, **kwargs)


# --------------------------------------------------------------------------- identity

def compatible_worlds_games(instance) -> List[str]:
    """Worlds that could have produced this exact observation (public information only).

    `instance.hypotheses[world].behavior[action]` is the probability that world's
    player utters the observed action; a world assigning it zero probability is
    excluded by the observation, and one assigning it positive probability survives
    it.  This is step 1 of the operator, run on the tables the agent is handed.
    """
    observation = str(instance.observation)
    survivors: List[str] = []
    for world in ("world1", "world2"):
        behavior = instance.hypotheses[world].behavior
        probability = behavior.get(observation, Fraction(0))
        if Fraction(probability) > 0:
            survivors.append(world)
    return survivors


def observation_is_identical(instance, worlds: Sequence[str]) -> bool:
    """True when the surviving worlds assign the observation the same likelihood."""
    likelihoods = [
        Fraction(instance.hypotheses[world].behavior[str(instance.observation)])
        for world in worlds
    ]
    return len(set(likelihoods)) <= 1


def answerer_cell_size(core, instance, text: str) -> int:
    """How many scenarios the answerer can still be in, from the public text alone.

    The modal environments name the scenario under evaluation in the prompt, so the
    answerer's cell is a singleton and every question they are asked is identifiable.
    Checked against the rendered text rather than asserted, because if the scenario
    were withheld the stratum would exist and the study would have to measure it.
    """
    if hasattr(instance, "actual_world") and str(instance.actual_world) in text:
        return 1
    spec = instance.to_spec()
    return max(1, len(spec.get("valuation") or {}))


def identifiability(core, env_name: str, instance, text: str) -> Dict[str, Any]:
    if env_name == "epistemic_games":
        survivors = compatible_worlds_games(instance)
        identical = observation_is_identical(instance, survivors) if len(survivors) > 1 else False
        return {
            "compatible_states": list(survivors),
            "compatible_state_count": len(survivors),
            "observations_identical_across_compatible_states": bool(identical),
            "identifiable": not (len(survivors) > 1 and identical),
            "hidden_variable": HIDDEN_VARIABLE[env_name],
        }
    cell = answerer_cell_size(core, instance, text)
    return {
        "compatible_states": [str(getattr(instance, "actual_world", ""))],
        "compatible_state_count": cell,
        "observations_identical_across_compatible_states": False,
        "identifiable": cell == 1,
        "hidden_variable": HIDDEN_VARIABLE[env_name],
    }


# ------------------------------------------------------------------------- procedures

@dataclass
class Arm:
    """One answer procedure, with the prompt text it is prescribed by."""

    name: str
    overlay_file: str | None
    policy: Callable[[Any, Any], Dict[str, Any]]
    notes: Dict[str, Any] = field(default_factory=dict)


def games_control(core, instance) -> Dict[str, Any]:
    """The repository's own bounded heuristics, at the instance the arm was given."""
    public = probe.public_info(instance)
    return probe.baseline_seductive(public)


def games_enumerate(core, instance) -> Dict[str, Any]:
    """Enumerate, update, and always name a supporting state - the commit clause alone.

    Deliberately *not* a strawman: the verdict band comes from the enumeration, so this
    arm reports `indistinguishable` whenever the evidence really fails to separate the
    worlds. What it lacks is only the clause that stops at that point - it still names a
    `most_supported` world at a tie. That isolates the one component measurement 2 is
    about, instead of grading a handicapped reasoner for being handicapped.
    """
    public = probe.public_info(instance)
    answer = dict(probe.oracle_from_public(public))
    posterior = float(answer["posterior_world1"])
    answer["most_supported"] = "world1" if posterior >= 0.5 else "world2"
    answer["justification"] = (
        "Enumerated both worlds against the transcript's behavior tables and named the "
        f"better supported one (P(W1)={posterior:.4f})."
    )
    return answer


def games_gated(core, instance) -> Dict[str, Any]:
    """Enumerate, update, then commit only if the evidence separates the states."""
    public = probe.public_info(instance)
    answer = probe.oracle_from_public(public)
    posterior = float(answer["posterior_world1"])
    survivors = compatible_worlds_games(instance)
    indistinguishable = len(survivors) > 1 and observation_is_identical(instance, survivors)
    if indistinguishable:
        return {
            "posterior_world1": posterior,
            "verdict": "indistinguishable",
            "most_supported": "neither",
            "justification": (
                f"Both worlds assign positive probability to the observed action and "
                f"agree on its likelihood, so the transcript cannot separate them; the "
                f"posterior stays at the prior ({posterior:.4f}) and no unique "
                f"explanation is asserted."
            ),
        }
    return dict(answer)


def games_literal(core, instance) -> Dict[str, Any]:
    return games_gated(core, instance)


def games_gated_revised(core, instance) -> Dict[str, Any]:
    """Enumerate, gate the *claim about the evidence*, keep the posterior the prior supports.

    Step 4 as written ("preserve the uncertainty ... answer the weakest the format
    allows") reads in this environment as "answer neither", and `most_supported` is
    defined by the posterior, not by the evidence's separative power. So on a skewed
    prior with an uninformative transcript the shipped clause turns a correct verdict
    into a wrong support claim. This is that clause with its scope fixed.
    """
    public = probe.public_info(instance)
    answer = dict(probe.oracle_from_public(public))
    survivors = compatible_worlds_games(instance)
    if len(survivors) > 1 and observation_is_identical(instance, survivors):
        answer["verdict"] = "indistinguishable"
        answer["justification"] = (
            "Both worlds assign positive probability to the observed action and agree "
            "on its likelihood, so this transcript separates nothing; the posterior "
            f"stays where the prior puts it ({answer['posterior_world1']:.4f}) and the "
            "support claim follows that number rather than the missing evidence."
        )
    return answer


def factual_layer_answer(struct, valuation: Dict[str, List[str]], world: str) -> bool:
    """Evaluate the query's propositional skeleton at one scenario, operators stripped.

    Both epistemic operators collapse to their operand: `knows` for the nested family,
    `joint_entails` for the fragmented one (whose own `_formula` does exactly this
    collapse for the truth-functional fragment). What is left is the atom's truth at
    the scenario under evaluation - the reading these families construct instances to
    defeat.
    """
    kind = struct[0]
    if kind == "atom":
        return struct[1] in (valuation.get(world) or [])
    if kind == "neg":
        return not factual_layer_answer(struct[1], valuation, world)
    if kind == "knows":
        return factual_layer_answer(struct[2], valuation, world)
    if kind == "joint_entails":
        return factual_layer_answer(struct[1], valuation, world)
    raise ValueError(f"unknown formula structure {struct!r}")


def modal_control(core, instance) -> Dict[str, Any]:
    """Answer what the facts say at the scenario, ignoring who knows what.

    This is the failure the two modal families are built to catch: their instances are
    constructed so the registered formula varies between scenarios that agree on every
    first-order fact, so a factual-layer reading is not a weak guess, it is the
    specific wrong computation.
    """
    spec = instance.to_spec()
    truth = factual_layer_answer(
        tuple(spec["query_formula"]), spec.get("valuation") or {}, str(spec["actual_world"])
    )
    return {
        "truth": bool(truth),
        "justification": "Read off which facts hold at the scenario under evaluation.",
    }


def modal_enumerate(core, instance) -> Dict[str, Any]:
    return dict(core.ground_truth_answer(instance))


def modal_gated(core, instance) -> Dict[str, Any]:
    """The gate, in an environment whose answer format has no underdetermined value.

    The instruction's fourth step says to report the states as indistinguishable or
    give the weakest answer the format allows. The format allows a boolean and nothing
    else, so there is no answer that preserves the uncertainty: the enumeration is
    reported with the uncertainty recorded in prose, and the graded field is unchanged.
    """
    answer = dict(core.ground_truth_answer(instance))
    answer["justification"] = (
        "Enumerated the scenarios compatible with the published model; the response "
        "format has no value for 'underdetermined', so the enumerated answer is given "
        "with the residual uncertainty stated here."
    )
    return answer


def modal_literal(core, instance) -> Dict[str, Any]:
    """Obey the abstention clause literally: withhold the graded field."""
    return {
        "truth": None,
        "justification": (
            "The proposition is not separated by the published model alone; no unique "
            "answer is asserted, per the required procedure."
        ),
    }


POLICIES: Dict[str, Dict[str, Callable[[Any, Any], Dict[str, Any]]]] = {
    "epistemic_games": {
        "control": games_control,
        "state_enumeration": games_enumerate,
        "equivalence_check": games_gated,
        "equivalence_check_literal": games_literal,
        "equivalence_check_revised": games_gated_revised,
    },
    "epistemic_nested_knowledge": {
        "control": modal_control,
        "state_enumeration": modal_enumerate,
        "equivalence_check": modal_gated,
        "equivalence_check_literal": modal_literal,
        "equivalence_check_revised": modal_gated,
    },
    "epistemic_fragmented_observation": {
        "control": modal_control,
        "state_enumeration": modal_enumerate,
        "equivalence_check": modal_gated,
        "equivalence_check_literal": modal_literal,
        "equivalence_check_revised": modal_gated,
    },
}


def render_prompt(core, env_name: str, instance, arm: Arm) -> str:
    """The arm's exact prompt: the shipped render, plus the overlay block verbatim.

    The block is taken from the same `files/task_*.md` the generated twins bake, so the
    prompt this study hands the procedure is the prompt a real episode would hand the
    model - and the diff against the control is the overlay and nothing else.
    """
    text = instance.public_task_md()
    if arm.overlay_file is None:
        return text
    block = (OPERATOR_TEXT_DIR / arm.overlay_file).read_text()
    if arm.name == PROPOSED_OVERLAY_ID and not (OPERATOR_TEXT_DIR / arm.overlay_file).is_file():
        block = PROPOSED_BLOCK  # pragma: no cover - the file is written by the same commit
    return text + "\n" + block if arm.name == PROPOSED_OVERLAY_ID else text + "\n" + block


def arms_for(env_name: str, core) -> List[Arm]:
    policies = POLICIES[env_name]
    return [
        Arm(name=arm, overlay_file=OVERLAY_FILES.get(arm), policy=policies[arm])
        for arm in ARMS
    ]


# ------------------------------------------------------------------------------ report

def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Predeclared statistics, per stratum. Pooling is reported and labelled.

    Per-group rows are primary because the two strata predict opposite effects: the
    gate can only help where there is something to be uncertain about, and an aggregate
    over both strata is the arithmetic that would let a null in one cancel a gain in the
    other and be read as a wash.
    """
    from collections import defaultdict

    out: Dict[str, Any] = {}
    by_env: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_env[row["environment"]].append(row)
    for env_name, env_rows in sorted(by_env.items()):
        strata: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in env_rows:
            strata["identifiable" if row["identifiability"]["identifiable"] else "non_identifiable"].append(row)
        strata["pooled"] = env_rows
        per: Dict[str, Any] = {}
        for stratum, group in sorted(strata.items()):
            by_arm: Dict[str, Any] = {}
            # Sorted, not a set comprehension: iteration order of a set of string tuples
            # follows PYTHONHASHSEED, which reorders `pairs` below and changes the
            # permutation p from run to run while leaving every closed-form statistic
            # still. A result file that differs between two runs of the same code is a
            # bug in the tool, whatever it says about the effect.
            keys = sorted({(r["environment"], r["seed"], r["case_id"]) for r in group})
            matched = {key: {arm: None for arm in ARMS} for key in keys}
            for row in group:
                matched[(row["environment"], row["seed"], row["case_id"])][row["arm"]] = row
            for arm in ARMS:
                present = [r for r in group if r["arm"] == arm]
                if not present:
                    continue
                correct = sum(1 for r in present if r["strict_correct"])
                scores = [float(r["score"]) for r in present]
                def _rate(key: str) -> Tuple[float | None, List[float] | None]:
                    values = [r for r in present if r["flags"].get(key) is not None]
                    if not values:
                        return None, None
                    hits = sum(1 for r in values if r["flags"][key])
                    lo, hi = probe.wilson_interval(hits, len(values))
                    return round(hits / len(values), 4), [round(lo, 4), round(hi, 4)]

                separation, separation_ci = _rate("claims_a_separation")
                over, over_ci = _rate("overcommits")
                under, under_ci = _rate("undercommits")
                nonident = sum(1 for r in present if not r["identifiability"]["identifiable"])
                withheld = sum(1 for r in present if r["answer_format_valid"] is False)
                lower, upper = probe.wilson_interval(correct, len(present))
                by_arm[arm] = {
                    "n": len(present),
                    "strict_accuracy": round(correct / len(present), 4),
                    "wilson95": [round(lower, 4), round(upper, 4)],
                    "mean_score": round(sum(scores) / len(scores), 4),
                    "claims_a_separation_rate": separation,
                    "claims_a_separation_wilson95": separation_ci,
                    "overcommit_rate": over,
                    "overcommit_wilson95": over_ci,
                    "undercommit_rate": under,
                    "undercommit_wilson95": under_ci,
                    "answer_withheld_rate": round(
                        sum(1 for r in present if r["flags"]["answer_withheld"]) / len(present), 4
                    ),
                    "non_identifiable_n": nonident,
                    "format_invalid_rate": round(withheld / len(present), 4),
                }
            pairs = [v for v in matched.values() if all(v[a] is not None for a in ARMS)]
            contrasts: Dict[str, Any] = {}
            for arm in ARMS[1:]:
                b = sum(1 for v in pairs if v["control"]["strict_correct"] and not v[arm]["strict_correct"])
                c = sum(1 for v in pairs if not v["control"]["strict_correct"] and v[arm]["strict_correct"])
                diffs = [
                    float(v[arm]["score"]) - float(v["control"]["score"]) for v in pairs
                ]
                perm_p = probe.paired_permutation_p(diffs) if diffs else None
                _wilcoxon_stat, wilcoxon_p, _wilcoxon_n = probe.wilcoxon_signed_rank(diffs) if diffs else (None, None, 0)
                contrasts[arm] = {
                    "matched_pairs": len(pairs),
                    "control_only_correct": b,
                    "arm_only_correct": c,
                    "mcnemar_exact_p": probe.exact_mcnemar_p(b, c),
                    "newcombe95_on_arm_minus_control": [
                        round(v, 4) for v in probe.newcombe_paired_diff_interval(c, b, len(pairs) or 1)
                    ],
                    "wilcoxon_p_on_score_diff": wilcoxon_p,
                    "permutation_p_on_score_diff": perm_p,
                    "mean_score_diff": round(sum(diffs) / len(diffs), 4) if diffs else None,
                }
            per[stratum] = {"arms": by_arm, "contrasts_vs_control": contrasts}
        out[env_name] = per
    return out


def _p(value: float | None) -> str:
    """One rendering of a p-value for both outputs, so the table cannot disagree with the file."""
    return "n/a" if value is None else (f"{value:.4f}" if value >= 0.0001 else "<0.0001")


def print_table(summary: Dict[str, Any]) -> None:
    for env_name, per in summary.items():
        print(f"\n=== {env_name} ===")
        for stratum, block in per.items():
            print(f"  -- {stratum}")
            print(
                f"    {'arm':<28}{'n':>5}{'accuracy':>10}{'score':>8}"
                f"{'separation':>12}{'over':>7}{'under':>8}{'withheld':>10}{'invalid':>9}"
            )
            for arm, v in block["arms"].items():
                cell = lambda value: "-" if value is None else format(value, ".3f")
                print(
                    f"    {arm:<28}{v['n']:>5}{v['strict_accuracy']:>10.3f}{v['mean_score']:>8.3f}"
                    f"{cell(v['claims_a_separation_rate']):>12}{cell(v['overcommit_rate']):>7}"
                    f"{cell(v['undercommit_rate']):>8}{v['answer_withheld_rate']:>10.2f}"
                    f"{v['format_invalid_rate']:>9.2f}"
                )
            for arm, c in block["contrasts_vs_control"].items():
                print(
                    f"      vs control {arm}: pairs={c['matched_pairs']} "
                    f"arm-only={c['arm_only_correct']} control-only={c['control_only_correct']} "
                    f"McNemar={_p(c['mcnemar_exact_p'])} "
                    f"Newcombe95(arm-control)={c['newcombe95_on_arm_minus_control']} "
                    f"Wilcoxon={_p(c['wilcoxon_p_on_score_diff'])} "
                    f"mean dScore={c['mean_score_diff']}"
                )


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--envs", default=",".join(sorted(POLICIES)))
    parser.add_argument("--seeds", default="3,4,5")
    parser.add_argument("--grid-cap", type=int, default=64,
                        help="max axis combinations per seed per environment")
    parser.add_argument("--out", type=Path, default=ROOT / "runs" / "operator_study")
    args = parser.parse_args(argv)

    env_names = [e.strip() for e in args.envs.split(",") if e.strip()]
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    args.out.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, Any]] = []
    for env_name in env_names:
        core = load_core(env_name)
        grid, axis_order = axis_grid(env_name, args.grid_cap)
        arms = arms_for(env_name, core)
        for seed in seeds:
            for levels in grid:
                try:
                    instance = build(core, levels, seed)
                except Exception as exc:  # construction refusals are data, not crashes
                    rows.append({
                        "environment": env_name, "seed": seed, "levels": levels,
                        "build_error": f"{type(exc).__name__}: {exc}",
                    })
                    continue
                spec = instance.to_spec()
                case_id = f"{env_name}__" + "_".join(f"{k}={levels[k]}" for k in axis_order if k in levels) + f"__seed-{seed}"
                base_text = instance.public_task_md()
                identity = identifiability(core, env_name, instance, base_text)
                for arm in arms:
                    prompt = render_prompt(core, env_name, instance, arm)
                    answer = arm.policy(core, instance)
                    graded = instance.grade(answer, float(
                        (yaml.safe_load((ROOT / "envs" / env_name / "config.yaml").read_text())
                         .get("scoring") or {}).get("pass_threshold", 0.85)
                    ))
                    metrics = graded.get("metrics") or {}
                    checks = graded.get("checks") or {}
                    rows.append({
                        "environment": env_name,
                        "seed": seed,
                        "case_id": case_id,
                        "levels": dict(levels),
                        "arm": arm.name,
                        "overlay_file": arm.overlay_file,
                        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                        "prompt_chars_added": len(prompt) - len(base_text),
                        "identifiability": identity,
                        "answer": answer,
                        "failure_mode": graded.get("failure_mode"),
                        "strict_correct": bool(metrics.get("strict_correct")),
                        "score": float(metrics.get("score", 0.0)),
                        "answer_format_valid": bool(checks.get("answer_format_valid", True)),
                        "flags": flags(env_name, answer, checks, metrics),
                        "grade_checks": checks,
                        "grade_metrics": metrics,
                        "grade_notes": list(graded.get("notes") or []),
                        "spec": spec,
                    })
    raw = args.out / "raw_results.jsonl"
    with raw.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    summary = summarize([r for r in rows if "arm" in r])
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(f"rows: {len(rows)} -> {raw}")
    print_table(summary)
    (args.out / "summary.md").write_text(render_markdown(summary, rows), encoding="utf-8")
    return 0


def flags(env_name: str, answer: Dict[str, Any], checks: Dict[str, Any], metrics: Dict[str, Any]) -> Dict[str, Any]:
    """The three ways an answer can mishandle underdetermination, kept separate on purpose.

    `claims_a_separation` is the failure the operator exists to remove: asserting that the
    observations distinguish states they do not. Reporting only that, though, rewards any
    answer that refuses - so the same table charges `overcommits` (naming a supported state
    the graded answer does not support) and `undercommits` (withholding support the prior and
    evidence *do* carry), which is how the shipped clause loses the skewed-prior cases.
    Environments whose response format has no underdetermined value cannot score either
    error, and say so rather than reporting a zero.
    """
    out: Dict[str, Any] = {
        "claims_a_separation": None,
        "overcommits": None,
        "undercommits": None,
        "answer_withheld": answer.get("truth") is None and "truth" in answer,
    }
    if env_name != "epistemic_games":
        out["uncertainty_inexpressible"] = True
        return out
    verdict_true = metrics.get("verdict_true")
    verdict_reported = metrics.get("verdict_reported")
    support_true = metrics.get("most_supported_true")
    support_reported = metrics.get("most_supported_reported")
    if verdict_true is not None and verdict_reported is not None:
        out["claims_a_separation"] = bool(
            verdict_true == "indistinguishable" and verdict_reported != "indistinguishable"
        )
    if support_true is not None and support_reported is not None:
        out["overcommits"] = bool(support_reported != "neither" and support_true == "neither")
        out["undercommits"] = bool(support_reported == "neither" and support_true != "neither")
    out["uncertainty_inexpressible"] = False
    return out


def render_markdown(summary: Dict[str, Any], rows: List[Dict[str, Any]]) -> str:
    """The same numbers as stdout, from the same dict, so the two cannot drift."""
    lines = [
        "# Observational-equivalence operator: offline instrument results",
        "",
        "Deterministic procedures on matched generated instances. No model was contacted;",
        "see the claim ceiling in `spec/observational-equivalence-check.yaml`.",
        "",
    ]
    for env_name, per in summary.items():
        lines.append(f"## {env_name}")
        for stratum, block in per.items():
            lines.append("")
            lines.append(f"### {stratum}")
            lines.append("")
            lines.append(
                "| arm | n | strict accuracy | Wilson 95% | mean score | claims a separation "
                "| over-commits | under-commits | answer withheld | format invalid |"
            )
            lines.append("|---|---|---|---|---|---|---|---|---|---|")
            for arm, v in block["arms"].items():
                def cell(key: str) -> str:
                    value = v.get(key)
                    return "n/a" if value is None else f"{value:.3f}"
                ci = v["wilson95"]
                lines.append(
                    f"| `{arm}` | {v['n']} | {v['strict_accuracy']:.3f} | {ci[0]:.3f}-{ci[1]:.3f} "
                    f"| {v['mean_score']:.3f} | {cell('claims_a_separation_rate')} "
                    f"| {cell('overcommit_rate')} | {cell('undercommit_rate')} "
                    f"| {v['answer_withheld_rate']:.2f} | {v['format_invalid_rate']:.2f} |"
                )
            lines.append("")
            lines.append("Matched-pair contrasts against `control` (same instance, both arms):")
            lines.append("")
            for arm, c in block["contrasts_vs_control"].items():
                lines.append(
                    f"- `{arm}`: {c['matched_pairs']} pairs, arm-only {c['arm_only_correct']}, "
                    f"control-only {c['control_only_correct']}, exact McNemar {_p(c['mcnemar_exact_p'])}, "
                    f"exact Wilcoxon {_p(c['wilcoxon_p_on_score_diff'])}, Newcombe 95% on the "
                    f"arm-minus-control accuracy difference "
                    f"{c['newcombe95_on_arm_minus_control']}, mean score "
                    f"\u0394 {c['mean_score_diff']}"
                )
        lines.append("")
    builds = [r for r in rows if "build_error" in r]
    if builds:
        lines.append(f"## Construction refusals ({len(builds)})")
        lines.append("")
        for row in builds[:12]:
            lines.append(f"- `{row['environment']}` seed {row['seed']} {row['levels']}: {row['build_error']}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
