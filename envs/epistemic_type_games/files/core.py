"""Symbolic core for the ``epistemic_type_games`` family (E6).

Model-independent, deterministic, standard library only (exact Fractions).

Source grounding (Mission 02 portfolio, question E6): "In finite
common-prior games with fixed payoffs and different information partitions,
do models' predicted action profiles track the independently enumerated
Bayesian-Nash equilibrium when the games are restricted to instances with a
unique equilibrium?" Discriminator: predicted action profile compared with
the unique, independently enumerated equilibrium under each type partition.
Feasibility rule honored: types, common prior, information partitions,
solution concept (pure-strategy Bayesian Nash equilibrium), and the
uniqueness/tie rules are all specified operationally below - the oracle is a
brute-force enumeration, not an uncapped textbook appeal.

Design
------
Two players, finite type spaces, common prior with FULL support (every type
profile strictly positive, exact rationals), so interim beliefs are always
defined. Each player observes their own type (the information partition is
the type partition). Two actions per player. Payoffs are rational and given
per (type profile, action pair).

Solution concept: a pure strategy profile (type -> action for each player)
is a Bayesian-Nash equilibrium iff, for every player and every type, the
prescribed action maximizes interim expected payoff against the opponent's
strategy under the conditional common prior. Ties are allowed in the
best-response test (>=), matching the standard definition.

Construction certificates (rejection at construction)
------------------------------------------------------
* UNIQUENESS: the enumerated pure-BNE set must have exactly one member -
  the portfolio restricts E6 to unique-equilibrium instances.
* PARTITION SENSITIVITY: at least one player's equilibrium strategy must
  vary across their types; otherwise the answer does not require
  type-contingent reasoning and the instance cannot discriminate
  partition-sensitive choice from payoff-only or surface choice.
"""
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, List, Tuple

PLAYERS: Tuple[str, ...] = ("player_a", "player_b")
ACTIONS: Tuple[str, ...] = ("X", "Y")

TYPES_BY_AXIS: Dict[str, Tuple[int, int]] = {"small": (2, 2), "large": (3, 2)}
PAYOFF_BOUND_BY_AXIS: Dict[str, int] = {"mild": 1, "sharp": 3}

#: Rejection bound; measured per-attempt certificate pass rates for the
#: smallest axis level stay well above the implied floor (see tests).
MAX_ATTEMPTS = 256


class InstanceConstructionError(RuntimeError):
    """Raised when no construction satisfies the family invariants."""


@dataclass(frozen=True)
class SurfaceVocab:
    player_names: Dict[str, str]
    action_texts: Dict[str, str]
    type_texts_a: Tuple[str, ...]
    type_texts_b: Tuple[str, ...]


VOCAB: Dict[str, SurfaceVocab] = {
    "office": SurfaceVocab(
        player_names={"player_a": "Alice", "player_b": "Bob"},
        action_texts={"X": "publish the report", "Y": "withhold the report"},
        type_texts_a=("demand is strong", "demand is weak", "demand is uncertain"),
        type_texts_b=("the audit is scheduled", "the audit was cancelled"),
    ),
    "expedition": SurfaceVocab(
        player_names={"player_a": "Anders", "player_b": "Bek"},
        action_texts={"X": "signal the camp", "Y": "wait one more day"},
        type_texts_a=("the weather window is open", "a storm is inbound",
                      "the forecast is inconclusive"),
        type_texts_b=("the rope team is fresh", "the rope team is exhausted"),
    ),
}

SCENARIOS: Tuple[str, ...] = tuple(sorted(VOCAB))


class _Reject(Exception):
    """Internal: this derived-seed attempt does not satisfy the invariants."""


def _type_names(n: int) -> List[str]:
    return [f"t{i + 1}" for i in range(n)]


# ---------------------------------------------------------------------------
# Oracle: exact brute-force pure BNE enumeration (independent solution check)
# ---------------------------------------------------------------------------

def interim_beliefs(prior: Dict[Tuple[str, str], Fraction], types_a: List[str],
                    types_b: List[str]) -> Tuple[Dict[str, Dict[str, Fraction]],
                                                  Dict[str, Dict[str, Fraction]]]:
    """Conditional common-prior beliefs for each realized type.

    Full support is required: every type must have positive marginal, which
    the generator enforces before calling this.
    """
    beliefs_a: Dict[str, Dict[str, Fraction]] = {}
    beliefs_b: Dict[str, Dict[str, Fraction]] = {}
    for ta in types_a:
        marginal = sum((prior[(ta, tb)] for tb in types_b), Fraction(0))
        if marginal <= 0:
            raise ValueError(f"zero marginal for type {ta}")
        beliefs_a[ta] = {tb: prior[(ta, tb)] / marginal for tb in types_b}
    for tb in types_b:
        marginal = sum((prior[(ta, tb)] for ta in types_a), Fraction(0))
        if marginal <= 0:
            raise ValueError(f"zero marginal for type {tb}")
        beliefs_b[tb] = {ta: prior[(ta, tb)] / marginal for ta in types_a}
    return beliefs_a, beliefs_b


def expected_payoff(player: str, own_type: str, action: str,
                    opponent_strategy: Dict[str, str],
                    beliefs: Dict[str, Fraction],
                    payoffs: Dict[Tuple[str, str], Dict[Tuple[str, str], Fraction]]
                    ) -> Fraction:
    """Interim expected payoff of `action` at `own_type` against a fixed
    opponent strategy, under conditional beliefs. Exact."""
    total = Fraction(0)
    for opp_type, prob in beliefs.items():
        if prob == 0:
            continue
        opp_action = opponent_strategy[opp_type]
        if player == "player_a":
            key = (own_type, opp_type)
            pair = (action, opp_action)
            slot = 0
        else:
            key = (opp_type, own_type)
            pair = (opp_action, action)
            slot = 1
        total += prob * payoffs[key][pair][slot]
    return total


def enumerate_pure_bne(
    types_a: List[str],
    types_b: List[str],
    prior: Dict[Tuple[str, str], Fraction],
    payoffs: Dict[Tuple[str, str], Dict[Tuple[str, str], Fraction]],
) -> List[Dict[str, Dict[str, str]]]:
    """Exhaustively enumerate all pure-strategy profiles and return exactly
    the Bayesian-Nash equilibria among them. Deterministic order."""
    beliefs_a, beliefs_b = interim_beliefs(prior, types_a, types_b)
    strategies_a = [dict(zip(types_a, combo))
                    for combo in itertools.product(ACTIONS, repeat=len(types_a))]
    strategies_b = [dict(zip(types_b, combo))
                    for combo in itertools.product(ACTIONS, repeat=len(types_b))]
    equilibria: List[Dict[str, Dict[str, str]]] = []
    for sa in strategies_a:
        for sb in strategies_b:
            ok = True
            for ta in types_a:
                current = expected_payoff("player_a", ta, sa[ta], sb, beliefs_a[ta], payoffs)
                for alt in ACTIONS:
                    if alt == sa[ta]:
                        continue
                    if expected_payoff("player_a", ta, alt, sb, beliefs_a[ta], payoffs) > current:
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                for tb in types_b:
                    current = expected_payoff("player_b", tb, sb[tb], sa, beliefs_b[tb], payoffs)
                    for alt in ACTIONS:
                        if alt == sb[tb]:
                            continue
                        if expected_payoff("player_b", tb, alt, sa, beliefs_b[tb], payoffs) > current:
                            ok = False
                            break
                    if not ok:
                        break
            if ok:
                equilibria.append({"player_a": dict(sa), "player_b": dict(sb)})
    return equilibria


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def _gen_prior(rng: random.Random, types_a: List[str],
               types_b: List[str]) -> Dict[Tuple[str, str], Fraction]:
    weights = {(ta, tb): rng.randint(1, 4) for ta in types_a for tb in types_b}
    total = sum(weights.values())
    return {key: Fraction(w, total) for key, w in weights.items()}


def _gen_payoffs(rng: random.Random, types_a: List[str], types_b: List[str],
                 bound: int) -> Dict[Tuple[str, str], Dict[Tuple[str, str], Tuple[Fraction, Fraction]]]:
    """Random (u_a, u_b) payoff matrices per type profile, exact rationals."""
    full: Dict[Tuple[str, str], Dict[Tuple[str, str], Tuple[Fraction, Fraction]]] = {}
    for ta in types_a:
        for tb in types_b:
            full[(ta, tb)] = {
                (aa, ab): (Fraction(rng.randint(-bound, bound)),
                           Fraction(rng.randint(-bound, bound)))
                for aa in ACTIONS for ab in ACTIONS
            }
    return full


def build_instance(
    types: str,
    payoffs: str,
    scenario: str,
    seed: int,
) -> "Instance":
    """Deterministically build one E6 instance; raises on unknown axis values.

    Construction uses derived seeds until BOTH certificates hold: a unique
    pure Bayesian-Nash equilibrium, and an equilibrium strategy that varies
    across types for at least one player (partition sensitivity).
    """
    if types not in TYPES_BY_AXIS:
        raise ValueError(f"unknown types level {types!r}; options: {sorted(TYPES_BY_AXIS)}")
    if payoffs not in PAYOFF_BOUND_BY_AXIS:
        raise ValueError(f"unknown payoffs level {payoffs!r}; options: {sorted(PAYOFF_BOUND_BY_AXIS)}")
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; options: {SCENARIOS}")

    n_a, n_b = TYPES_BY_AXIS[types]
    bound = PAYOFF_BOUND_BY_AXIS[payoffs]

    for attempt in range(MAX_ATTEMPTS):
        rng = random.Random(f"{seed}:{attempt}")
        types_a = _type_names(n_a)
        types_b = _type_names(n_b)
        prior = _gen_prior(rng, types_a, types_b)
        payoff_tables = _gen_payoffs(rng, types_a, types_b, bound)
        equilibria = enumerate_pure_bne(types_a, types_b, prior, payoff_tables)
        if len(equilibria) != 1:
            continue  # uniqueness certificate
        equilibrium = equilibria[0]
        varies = (
            len(set(equilibrium["player_a"].values())) > 1
            or len(set(equilibrium["player_b"].values())) > 1
        )
        if not varies:
            continue  # partition-sensitivity certificate
        return Instance(
            types_axis=types,
            payoffs_axis=payoffs,
            scenario=scenario,
            seed=seed,
            attempt=attempt,
            vocab=VOCAB[scenario],
            types_a=types_a,
            types_b=types_b,
            prior={f"{ta},{tb}": str(prior[(ta, tb)])
                   for ta in types_a for tb in types_b},
            payoffs={
                f"{ta},{tb}": {
                    f"{aa},{ab}": [str(u) for u in payoff_tables[(ta, tb)][(aa, ab)]]
                    for aa in ACTIONS for ab in ACTIONS
                }
                for ta in types_a for tb in types_b
            },
            equilibrium={player: dict(strategy)
                         for player, strategy in equilibrium.items()},
        )
    raise InstanceConstructionError(
        f"no certificate-satisfying construction in {MAX_ATTEMPTS} attempts "
        f"(types={types} payoffs={payoffs} scenario={scenario} seed={seed})"
    )


@dataclass(frozen=True)
class Instance:
    types_axis: str
    payoffs_axis: str
    scenario: str
    seed: int
    attempt: int
    vocab: SurfaceVocab
    types_a: List[str]
    types_b: List[str]
    prior: Dict[str, str]
    payoffs: Dict[str, Dict[str, List[str]]]
    equilibrium: Dict[str, Dict[str, str]]

    # -- reconstruction helpers (used by the judge) ---------------------------

    def reconstructed_prior(self) -> Dict[Tuple[str, str], Fraction]:
        prior: Dict[Tuple[str, str], Fraction] = {}
        for key, value in self.prior.items():
            ta, tb = key.split(",")
            prior[(ta, tb)] = Fraction(value)
        return prior

    def reconstructed_payoffs(self) -> Dict[Tuple[str, str], Dict[Tuple[str, str], Tuple[Fraction, Fraction]]]:
        tables: Dict[Tuple[str, str], Dict[Tuple[str, str], Tuple[Fraction, Fraction]]] = {}
        for key, matrix in self.payoffs.items():
            ta, tb = key.split(",")
            tables[(ta, tb)] = {}
            for pair, utils in matrix.items():
                aa, ab = pair.split(",")
                tables[(ta, tb)][(aa, ab)] = (Fraction(utils[0]), Fraction(utils[1]))
        return tables

    def to_spec(self) -> dict:
        """Judge-side specification with full provenance (JSON-safe)."""
        return {
            "family": "epistemic_type_games",
            "question": "E6",
            "types": self.types_axis,
            "payoffs": self.payoffs_axis,
            "scenario": self.scenario,
            "seed": self.seed,
            "attempt": self.attempt,
            "types_a": list(self.types_a),
            "types_b": list(self.types_b),
            "prior": dict(self.prior),
            "payoff_matrices": {k: {p: list(u) for p, u in m.items()}
                                for k, m in self.payoffs.items()},
            "equilibrium": {player: dict(strategy)
                            for player, strategy in self.equilibrium.items()},
        }

    # -- public rendering ------------------------------------------------------

    def _type_text(self, player: str, type_name: str) -> str:
        vocab = self.vocab
        texts = vocab.type_texts_a if player == "player_a" else vocab.type_texts_b
        index = int(type_name[1:]) - 1
        return texts[index]

    def _semantics_box(self) -> str:
        a, b = self.vocab.player_names["player_a"], self.vocab.player_names["player_b"]
        return (
            "Semantics: a two-player Bayesian game. Nature draws a type "
            "profile from the common prior (full support, exact rationals); "
            "each player privately observes their own type and nothing else. "
            "A pure strategy maps each of a player's types to an action. A "
            "pure Bayesian-Nash equilibrium is a strategy profile in which, "
            "for every player and every type of that player, the prescribed "
            "action maximizes interim expected payoff against the opponent's "
            "strategy under the conditional common prior; ties in the "
            "best-response comparison are allowed. This instance is "
            "registered to have EXACTLY ONE pure Bayesian-Nash equilibrium; "
            f"your task is to identify it. {a} moves simultaneously with "
            f"{b} - there is no sequential play."
        )

    def _game_block(self) -> str:
        a = self.vocab.player_names["player_a"]
        b = self.vocab.player_names["player_b"]
        lines = ["## The game (common knowledge)"]
        lines.append(f"- {a}'s possible types:")
        for ta in self.types_a:
            lines.append(f"  - `{ta}`: {self._type_text('player_a', ta)}.")
        lines.append(f"- {b}'s possible types:")
        for tb in self.types_b:
            lines.append(f"  - `{tb}`: {self._type_text('player_b', tb)}.")
        lines.append("- Actions: each player chooses `X` "
                     f"({self.vocab.action_texts['X']}) or `Y` "
                     f"({self.vocab.action_texts['Y']}).")
        lines.append("- Common prior over type profiles:")
        for key in sorted(self.prior):
            ta, tb = key.split(",")
            lines.append(f"  - P(`{ta}`, `{tb}`) = {self.prior[key]}")
        lines.append(
            f"- Payoffs as (utility for {a}, utility for {b}), by type "
            "profile and action pair:"
        )
        for key in sorted(self.payoffs):
            ta, tb = key.split(",")
            lines.append(f"  - types (`{ta}`, `{tb}`):")
            for pair in sorted(self.payoffs[key]):
                aa, ab = pair.split(",")
                ua, ub = self.payoffs[key][pair]
                lines.append(f"    - (`{aa}`, `{ab}`): ({ua}, {ub})")
        return "\n".join(lines)

    def public_task_md(self) -> str:
        """Render the agent-facing task. Contains NO ground-truth values."""
        parts: List[str] = []
        parts.append(
            f"# Bayesian Game Task (epistemic_type_games, types={self.types_axis})"
        )
        parts.append(
            "Report the unique pure Bayesian-Nash equilibrium of the "
            "registered game: one action for every type of every player. "
            "Your answer is judged against the independently enumerated "
            "equilibrium."
        )
        parts.append("## Semantics")
        parts.append(self._semantics_box())
        parts.append(self._game_block())
        parts.append("## Question")
        parts.append(
            "What is the unique pure Bayesian-Nash equilibrium? Give the "
            "action (`X` or `Y`) prescribed for each type of each player."
        )
        parts.append("## Answer protocol")
        parts.append(
            "Fill in the `ANSWER` dictionary in `answer.py` (the only file "
            "you should edit): `player_a` and `player_b` each map type ids "
            "like `t1` to `X` or `Y`; `justification` a short explanation "
            "(max 600 characters). Then run the local format check:\n\n"
            "```\npython -m pytest visible_tests.py -q\n```\n\n"
            "When satisfied, submit (`python /tools/submit.py`)."
        )
        text = "\n\n".join(parts) + "\n"
        _assert_clean(text, "task.md")
        return text

    # -- grading ---------------------------------------------------------------

    def grade(self, answer: object, pass_threshold: float) -> dict:
        """Exact classification: full credit only on the exact equilibrium."""
        parsed, errors = _parse_answer(answer, self.types_a, self.types_b)
        checks = {"answer_format_valid": not errors, "equilibrium_correct": False}
        metrics: Dict[str, object] = {
            "types": self.types_axis,
            "payoffs": self.payoffs_axis,
        }
        if errors:
            metrics["strategy_reported"] = None
            metrics["score"] = 0.0
            metrics["strict_correct"] = False
            return {
                "checks": checks,
                "metrics": metrics,
                "failure_mode": "answer_format_invalid",
                "notes": errors,
            }
        correct = (
            parsed["player_a"] == self.equilibrium["player_a"]
            and parsed["player_b"] == self.equilibrium["player_b"]
        )
        checks["equilibrium_correct"] = correct
        score = 1.0 if correct else 0.0
        metrics.update(
            {
                "strategy_reported": {
                    "player_a": parsed["player_a"],
                    "player_b": parsed["player_b"],
                },
                "score": score,
                "strict_correct": correct,
            }
        )
        return {
            "checks": checks,
            "metrics": metrics,
            "failure_mode": "pass" if correct else "wrong_equilibrium",
            "notes": [
                f"reported a={parsed['player_a']} b={parsed['player_b']} vs "
                f"equilibrium a={self.equilibrium['player_a']} "
                f"b={self.equilibrium['player_b']}"
            ],
        }


def _parse_answer(answer: object, types_a: List[str],
                  types_b: List[str]) -> Tuple[dict, List[str]]:
    errors: List[str] = []
    normalized: dict = {}
    if not isinstance(answer, dict):
        return normalized, [f"ANSWER must be a JSON object, got {type(answer).__name__}"]
    required = ("player_a", "player_b", "justification")
    for key in required:
        if key not in answer:
            errors.append(f"missing key {key!r}")
    for key in answer:
        if key not in required:
            errors.append(f"unexpected key {key!r}")
    for player, type_space in (("player_a", types_a), ("player_b", types_b)):
        if player not in answer:
            continue
        strategy = answer[player]
        if not isinstance(strategy, dict):
            errors.append(f"{player} must be a dict from types to actions")
            continue
        if sorted(strategy) != sorted(type_space):
            errors.append(
                f"{player} strategy must cover exactly the types {type_space}"
            )
            continue
        bad = [t for t, action in strategy.items() if action not in ACTIONS]
        if bad:
            errors.append(f"{player} assigns invalid actions at types {bad}")
            continue
        normalized[player] = {t: strategy[t] for t in type_space}
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
        "player_a": dict(instance.equilibrium["player_a"]),
        "player_b": dict(instance.equilibrium["player_b"]),
        "justification": (
            "Enumerated all pure strategy profiles and checked the interim "
            "best-response condition under the conditional common prior."
        ),
    }


def _assert_clean(text: str, where: str) -> None:
    if "%%" in text:
        raise InstanceConstructionError(f"rendered text in {where} contains '%%'")
