"""Symbolic core for the ``epistemic_announcements`` environment family (E2).

Model-independent, deterministic, standard library only.

Source grounding (Mission 02 portfolio, question E2): "In formally matched
dynamic-epistemic instances that differ only in the number or order of
truthful public announcements, how does exact truth-classification accuracy
change with update depth?" Discriminator: exact classification of a
registered knowledge proposition after the updates, with a matched one-step
factual control. Feasibility rule honored here: the event model, truth
conditions, and text rendering rule are frozen below before any measurement.

Semantics
---------
Finite propositional S5 models (worlds, per-agent partitions, valuation) from
the accepted CS005/CS002 substrate ``shared.epistemic_semantics.
public_announcements``. Announcements are truthful at the actual world
(``public_announce_checked``) and restrict the model: surviving worlds AND
restricted indistinguishability cells. The task is to evaluate the registered
query formula in the FINAL restricted model.

The obvious shortcut — keeping only the surviving worlds while ignoring the
partition restriction — is exactly the conflation this family discriminates:
instances whose NESTED query truth is invariant under announcement depth are
rejected at construction (truncation-flip certificate), so every emitted
nested instance requires relational updating, not just world filtering.
Factual (atomic) queries are the matched control: atom truths survive every
truthful restriction, so their classification is depth-invariant by design —
the depth contrast lives across the query axis, not inside one instance.

What this family does and does not measure
------------------------------------------
Behavioral: exact truth classification after sequential updates. It does NOT
establish internal update rules, attention, or a general theory-of-mind
capability; labels describe task structure only.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Tuple

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

WORLDS_BY_AXIS: Dict[str, int] = {"three": 3, "four": 4}
#: Target announcement counts by depth axis. A chain targets three steps but
#: realizes at most ``n_worlds - 1`` informative ones (each informative
#: announcement removes at least one world); the realized count is recorded
#: in the spec. Chains must realize at least two steps (enforced in build).
DEPTH_BY_AXIS: Dict[str, int] = {"one": 1, "chain": 3}
QUERY_KINDS: Tuple[str, ...] = ("factual", "nested")

#: Deterministic construction budget: derived-seed attempts until every
#: invariant holds. Rejection at construction is the family's guarantee that
#: no non-discriminating instance is ever emitted.
MAX_ATTEMPTS = 64


class InstanceConstructionError(RuntimeError):
    """Raised when no construction satisfies the family invariants."""


# ---------------------------------------------------------------------------
# Surface vocabulary (varies to reduce retrieval cues; shared within instance)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SurfaceVocab:
    agent_names: Dict[str, str]
    world_labels: Tuple[str, ...]
    atom_texts: Dict[str, str]


VOCAB: Dict[str, SurfaceVocab] = {
    "office": SurfaceVocab(
        agent_names={"a": "Alice", "b": "Bob"},
        world_labels=(
            "the archive room", "the print room", "the server room", "the records vault",
        ),
        atom_texts={"p": "the ledger was updated", "q": "the nightly backup ran"},
    ),
    "expedition": SurfaceVocab(
        agent_names={"a": "Anders", "b": "Bek"},
        world_labels=(
            "the ridge camp", "the river fork", "the glacier shelf", "the moraine",
        ),
        atom_texts={"p": "the supply cache was moved", "q": "the radio check-in happened"},
    ),
}

SCENARIOS: Tuple[str, ...] = tuple(sorted(VOCAB))


# ---------------------------------------------------------------------------
# Formula structures (frozen structural repr; callables built on demand)
# ---------------------------------------------------------------------------

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


#: Frozen announcement candidate pool (shuffled per attempt, seeded).
def _announcement_pool() -> List[Struct]:
    return [
        ("atom", "p"),
        ("atom", "q"),
        ("neg", ("atom", "p")),
        ("neg", ("atom", "q")),
        ("knows", "a", ("atom", "p")),
        ("knows", "b", ("atom", "q")),
        ("neg", ("knows", "a", ("atom", "q"))),
        ("neg", ("knows", "b", ("atom", "p"))),
    ]


def _query_pool(kind: str) -> List[Struct]:
    if kind == "factual":
        return [
            ("atom", "p"),
            ("atom", "q"),
            ("neg", ("atom", "p")),
            ("neg", ("atom", "q")),
        ]
    if kind == "nested":
        return [
            ("knows", "a", ("atom", "p")),
            ("knows", "b", ("atom", "p")),
            ("knows", "a", ("knows", "b", ("atom", "q"))),
            ("knows", "b", ("knows", "a", ("atom", "p"))),
            ("neg", ("knows", "a", ("atom", "q"))),
        ]
    raise InstanceConstructionError(f"unknown query kind {kind!r}")


def _fallback_literals() -> List[Struct]:
    return [
        ("atom", "p"),
        ("neg", ("atom", "p")),
        ("atom", "q"),
        ("neg", ("atom", "q")),
    ]


class _Reject(Exception):
    """Internal: this derived-seed attempt does not satisfy the invariants."""


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def _gen_model(rng: random.Random, n_worlds: int) -> Tuple["_pal.EpistemicModel", str]:
    worlds = tuple(f"w{i + 1}" for i in range(n_worlds))
    valuation = {
        w: frozenset(x for x in ATOMS if rng.random() < 0.5) for w in worlds
    }
    # Non-constant atoms: both p and q must vary across worlds, otherwise
    # factual announcements/queries degenerate.
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
    actual = rng.choice(worlds)
    return model, actual


def _pick_announcements(
    rng: random.Random,
    model0: "_pal.EpistemicModel",
    actual: str,
    count: int,
) -> List[Struct]:
    model = model0
    pool = _announcement_pool()
    rng.shuffle(pool)
    chosen: List[Struct] = []
    for _ in range(count):
        picked = None
        for struct in pool:
            formula = _formula(struct)
            if not formula(model, actual):
                continue  # truthfulness at the actual world
            surviving = {w for w in model.worlds if formula(model, w)}
            if len(surviving) < len(model.worlds):
                picked = struct
                break
        if picked is None:
            # Deterministic fallback: some truthful atom is informative unless
            # every atom is constant on the surviving worlds.
            for struct in _fallback_literals():
                formula = _formula(struct)
                if not formula(model, actual):
                    continue
                surviving = {w for w in model.worlds if formula(model, w)}
                if len(surviving) < len(model.worlds):
                    picked = struct
                    break
        if picked is None:
            # No informative truthful announcement remains: the model cannot
            # be restricted further. The chain ends here (every informative
            # announcement removes at least one world, so a chain can hold at
            # most n_worlds - 1 steps). Realized depth is recorded in the
            # spec; depth-invariance bookkeeping is unaffected.
            break
        chosen.append(picked)
        model = _pal.public_announce_checked(model, actual, _formula(picked))
    return chosen


def build_instance(
    worlds: str,
    depth: str,
    query: str,
    scenario: str,
    seed: int,
) -> "Instance":
    """Deterministically build one E2 instance; raises on unknown axis values.

    Construction uses derived seeds ``f"{seed}:{attempt}"`` until every family
    invariant holds (non-constant valuation, non-trivial partitions, truthful
    informative announcements, and the truncation-flip certificate). Instances
    that cannot discriminate are never emitted.
    """
    if worlds not in WORLDS_BY_AXIS:
        raise ValueError(f"unknown worlds level {worlds!r}; options: {sorted(WORLDS_BY_AXIS)}")
    if depth not in DEPTH_BY_AXIS:
        raise ValueError(f"unknown depth level {depth!r}; options: {sorted(DEPTH_BY_AXIS)}")
    if query not in QUERY_KINDS:
        raise ValueError(f"unknown query kind {query!r}; options: {QUERY_KINDS}")
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; options: {SCENARIOS}")

    n_worlds = WORLDS_BY_AXIS[worlds]
    n_announcements = DEPTH_BY_AXIS[depth]

    for attempt in range(MAX_ATTEMPTS):
        rng = random.Random(f"{seed}:{attempt}")
        try:
            model0, actual = _gen_model(rng, n_worlds)
            announcements = _pick_announcements(rng, model0, actual, n_announcements)
            # Depth contract: the single-step control must have exactly one
            # informative announcement; a chain must realize at least two, so
            # "depth" is an actual factor and not a label.
            if depth == "one" and len(announcements) != 1:
                raise _Reject("single-step control requires exactly one announcement")
            if depth == "chain" and len(announcements) < 2:
                raise _Reject("chain requires at least two realized announcements")
            pool = _query_pool(query)
            query_struct = pool[rng.randrange(len(pool))]
            query_formula = _formula(query_struct)

            # Prefix truths: after 0, 1, ..., n announcements (evaluated at
            # the actual world in each restricted model).
            prefix_truths: List[bool] = [bool(query_formula(model0, actual))]
            model = model0
            for struct in announcements:
                model = _pal.public_announce_checked(model, actual, _formula(struct))
                prefix_truths.append(bool(query_formula(model, actual)))
            final_truth = prefix_truths[-1]

            # Public derivability (fairness invariant): after the full
            # transcript, the registered question must be settled by the
            # public information alone, i.e. its truth is constant across
            # every scenario surviving the announcements. Otherwise no
            # reasoner could classify it from the task text and accuracy
            # would measure luck, not update tracking.
            final_truths = {bool(query_formula(model, w)) for w in model.worlds}
            if len(final_truths) != 1:
                raise _Reject("query is not publicly derivable after the announcements")

            # Truncation-flip certificate (nested queries): the answer must
            # depend on announcement depth, otherwise the instance is not
            # discriminating and is rejected at construction. Factual queries
            # are exempt BY DESIGN: atom truths survive every truthful
            # restriction (the actual world never disappears), so the factual
            # control is depth-invariant; its role is the cross-axis contrast
            # - same announcements, but the registered proposition does not
            # track the update structure.
            if query == "nested" and len(set(prefix_truths)) == 1:
                raise _Reject("query truth is announcement-depth invariant")

            return Instance(
                worlds_axis=worlds,
                depth_axis=depth,
                query_axis=query,
                scenario=scenario,
                seed=seed,
                attempt=attempt,
                vocab=VOCAB[scenario],
                n_worlds=n_worlds,
                valuation={w: sorted(model0.valuation[w]) for w in sorted(model0.worlds)},
                partitions={
                    agent: sorted(sorted(cell) for cell in cells)
                    for agent, cells in sorted(model0.partitions.items())
                },
                actual_world=actual,
                announcements=[tuple(s) for s in announcements],
                query=tuple(query_struct),
                prefix_truths=prefix_truths,
                final_worlds=sorted(model.worlds),
                ground_truth=final_truth,
            )
        except _Reject:
            continue
    raise InstanceConstructionError(
        f"no discriminating construction in {MAX_ATTEMPTS} attempts "
        f"(worlds={worlds} depth={depth} query={query} scenario={scenario} seed={seed})"
    )


# ---------------------------------------------------------------------------
# Instance
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Instance:
    worlds_axis: str
    depth_axis: str
    query_axis: str
    scenario: str
    seed: int
    attempt: int
    vocab: SurfaceVocab
    n_worlds: int
    valuation: Dict[str, List[str]]
    partitions: Dict[str, List[List[str]]]
    actual_world: str
    announcements: List[Tuple]
    query: Tuple
    prefix_truths: List[bool]
    final_worlds: List[str]
    ground_truth: bool

    # -- spec / serialization -------------------------------------------------

    def to_spec(self) -> dict:
        """Judge-side specification with full provenance (JSON-safe)."""
        return {
            "family": "epistemic_announcements",
            "question": "E2",
            "worlds": self.worlds_axis,
            "depth": self.depth_axis,
            "query": self.query_axis,
            "scenario": self.scenario,
            "seed": self.seed,
            "attempt": self.attempt,
            "n_worlds": self.n_worlds,
            "valuation": self.valuation,
            "partitions": self.partitions,
            "actual_world": self.actual_world,
            "announcements": [list(a) for a in self.announcements],
            "query_formula": list(self.query),
            "prefix_truths": self.prefix_truths,
            "final_worlds": self.final_worlds,
            "ground_truth": self.ground_truth,
        }

    # -- public rendering ------------------------------------------------------

    def _semantics_box(self) -> str:
        return (
            "Semantics: scenarios form a finite S5 model. Each agent's "
            "indistinguishability relation is a partition over the scenarios. "
            "A truthful public announcement restricts the model: only the "
            "scenarios where the announced formula holds survive, and each "
            "agent's indistinguishability cells are restricted to the "
            "survivors. Knowledge ('X knows that ...') is evaluated in the "
            "current restricted model: X knows a formula iff it holds in "
            "every scenario X cannot distinguish from the current one. All "
            "announcements below are truthful and are made in the listed "
            "order; each is evaluated in the model produced by the previous "
            "ones. The actual scenario is not revealed; the question is about "
            "the registered formula after all announcements."
        )

    def _model_block(self) -> str:
        lines = ["## The model (common knowledge)"]
        lines.append("Scenarios and the facts that hold in each:")
        for w in sorted(self.valuation):
            label = self.vocab.world_labels[int(w[1:]) - 1]
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

    def _announcements_block(self) -> str:
        lines = ["## Public announcements (in order)"]
        for i, struct in enumerate(self.announcements, start=1):
            lines.append(
                f"{i}. It is publicly announced that {formula_text(tuple(struct), self.vocab)}."
            )
        return "\n".join(lines)

    def public_task_md(self) -> str:
        """Render the agent-facing task. Contains NO ground-truth values.

        Public by construction: the model (worlds, valuation, partitions),
        the announcement sequence, and the registered query. Withheld: the
        actual world, all prefix/final truth values, the ground truth.
        """
        parts: List[str] = []
        parts.append(
            f"# Sequential Public Announcement Task (epistemic_announcements, "
            f"depth={self.depth_axis}, query={self.query_axis})"
        )
        parts.append(
            "A registered proposition must be classified exactly after a "
            "sequence of truthful public announcements updates the model. "
            "Your answer is judged against the exact truth value in the "
            "final restricted model."
        )
        parts.append("## Semantics")
        parts.append(self._semantics_box())
        parts.append(self._model_block())
        parts.append(self._announcements_block())
        parts.append("## Question")
        parts.append(
            "After all announcements above have been made (in order, each "
            "restricting the model), is it the case that "
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
        """Grade an answer dict; returns checks, metrics, failure_mode, notes.

        Exact classification: full credit only on the exact truth value.
        There is deliberately no partial credit — a half-right classification
        of a registered proposition is not evidence of the update.
        """
        parsed, errors = _parse_answer(answer)
        checks = {"answer_format_valid": not errors, "truth_correct": False}
        metrics: Dict[str, object] = {
            "depth": self.depth_axis,
            "query": self.query_axis,
            "n_announcements": len(self.announcements),
            "ground_truth": self.ground_truth,
            "prefix_truths": self.prefix_truths,
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
            f"(depth={self.depth_axis}, query={self.query_axis}, "
            f"announcements={len(self.announcements)})"
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
            "Restricted the S5 model by each truthful announcement in order "
            "and evaluated the registered formula at the final model."
        ),
    }


def _assert_clean(text: str, where: str) -> None:
    if "%%" in text:
        raise InstanceConstructionError(f"rendered text in {where} contains '%%'")
