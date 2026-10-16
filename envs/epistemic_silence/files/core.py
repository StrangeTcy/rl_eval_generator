"""Symbolic core for the ``epistemic_silence`` family (E3).

Model-independent, deterministic, standard library only.

Source grounding (Mission 02 portfolio, question E3): "Does the model update
beliefs correctly when an expected public message is absent, compared to
matched trials where the message is observed?" Discriminator: direction and
magnitude of the posterior.

Feasibility rule honored: posteriors are computed with the accepted CS007
deterministic-silence substrate (``update_on_silence``) and its matched
announcement complement through the CS008 supplied-policy Bayes update.
Rules are pure Boolean predicates over two worlds; fractions are exact. No
probabilistic agent rules and no independence assumptions beyond what the
accepted substrate itself does.

Design
------
Three scenarios, exact rational prior, one or two agents with deterministic
announce-in-these-scenarios rules. The observation axis contrasts the
matched pair:

* ``silence``  - nobody announced; posterior = ``update_on_silence``;
* ``message``  - at least one agent announced; posterior = the same supplied
  policy with realized observation ``announcement``.

Construction certificate (rejection): the realized observation event must
have prior mass strictly between 0 and 1 (informative and realizable), and
the posterior over the registered first scenario must differ from its prior,
so direction is defined and the instance discriminates updating from mere
repetition of the prior. Three scenarios are used because deterministic
rules over two worlds admit only degenerate (0/1) informative posteriors.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, List, Tuple

try:
    from shared.epistemic_semantics import silence as _silence
    from shared.epistemic_semantics import supplied_policy as _policy
except ImportError:
    try:
        from epistemic_semantics import silence as _silence
        from epistemic_semantics import supplied_policy as _policy
    except ImportError:
        import sys as _sys
        from pathlib import Path as _Path

        _REPO_ROOT = str(_Path(__file__).resolve().parents[3])
        if _REPO_ROOT not in _sys.path:
            _sys.path.insert(0, _REPO_ROOT)
        from shared.epistemic_semantics import silence as _silence
        from shared.epistemic_semantics import supplied_policy as _policy

WORLD1, WORLD2, WORLD3 = "w1", "w2", "w3"
WORLDS: Tuple[str, ...] = (WORLD1, WORLD2, WORLD3)

AGENTS_BY_AXIS: Dict[str, Tuple[str, ...]] = {
    "single": ("a",),
    "pair": ("a", "b"),
}
PRIORS_BY_AXIS: Dict[str, Dict[str, Fraction]] = {
    "uniform": {WORLD1: Fraction(1, 3), WORLD2: Fraction(1, 3), WORLD3: Fraction(1, 3)},
    "skewed": {WORLD1: Fraction(1, 2), WORLD2: Fraction(1, 4), WORLD3: Fraction(1, 4)},
}
OBSERVATIONS: Tuple[str, ...] = ("silence", "message")

#: Announce-set candidates (non-empty subsets; membership predicate).
_ANNOUNCE_SETS: Tuple[Tuple[str, ...], ...] = (
    (WORLD1,), (WORLD2,), (WORLD3,),
    (WORLD1, WORLD2), (WORLD1, WORLD3), (WORLD2, WORLD3),
    (WORLD1, WORLD2, WORLD3),
)

#: Rejection bound; per-attempt acceptance is high (most announce-set draws
#: give an event of intermediate mass), so 128 attempts is far beyond need.
MAX_ATTEMPTS = 128


class InstanceConstructionError(RuntimeError):
    """Raised when no construction satisfies the family invariants."""


@dataclass(frozen=True)
class SurfaceVocab:
    agent_names: Dict[str, str]
    world_labels: Dict[str, str]
    scenario_noun: str


VOCAB: Dict[str, SurfaceVocab] = {
    "office": SurfaceVocab(
        agent_names={"a": "Alice", "b": "Bob"},
        world_labels={
            WORLD1: "the ledger was updated",
            WORLD2: "the nightly backup ran",
            WORLD3: "neither the ledger update nor the backup ran",
        },
        scenario_noun="ledger state",
    ),
    "expedition": SurfaceVocab(
        agent_names={"a": "Anders", "b": "Bek"},
        world_labels={
            WORLD1: "the supply cache was moved",
            WORLD2: "the radio check-in happened",
            WORLD3: "neither the cache move nor the check-in happened",
        },
        scenario_noun="cache state",
    ),
}

SCENARIOS: Tuple[str, ...] = tuple(sorted(VOCAB))


class _Reject(Exception):
    """Internal: this derived-seed attempt does not satisfy the invariants."""


def _protocol_from_announce_sets(announce_sets: Dict[str, Tuple[str, ...]]) -> Dict[str, object]:
    """Deterministic Boolean predicate protocol from announce-set choices."""
    protocol = {}
    for agent, announce_set in announce_sets.items():
        members = frozenset(announce_set)
        protocol[agent] = (lambda world, _members=members: world in _members)
    return protocol


def _policy_for(announce_sets: Dict[str, Tuple[str, ...]]) -> Dict[str, Dict[str, Fraction]]:
    """Supplied-policy likelihood table shared by both observations."""
    protocol = _protocol_from_announce_sets(announce_sets)
    table: Dict[str, Dict[str, Fraction]] = {}
    for world in WORLDS:
        silence_likelihood = _silence.silence_event_likelihood(world, protocol)
        table[world] = {
            "silence": silence_likelihood,
            "announcement": Fraction(1) - silence_likelihood,
        }
    return table


def _posterior_for_observation(
    prior: Dict[str, Fraction],
    announce_sets: Dict[str, Tuple[str, ...]],
    observation: str,
) -> Dict[str, Fraction]:
    realized = "silence" if observation == "silence" else "announcement"
    inst = _policy.SuppliedPolicyInstance(
        prior=prior, policy=_policy_for(announce_sets), realized_observation=realized
    )
    return _policy.bayes_update(inst)


def build_instance(
    observation: str,
    protocol: str,
    prior: str,
    scenario: str,
    seed: int,
) -> "Instance":
    """Deterministically build one E3 instance; raises on unknown axis values.

    Construction uses derived seeds until the realized observation event has
    prior mass strictly between 0 and 1 (informative, realizable), which also
    guarantees the posterior differs from the prior.
    """
    if observation not in OBSERVATIONS:
        raise ValueError(f"unknown observation level {observation!r}; options: {OBSERVATIONS}")
    if protocol not in AGENTS_BY_AXIS:
        raise ValueError(f"unknown protocol level {protocol!r}; options: {sorted(AGENTS_BY_AXIS)}")
    if prior not in PRIORS_BY_AXIS:
        raise ValueError(f"unknown prior level {prior!r}; options: {sorted(PRIORS_BY_AXIS)}")
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; options: {SCENARIOS}")

    agents = AGENTS_BY_AXIS[protocol]
    prior_dist = dict(PRIORS_BY_AXIS[prior])

    for attempt in range(MAX_ATTEMPTS):
        rng = random.Random(f"{seed}:{attempt}")
        announce_sets = {
            agent: _ANNOUNCE_SETS[rng.randrange(len(_ANNOUNCE_SETS))] for agent in agents
        }
        table = _policy_for(announce_sets)
        event_mass = sum(
            prior_dist[world] * table[world][observation if observation == "silence" else "announcement"]
            for world in WORLDS
        )
        if not (Fraction(0) < event_mass < Fraction(1)):
            continue
        posterior = _posterior_for_observation(prior_dist, announce_sets, observation)
        counter_observation = "message" if observation == "silence" else "silence"
        counter_posterior = _posterior_for_observation(prior_dist, announce_sets, counter_observation)

        posterior_world1 = posterior[WORLD1]
        prior_world1 = prior_dist[WORLD1]
        if posterior_world1 == prior_world1:
            continue  # cannot happen for informative events, kept as a guard
        direction = "increased" if posterior_world1 > prior_world1 else "decreased"

        return Instance(
            observation_axis=observation,
            protocol_axis=protocol,
            prior_axis=prior,
            scenario=scenario,
            seed=seed,
            attempt=attempt,
            vocab=VOCAB[scenario],
            prior_dist={w: str(prior_dist[w]) for w in WORLDS},
            prior_world1=prior_world1,
            announce_sets={agent: sorted(s) for agent, s in sorted(announce_sets.items())},
            posterior_world1=posterior_world1,
            direction=direction,
            counter_posterior_world1=counter_posterior[WORLD1],
        )
    raise InstanceConstructionError(
        f"no construction in {MAX_ATTEMPTS} attempts (observation={observation} "
        f"protocol={protocol} prior={prior} scenario={scenario} seed={seed})"
    )


@dataclass(frozen=True)
class Instance:
    observation_axis: str
    protocol_axis: str
    prior_axis: str
    scenario: str
    seed: int
    attempt: int
    vocab: SurfaceVocab
    prior_dist: Dict[str, str]
    prior_world1: Fraction
    announce_sets: Dict[str, List[str]]
    posterior_world1: Fraction
    direction: str
    counter_posterior_world1: Fraction

    def to_spec(self) -> dict:
        """Judge-side specification with full provenance (JSON-safe)."""
        return {
            "family": "epistemic_silence",
            "question": "E3",
            "observation": self.observation_axis,
            "protocol": self.protocol_axis,
            "prior": self.prior_axis,
            "scenario": self.scenario,
            "seed": self.seed,
            "attempt": self.attempt,
            "prior_dist": self.prior_dist,
            "prior_world1": str(self.prior_world1),
            "announce_sets": self.announce_sets,
            "posterior_world1": str(self.posterior_world1),
            "direction": self.direction,
            "counter_posterior_world1": str(self.counter_posterior_world1),
        }

    # -- public rendering ------------------------------------------------------

    def _semantics_box(self) -> str:
        return (
            "Semantics: exactly one of the scenario descriptions is the "
            "case, with the stated prior. Every listed agent follows a "
            "deterministic announcement rule: they announce exactly in the "
            "scenarios listed for them, otherwise they stay silent. "
            "Updating conditions the prior on the observed public event "
            "(silence = nobody announced; message = at least one agent "
            "announced). Probabilities are exact rationals."
        )

    def _setup_block(self) -> str:
        lines = ["## The setup (common knowledge)"]
        for w in WORLDS:
            lines.append(f"- `{w}`: {self.vocab.world_labels[w]}.")
        prior_terms = ", ".join(
            f"P(`{w}`) = {Fraction(self.prior_dist[w])}" for w in WORLDS
        )
        lines.append(f"- Prior: {prior_terms}.")
        lines.append("- Announcement rules:")
        for agent in sorted(self.announce_sets):
            name = self.vocab.agent_names[agent]
            targets = ", ".join(f"`{w}`" for w in self.announce_sets[agent])
            lines.append(f"  - {name} announces exactly in: {targets}.")
        return "\n".join(lines)

    def public_task_md(self) -> str:
        """Render the agent-facing task. Contains NO ground-truth values."""
        observed = (
            "nobody announced anything (silence)"
            if self.observation_axis == "silence"
            else "at least one agent announced (a message was made)"
        )
        parts: List[str] = []
        parts.append(
            f"# Belief Update Task (epistemic_silence, observation={self.observation_axis})"
        )
        parts.append(
            "Report the exact posterior probability of the first scenario "
            "after conditioning on the observed public event, plus the "
            "direction of change relative to the prior. Your answer is "
            "judged against the exact rational posterior."
        )
        parts.append("## Semantics")
        parts.append(self._semantics_box())
        parts.append(self._setup_block())
        parts.append("## Observation")
        parts.append(f"It is publicly observed that {observed}.")
        parts.append("## Question")
        parts.append(
            f"1. What is the exact posterior probability of `{WORLD1}` "
            "(as a rational number, e.g. `3/4`)?\n"
            f"2. Relative to the prior, is the probability of `{WORLD1}` "
            "increased, decreased, or unchanged?"
        )
        parts.append("## Answer protocol")
        parts.append(
            "Fill in the `ANSWER` dictionary in `answer.py` (the only file "
            "you should edit): `posterior_world1` is a string rational such "
            "as `3/4` (or `0`, `1`), `direction` is one of `increased`, "
            "`decreased`, `unchanged`, `justification` a short explanation "
            "(max 600 characters). Then run the local format check:\n\n"
            "```\npython -m pytest visible_tests.py -q\n```\n\n"
            "When satisfied, submit (`python /tools/submit.py`)."
        )
        text = "\n\n".join(parts) + "\n"
        _assert_clean(text, "task.md")
        return text

    # -- grading ---------------------------------------------------------------

    def grade(self, answer: object, pass_threshold: float) -> dict:
        """Exact classification: full credit only on exact posterior + direction."""
        parsed, errors = _parse_answer(answer)
        checks = {
            "answer_format_valid": not errors,
            "posterior_correct": False,
            "direction_correct": False,
        }
        metrics: Dict[str, object] = {
            "observation": self.observation_axis,
            "prior_dist": self.prior_dist,
            "prior_world1": str(self.prior_world1),
            "posterior_world1": str(self.posterior_world1),
            "direction": self.direction,
        }
        if errors:
            metrics["posterior_reported"] = None
            metrics["direction_reported"] = None
            metrics["score"] = 0.0
            metrics["strict_correct"] = False
            return {
                "checks": checks,
                "metrics": metrics,
                "failure_mode": "answer_format_invalid",
                "notes": errors,
            }
        posterior_correct = parsed["posterior_world1"] == self.posterior_world1
        direction_correct = parsed["direction"] == self.direction
        checks["posterior_correct"] = posterior_correct
        checks["direction_correct"] = direction_correct
        score = 1.0 if (posterior_correct and direction_correct) else 0.0
        metrics.update(
            {
                "posterior_reported": str(parsed["posterior_world1"]),
                "direction_reported": parsed["direction"],
                "score": score,
                "strict_correct": bool(score),
            }
        )
        if not posterior_correct and direction_correct:
            failure_mode = "wrong_magnitude"
        elif posterior_correct and not direction_correct:
            failure_mode = "wrong_direction"
        elif not posterior_correct:
            failure_mode = "wrong_posterior"
        else:
            failure_mode = "pass"
        notes = [
            f"reported posterior={parsed['posterior_world1']} "
            f"vs ground truth={self.posterior_world1}; reported "
            f"direction={parsed['direction']} vs {self.direction}"
        ]
        return {
            "checks": checks,
            "metrics": metrics,
            "failure_mode": failure_mode,
            "notes": notes,
        }


def _parse_answer(answer: object) -> Tuple[dict, List[str]]:
    errors: List[str] = []
    normalized: dict = {}
    if not isinstance(answer, dict):
        return normalized, [f"ANSWER must be a JSON object, got {type(answer).__name__}"]
    required = ("posterior_world1", "direction", "justification")
    for key in required:
        if key not in answer:
            errors.append(f"missing key {key!r}")
    for key in answer:
        if key not in required:
            errors.append(f"unexpected key {key!r}")
    if "posterior_world1" in answer:
        raw = answer["posterior_world1"]
        if not isinstance(raw, str) or not raw:
            errors.append("posterior_world1 must be a non-empty string rational")
        else:
            try:
                value = Fraction(raw)
            except (ValueError, ZeroDivisionError):
                errors.append(f"posterior_world1 {raw!r} is not a rational")
            else:
                if value < 0 or value > 1:
                    errors.append("posterior_world1 must lie in [0, 1]")
                elif value.denominator > 10000:
                    errors.append("posterior_world1 denominator too large")
                else:
                    normalized["posterior_world1"] = value
    if "direction" in answer:
        d = answer["direction"]
        if d not in ("increased", "decreased", "unchanged"):
            errors.append(f"direction must be increased/decreased/unchanged, got {d!r}")
        else:
            normalized["direction"] = d
    if "justification" in answer:
        j = answer["justification"]
        if not isinstance(j, str) or len(j) == 0:
            errors.append("justification must be a non-empty string")
        elif len(j) > 600:
            errors.append(f"justification exceeds 600 characters ({len(j)})")
        else:
            normalized["justification"] = j
    return normalized, errors


def ground_truth_answer(instance: Instance) -> dict:
    """The deliberately correct answer (judge/dev side only)."""
    return {
        "posterior_world1": str(instance.posterior_world1),
        "direction": instance.direction,
        "justification": (
            "Conditioned the exact prior on the observed public event "
            "(silence or announcement) using the deterministic rules."
        ),
    }


def _assert_clean(text: str, where: str) -> None:
    if "%%" in text:
        raise InstanceConstructionError(f"rendered text in {where} contains '%%'")
