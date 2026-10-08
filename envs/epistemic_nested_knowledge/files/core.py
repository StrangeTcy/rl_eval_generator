"""Symbolic core for the ``epistemic_nested_knowledge`` family (E4).

Model-independent, deterministic, standard library only.

Source grounding (Mission 02 portfolio, question E4): "On matched finite
epistemic models with the same narrative and first-order facts but different
truth values for registered nested-knowledge formulas, how does model accuracy
vary from first- through higher-order propositions?" Discriminator: exact
truth classification for formula families ``K_i p``, ``K_i K_j p``, and a
bounded higher-order extension, with formula order as the varying factor.

Feasibility rule honored: bounded, explicit finite S5 models. This family
measures classification of registered nested formulas. It does NOT establish
common knowledge, a general theory of mind, or any internal mechanism;
finite-order results here are exactly that and nothing more.

Task shape: the scenario under evaluation is NAMED in the public task, so
this is a model-checking family (recursive evaluation of nested knowledge
over a given finite structure), not inference under hidden state.

Discrimination certificate (rejection at construction)
------------------------------------------------------
An instance is emitted only if the named scenario has a SAME-VALUATION twin
- another scenario agreeing on all first-order facts - at which the
registered formula has the OPPOSITE truth value. Then the first-order facts
of the evaluated scenario alone cannot decide the answer: the nested truth
value is carried by the accessibility structure, which is the contrast the
portfolio asks for.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Tuple

try:
    from shared.epistemic_semantics import public_announcements as _pal
except ImportError:
    try:
        from epistemic_semantics import public_announcements as _pal
    except ImportError:
        import sys as _sys
        from pathlib import Path as _Path

        _REPO_ROOT = str(_Path(__file__).resolve().parents[3])
        if _REPO_ROOT not in _sys.path:
            _sys.path.insert(0, _REPO_ROOT)
        from shared.epistemic_semantics import public_announcements as _pal

AGENTS: Tuple[str, ...] = ("a", "b")
ATOMS: Tuple[str, ...] = ("p", "q")

WORLDS_BY_AXIS: Dict[str, int] = {"four": 4, "six": 6}
ORDER_BY_AXIS: Dict[str, int] = {"first": 1, "second": 2, "third": 3}

#: Rejection bound. Empirical per-attempt discrimination rates at the smallest
#: axis level (four worlds, third order) are ~7%, so 256 attempts bound the
#: per-cell failure probability near 1e-8.
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

Struct = Tuple  # ("atom", prop) | ("neg", struct) | ("knows", agent, struct)


def _formula(struct: Struct) -> "_pal.Formula":
    kind = struct[0]
    if kind == "atom":
        return _pal.atom(struct[1])
    if kind == "neg":
        return _pal.neg(_formula(struct[1]))
    if kind == "knows":
        return _pal.knows(struct[1], _formula(struct[2]))
    raise InstanceConstructionError(f"unknown formula structure {struct!r}")


def formula_text(struct: Struct, vocab: SurfaceVocab) -> str:
    kind = struct[0]
    if kind == "atom":
        return vocab.atom_texts[struct[1]]
    if kind == "neg":
        return f"it is not the case that {formula_text(struct[1], vocab)}"
    if kind == "knows":
        return f"{vocab.agent_names[struct[1]]} knows that {formula_text(struct[2], vocab)}"
    raise InstanceConstructionError(f"unknown formula structure {struct!r}")


def _query_pool(order: int) -> List[Struct]:
    if order == 1:
        return [
            ("knows", "a", ("atom", "p")),
            ("knows", "b", ("atom", "q")),
            ("knows", "b", ("atom", "p")),
            ("neg", ("knows", "a", ("atom", "q"))),
        ]
    if order == 2:
        return [
            ("knows", "a", ("knows", "b", ("atom", "p"))),
            ("knows", "b", ("knows", "a", ("atom", "q"))),
            ("knows", "a", ("knows", "b", ("atom", "q"))),
            ("neg", ("knows", "b", ("knows", "a", ("atom", "p")))),
        ]
    if order == 3:
        return [
            ("knows", "a", ("knows", "b", ("knows", "a", ("atom", "p")))),
            ("knows", "b", ("knows", "a", ("knows", "b", ("atom", "q")))),
        ]
    raise InstanceConstructionError(f"unknown formula order {order!r}")


def _formula_order(struct: Struct) -> int:
    """Number of nested knowledge operators (atoms are order 0)."""
    if struct[0] == "knows":
        return 1 + _formula_order(struct[2])
    if struct[0] == "neg":
        return _formula_order(struct[1])
    return 0


class _Reject(Exception):
    """Internal: this derived-seed attempt does not satisfy the invariants."""


def _gen_model(rng: random.Random, n_worlds: int) -> Tuple["_pal.EpistemicModel", str, dict]:
    worlds = tuple(f"w{i + 1}" for i in range(n_worlds))
    actual = rng.choice(worlds)
    # Bias valuations so the evaluated scenario usually has a same-valuation
    # twin: other worlds copy the actual valuation with probability 0.5.
    # Without this, first-order twins are too rare for the certificate to be
    # reachable at small model sizes.
    actual_valuation = frozenset(x for x in ATOMS if rng.random() < 0.5)
    valuation = {}
    for w in worlds:
        if w == actual:
            valuation[w] = actual_valuation
        elif rng.random() < 0.5:
            valuation[w] = actual_valuation
        else:
            valuation[w] = frozenset(x for x in ATOMS if rng.random() < 0.5)
    for x in ATOMS:
        values = {x in valuation[w] for w in worlds}
        if len(values) != 2:
            raise _Reject(f"atom {x} is constant across worlds")
    partitions = {}
    for agent in AGENTS:
        order = list(worlds)
        rng.shuffle(order)
        cells, rest = [], list(order)
        while rest:
            size = rng.randint(1, min(3, len(rest)))
            cells.append(frozenset(rest[:size]))
            rest = rest[size:]
        if all(len(cell) == 1 for cell in cells):
            raise _Reject(f"agent {agent} has a trivial partition")
        partitions[agent] = frozenset(cells)
    model = _pal.EpistemicModel(
        frozenset(worlds), partitions, {w: valuation[w] for w in worlds}
    )
    return model, actual, valuation


def build_instance(
    worlds: str,
    order: str,
    scenario: str,
    seed: int,
) -> "Instance":
    """Deterministically build one E4 instance; raises on unknown axis values.

    Construction uses derived seeds until the model invariants hold and the
    registered formula is a genuine nested discriminator: its truth must vary
    between two worlds that agree on every first-order fact. Instances that
    reduce to the factual layer are never emitted.
    """
    if worlds not in WORLDS_BY_AXIS:
        raise ValueError(f"unknown worlds level {worlds!r}; options: {sorted(WORLDS_BY_AXIS)}")
    if order not in ORDER_BY_AXIS:
        raise ValueError(f"unknown order level {order!r}; options: {sorted(ORDER_BY_AXIS)}")
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; options: {SCENARIOS}")

    n_worlds = WORLDS_BY_AXIS[worlds]
    depth = ORDER_BY_AXIS[order]

    for attempt in range(MAX_ATTEMPTS):
        rng = random.Random(f"{seed}:{attempt}")
        try:
            model, actual, valuation = _gen_model(rng, n_worlds)
            pool = _query_pool(depth)
            query_struct = pool[rng.randrange(len(pool))]
            if _formula_order(query_struct) != depth:
                raise _Reject("query order does not match the axis")
            query_formula = _formula(query_struct)

            # Discrimination certificate: the evaluated scenario must have a
            # same-valuation twin at which the registered formula flips.
            # Otherwise the first-order facts of the named scenario alone
            # decide the answer and the instance does not test nested-
            # knowledge tracking.
            twins = [
                v for v in model.worlds
                if v != actual and valuation[v] == valuation[actual]
            ]
            if not twins:
                raise _Reject("evaluated scenario has no first-order twin")
            discriminating = any(
                bool(query_formula(model, v)) != bool(query_formula(model, actual))
                for v in twins
            )
            if not discriminating:
                raise _Reject("query truth is decided by first-order facts alone")

            ground_truth = bool(query_formula(model, actual))
            return Instance(
                worlds_axis=worlds,
                order_axis=order,
                scenario=scenario,
                seed=seed,
                attempt=attempt,
                vocab=VOCAB[scenario],
                n_worlds=n_worlds,
                valuation={w: sorted(valuation[w]) for w in sorted(model.worlds)},
                partitions={
                    agent: sorted(sorted(cell) for cell in cells)
                    for agent, cells in sorted(model.partitions.items())
                },
                actual_world=actual,
                query=tuple(query_struct),
                ground_truth=ground_truth,
            )
        except _Reject:
            continue
    raise InstanceConstructionError(
        f"no discriminating construction in {MAX_ATTEMPTS} attempts "
        f"(worlds={worlds} order={order} scenario={scenario} seed={seed})"
    )


@dataclass(frozen=True)
class Instance:
    worlds_axis: str
    order_axis: str
    scenario: str
    seed: int
    attempt: int
    vocab: SurfaceVocab
    n_worlds: int
    valuation: Dict[str, List[str]]
    partitions: Dict[str, List[List[str]]]
    actual_world: str
    query: Tuple
    ground_truth: bool

    def to_spec(self) -> dict:
        """Judge-side specification with full provenance (JSON-safe)."""
        return {
            "family": "epistemic_nested_knowledge",
            "question": "E4",
            "worlds": self.worlds_axis,
            "order": self.order_axis,
            "scenario": self.scenario,
            "seed": self.seed,
            "attempt": self.attempt,
            "n_worlds": self.n_worlds,
            "valuation": self.valuation,
            "partitions": self.partitions,
            "actual_world": self.actual_world,
            "query_formula": list(self.query),
            "query_order": _formula_order(self.query),
            "ground_truth": self.ground_truth,
        }

    # -- public rendering ------------------------------------------------------

    def _world_label(self, w: str) -> str:
        return self.vocab.world_labels[int(w[1:]) - 1]

    def _semantics_box(self) -> str:
        return (
            "Semantics: scenarios form a finite S5 model. Each agent's "
            "indistinguishability relation is a partition over the scenarios. "
            "'X knows that F' holds at a scenario iff F holds at every "
            "scenario X cannot distinguish from it; nested knowledge is "
            "evaluated recursively in the same model. The question asks for "
            "the truth of the registered formula at the scenario named under "
            "'Scenario under evaluation'."
        )

    def _model_block(self) -> str:
        lines = ["## The model (common knowledge)"]
        lines.append("Scenarios and the facts that hold in each:")
        for w in sorted(self.valuation):
            label = self._world_label(w)
            facts = [self.vocab.atom_texts[x] for x in self.valuation[w]] or ["no listed facts"]
            lines.append(f"- `{w}` ({label}): {'; '.join(facts)}.")
        lines.append("")
        lines.append("Indistinguishability:")
        for agent in AGENTS:
            name = self.vocab.agent_names[agent]
            parts = []
            for cell in self.partitions[agent]:
                if len(cell) == 1:
                    parts.append(f"identifies {cell[0]} exactly")
                else:
                    parts.append("cannot distinguish " + " from ".join(cell))
            lines.append(f"- {name}: {'; '.join(parts)}.")
        return "\n".join(lines)

    def public_task_md(self) -> str:
        """Render the agent-facing task. Contains NO ground-truth values."""
        parts: List[str] = []
        parts.append(
            f"# Nested Knowledge Task (epistemic_nested_knowledge, order={self.order_axis})"
        )
        parts.append(
            "A registered nested-knowledge proposition must be classified "
            "exactly. Your answer is judged against the exact truth value of "
            "the registered formula at the scenario named below."
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
            "order": self.order_axis,
            "query_order": _formula_order(self.query),
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
            f"(order={self.order_axis})"
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
            "Evaluated the registered nested formula recursively over the "
            "agents' partitions at the actual scenario."
        ),
    }


def _assert_clean(text: str, where: str) -> None:
    if "%%" in text:
        raise InstanceConstructionError(f"rendered text in {where} contains '%%'")
