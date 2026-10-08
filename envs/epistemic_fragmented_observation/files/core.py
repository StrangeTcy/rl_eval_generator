"""Symbolic core for the ``epistemic_fragmented_observation`` family (E5).

Model-independent, deterministic, standard library only.

Source grounding (Mission 02 portfolio, question E5): "With the narrative and
base rules fixed, does model truth-judgment track changes to the registered
observation matrix as the agents' perspectives become more
asymmetric/fragmented?" Discriminator: exact truth classification of
registered propositions about the pooled (distributed) information set.

Feasibility rule honored: pooled information is computed with the accepted
CS011 substrate (``joint_information``) on bounded finite S5 models. Per the
substrate's own boundary, this is NOT communication: pooling intersects
observation cells; it does not implement announcements and does not
establish individual or common knowledge.

Task shape: the scenario under evaluation is NAMED in the public task, so
this is a model-checking family over registered observation matrices, not
inference under hidden state.

Discrimination certificate (rejection at construction), per axis level
----------------------------------------------------------------------
* ``asymmetric``: emitted only if, at the named scenario, the pooled (joint)
  information set is a PROPER subset of each individual agent's observation
  cell - pooling strictly adds information, so no single perspective alone
  can answer the registered proposition.
* ``symmetric``: both agents share one matrix, so pooling cannot shrink the
  cell; emitted only if the registered proposition is NOT decided by the
  named scenario's own facts - i.e. some scenario in the observed cell
  evaluates the proposition's payload differently. The answer then requires
  the full cell, not just the evaluated scenario.

Together the two levels give the portfolio contrast: identical narrative and
base rules, varied registered observation matrix.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Tuple

try:
    from shared.epistemic_semantics import fragmented_observation as _cso
    from shared.epistemic_semantics import public_announcements as _pal
except ImportError:
    try:
        from epistemic_semantics import fragmented_observation as _cso
        from epistemic_semantics import public_announcements as _pal
    except ImportError:
        import sys as _sys
        from pathlib import Path as _Path

        _REPO_ROOT = str(_Path(__file__).resolve().parents[3])
        if _REPO_ROOT not in _sys.path:
            _sys.path.insert(0, _REPO_ROOT)
        from shared.epistemic_semantics import fragmented_observation as _cso
        from shared.epistemic_semantics import public_announcements as _pal

AGENTS: Tuple[str, ...] = ("a", "b")
ATOMS: Tuple[str, ...] = ("p", "q")

WORLDS_BY_AXIS: Dict[str, int] = {"four": 4, "six": 6}
FRAGMENTS: Tuple[str, ...] = ("symmetric", "asymmetric")

#: Rejection bound, matching the E4 family (empirical per-attempt certificate
#: rates at the smallest axis level stay comfortably above the implied floor).
MAX_ATTEMPTS = 256


class InstanceConstructionError(RuntimeError):
    """Raised when no construction satisfies the family invariants."""


@dataclass(frozen=True)
class SurfaceVocab:
    agent_names: Dict[str, str]
    world_labels: Tuple[str, ...]
    atom_texts: Dict[str, str]


VOCAB: Dict[str, SurfaceVocab] = {
    "office": SurfaceVocab(
        agent_names={"a": "Alice", "b": "Bob"},
        world_labels=(
            "the archive room", "the print room", "the server room",
            "the records vault", "the mail room", "the loading dock",
        ),
        atom_texts={"p": "the ledger was updated", "q": "the nightly backup ran"},
    ),
    "expedition": SurfaceVocab(
        agent_names={"a": "Anders", "b": "Bek"},
        world_labels=(
            "the ridge camp", "the river fork", "the glacier shelf",
            "the moraine", "the icefall", "the summit saddle",
        ),
        atom_texts={"p": "the supply cache was moved", "q": "the radio check-in happened"},
    ),
}

SCENARIOS: Tuple[str, ...] = tuple(sorted(VOCAB))

Struct = Tuple  # ("atom", prop) | ("neg", struct) | ("joint_entails", struct)


def formula_text(struct: Struct, vocab: SurfaceVocab) -> str:
    kind = struct[0]
    if kind == "atom":
        return vocab.atom_texts[struct[1]]
    if kind == "neg":
        return f"it is not the case that {formula_text(struct[1], vocab)}"
    if kind == "joint_entails":
        names = " and ".join(vocab.agent_names[a] for a in AGENTS)
        return (
            f"pooling {names}'s observations pins down that "
            f"{formula_text(struct[1], vocab)}"
        )
    raise InstanceConstructionError(f"unknown formula structure {struct!r}")


def _query_pool() -> List[Struct]:
    return [
        ("joint_entails", ("atom", "p")),
        ("joint_entails", ("atom", "q")),
        ("neg", ("joint_entails", ("atom", "p"))),
        ("neg", ("joint_entails", ("atom", "q"))),
    ]


class _Reject(Exception):
    """Internal: this derived-seed attempt does not satisfy the invariants."""


def _gen_partition(rng: random.Random, worlds: List[str]) -> frozenset:
    rest, cells = list(worlds), []
    while rest:
        size = rng.randint(1, min(3, len(rest)))
        cells.append(frozenset(rest[:size]))
        rest = rest[size:]
    return frozenset(cells)


def _gen_model(
    rng: random.Random, n_worlds: int, fragment: str
) -> Tuple["_pal.EpistemicModel", str, dict]:
    worlds = tuple(f"w{i + 1}" for i in range(n_worlds))
    actual = rng.choice(worlds)
    valuation = {
        w: frozenset(x for x in ATOMS if rng.random() < 0.5) for w in worlds
    }
    for x in ATOMS:
        values = {x in valuation[w] for w in worlds}
        if len(values) != 2:
            raise _Reject(f"atom {x} is constant across worlds")

    if fragment == "symmetric":
        partition = _gen_partition(rng, list(worlds))
        if all(len(cell) == 1 for cell in partition):
            raise _Reject("trivial partition")
        partitions = {"a": partition, "b": partition}
    else:  # asymmetric
        part_a = _gen_partition(rng, list(worlds))
        part_b = _gen_partition(rng, list(worlds))
        if all(len(cell) == 1 for cell in part_a) or all(
            len(cell) == 1 for cell in part_b
        ):
            raise _Reject("trivial partition")
        if part_a == part_b:
            raise _Reject("asymmetric axis requires distinct observation matrices")
        partitions = {"a": part_a, "b": part_b}

    model = _pal.EpistemicModel(
        frozenset(worlds), partitions, {w: valuation[w] for w in worlds}
    )
    return model, actual, valuation


def _joint_cell(model: "_pal.EpistemicModel", actual: str) -> frozenset:
    return _cso.joint_information(model, list(AGENTS), actual)


def build_instance(
    worlds: str,
    fragment: str,
    scenario: str,
    seed: int,
) -> "Instance":
    """Deterministically build one E5 instance; raises on unknown axis values.

    Construction uses derived seeds until the model invariants hold and the
    pooling certificate fires: the joint information set must be a proper
    subset of each individual observation cell at the actual world, so the
    registered observation matrix is genuinely required.
    """
    if worlds not in WORLDS_BY_AXIS:
        raise ValueError(f"unknown worlds level {worlds!r}; options: {sorted(WORLDS_BY_AXIS)}")
    if fragment not in FRAGMENTS:
        raise ValueError(f"unknown fragment level {fragment!r}; options: {FRAGMENTS}")
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; options: {SCENARIOS}")

    n_worlds = WORLDS_BY_AXIS[worlds]

    for attempt in range(MAX_ATTEMPTS):
        rng = random.Random(f"{seed}:{attempt}")
        try:
            model, actual, valuation = _gen_model(rng, n_worlds, fragment)
            pool = _query_pool()
            query_struct = pool[rng.randrange(len(pool))]

            joint = _joint_cell(model, actual)
            cells = [model.agent_class(agent, actual) for agent in AGENTS]
            if fragment == "asymmetric":
                # Pooling must strictly add information relative to each
                # individual perspective.
                if not all(joint < cell for cell in cells):
                    raise _Reject("pooling is not strictly informative here")
            else:
                # Symmetric control: pooling cannot shrink a shared cell, so
                # the certificate is that the named scenario's own facts do
                # not decide the proposition - some scenario in the observed
                # cell evaluates the payload differently.
                payload = query_struct[1] if query_struct[0] == "neg" else query_struct
                payload_formula = _formula(payload)
                target_truth = bool(payload_formula(model, actual))
                if not any(
                    bool(payload_formula(model, w)) != target_truth
                    for w in joint
                ):
                    raise _Reject("named scenario facts decide the proposition alone")

            # Ground truth under the accepted substrate.
            ground_truth = _evaluate_query(model, actual, query_struct)
            return Instance(
                worlds_axis=worlds,
                fragment_axis=fragment,
                scenario=scenario,
                seed=seed,
                attempt=attempt,
                vocab=VOCAB[scenario],
                n_worlds=n_worlds,
                valuation={w: sorted(valuation[w]) for w in sorted(model.worlds)},
                partitions={
                    agent: sorted(sorted(cell) for cell in cells_)
                    for agent, cells_ in sorted(model.partitions.items())
                },
                actual_world=actual,
                query=tuple(query_struct),
                joint_size=len(joint),
                ground_truth=ground_truth,
            )
        except _Reject:
            continue
    raise InstanceConstructionError(
        f"no discriminating construction in {MAX_ATTEMPTS} attempts "
        f"(worlds={worlds} fragment={fragment} scenario={scenario} seed={seed})"
    )


def _evaluate_query(model: "_pal.EpistemicModel", actual: str, struct: Struct) -> bool:
    """Evaluate a registered query via the accepted substrate.

    ``joint_entails`` is computed with CS011 ``joint_information``; the inner
    formula is a plain propositional formula, so atom/neg evaluation reuses
    the CS005 truth functional.
    """
    kind = struct[0]
    if kind == "neg":
        return not _evaluate_query(model, actual, struct[1])
    if kind == "joint_entails":
        joint = _cso.joint_information(model, list(AGENTS), actual)
        inner = _formula(struct[1])
        return all(bool(inner(model, w)) for w in sorted(joint))
    if kind == "atom":
        formula = _formula(struct)
        return bool(formula(model, actual))
    raise InstanceConstructionError(f"unknown formula structure {struct!r}")


def _formula(struct: Struct) -> "_pal.Formula":
    """Propositional-only fragment of the query language."""
    kind = struct[0]
    if kind == "atom":
        return _pal.atom(struct[1])
    if kind == "neg":
        return _pal.neg(_formula(struct[1]))
    if kind == "joint_entails":
        return _formula(struct[1])
    raise InstanceConstructionError(f"unknown formula structure {struct!r}")


@dataclass(frozen=True)
class Instance:
    worlds_axis: str
    fragment_axis: str
    scenario: str
    seed: int
    attempt: int
    vocab: SurfaceVocab
    n_worlds: int
    valuation: Dict[str, List[str]]
    partitions: Dict[str, List[List[str]]]
    actual_world: str
    query: Tuple
    joint_size: int
    ground_truth: bool

    def to_spec(self) -> dict:
        """Judge-side specification with full provenance (JSON-safe)."""
        return {
            "family": "epistemic_fragmented_observation",
            "question": "E5",
            "worlds": self.worlds_axis,
            "fragment": self.fragment_axis,
            "scenario": self.scenario,
            "seed": self.seed,
            "attempt": self.attempt,
            "n_worlds": self.n_worlds,
            "valuation": self.valuation,
            "partitions": self.partitions,
            "actual_world": self.actual_world,
            "query_formula": list(self.query),
            "joint_size": self.joint_size,
            "ground_truth": self.ground_truth,
        }

    # -- public rendering ------------------------------------------------------

    def _world_label(self, w: str) -> str:
        return self.vocab.world_labels[int(w[1:]) - 1]

    def _semantics_box(self) -> str:
        names = " and ".join(self.vocab.agent_names[a] for a in AGENTS)
        return (
            "Semantics: scenarios form a finite model; each agent's "
            "observation is a partition over the scenarios (their registered "
            "observation matrix). At a given scenario, an agent observes only "
            "the cell containing it. Pooling observations at a scenario means "
            "intersecting the agents' observed cells there; it does not model "
            "communication and establishes neither individual nor common "
            "knowledge. 'Pooling "
            f"{names}'s observations pins down that F' means F holds in every "
            "scenario surviving the pooled observation. The question asks "
            "about the scenario named under 'Scenario under evaluation'."
        )

    def _model_block(self) -> str:
        lines = ["## The model (common knowledge)"]
        lines.append("Scenarios and the facts that hold in each:")
        for w in sorted(self.valuation):
            label = self._world_label(w)
            facts = [self.vocab.atom_texts[x] for x in self.valuation[w]] or ["no listed facts"]
            lines.append(f"- `{w}` ({label}): {'; '.join(facts)}.")
        lines.append("")
        lines.append("Registered observation matrices:")
        for agent in AGENTS:
            name = self.vocab.agent_names[agent]
            parts = []
            for cell in self.partitions[agent]:
                if len(cell) == 1:
                    parts.append(f"observes {cell[0]} exactly")
                else:
                    parts.append("cannot distinguish " + " from ".join(cell))
            lines.append(f"- {name}: {'; '.join(parts)}.")
        return "\n".join(lines)

    def public_task_md(self) -> str:
        """Render the agent-facing task. Contains NO ground-truth values."""
        parts: List[str] = []
        parts.append(
            "# Fragmented Observation Task (epistemic_fragmented_observation, "
            f"fragment={self.fragment_axis})"
        )
        parts.append(
            "A registered proposition about pooled observations must be "
            "classified exactly. Your answer is judged against the exact "
            "truth value at the scenario named below."
        )
        parts.append("## Semantics")
        parts.append(self._semantics_box())
        parts.append(self._model_block())
        parts.append("## Scenario under evaluation")
        parts.append(f"`{self.actual_world}` ({self._world_label(self.actual_world)})")
        parts.append("## Question")
        parts.append(
            f"Is it the case, at scenario `{self.actual_world}` "
            f"({self._world_label(self.actual_world)}), that "
            f"{formula_text(self.query, self.vocab)}?"
        )
        parts.append("## Answer protocol")
        parts.append(
            "Fill in the `ANSWER` dictionary in `answer.py` (the only file "
            "you should edit): `truth` is a JSON boolean, `justification` a "
            "short explanation (max 600 characters). Then run the local "
            "format check:\n\n"
            "```\npython -m pytest visible_tests.py -q\n```\n\n"
            "When satisfied, submit (`python /tools/submit.py`)."
        )
        text = "\n\n".join(parts) + "\n"
        _assert_clean(text, "task.md")
        return text

    # -- grading ---------------------------------------------------------------

    def grade(self, answer: object, pass_threshold: float) -> dict:
        """Exact classification: full credit only on the exact truth value."""
        parsed, errors = _parse_answer(answer)
        checks = {"answer_format_valid": not errors, "truth_correct": False}
        metrics: Dict[str, object] = {
            "fragment": self.fragment_axis,
            "joint_size": self.joint_size,
            "ground_truth": self.ground_truth,
        }
        if errors:
            metrics["truth_reported"] = None
            metrics["score"] = 0.0
            metrics["strict_correct"] = False
            return {
                "checks": checks,
                "metrics": metrics,
                "failure_mode": "answer_format_invalid",
                "notes": errors,
            }
        truth_correct = parsed["truth"] == self.ground_truth
        checks["truth_correct"] = truth_correct
        score = 1.0 if truth_correct else 0.0
        metrics.update(
            {
                "truth_reported": parsed["truth"],
                "score": score,
                "strict_correct": truth_correct,
            }
        )
        notes = [
            f"reported truth={parsed['truth']} vs ground truth={self.ground_truth} "
            f"(fragment={self.fragment_axis})"
        ]
        return {
            "checks": checks,
            "metrics": metrics,
            "failure_mode": "pass" if truth_correct else "wrong_truth",
            "notes": notes,
        }


def _parse_answer(answer: object) -> Tuple[dict, List[str]]:
    errors: List[str] = []
    normalized: dict = {}
    if not isinstance(answer, dict):
        return normalized, [f"ANSWER must be a JSON object, got {type(answer).__name__}"]
    required = ("truth", "justification")
    for key in required:
        if key not in answer:
            errors.append(f"missing key {key!r}")
    for key in answer:
        if key not in required:
            errors.append(f"unexpected key {key!r}")
    if "truth" in answer:
        t = answer["truth"]
        if not isinstance(t, bool):
            errors.append(f"truth must be a boolean, got {t!r}")
        else:
            normalized["truth"] = t
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
        "truth": instance.ground_truth,
        "justification": (
            "Intersected the agents' observation cells at the actual "
            "scenario and evaluated the registered proposition over the "
            "surviving scenarios."
        ),
    }


def _assert_clean(text: str, where: str) -> None:
    if "%%" in text:
        raise InstanceConstructionError(f"rendered text in {where} contains '%%'")
