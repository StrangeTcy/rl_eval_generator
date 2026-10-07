"""Visible schema-only checks for the literal answer assignment.

These checks intentionally do not contain the hidden expected answer. Run with:

    python visible_tests.py
"""

from __future__ import annotations

import ast
import json
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_task() -> dict:
    value = json.loads((ROOT / "task.json").read_text(encoding="utf-8"))
    if type(value) is not dict or type(value.get("variant")) is not str:
        raise ValueError("task.json has an invalid top-level schema")
    return value


def _load_answer() -> dict:
    path = ROOT / "answer.py"
    text = path.read_text(encoding="utf-8")
    if len(text.encode("utf-8")) > 20_000:
        raise ValueError("answer.py is too large")
    tree = ast.parse(text, filename="answer.py")
    if sum(1 for _ in ast.walk(tree)) > 500:
        raise ValueError("answer.py has too many syntax nodes")
    assignments = []
    for statement in tree.body:
        if isinstance(statement, ast.Expr):
            if not (
                isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str)
            ):
                raise ValueError("only a docstring and ANSWER assignment are allowed")
        elif isinstance(statement, ast.Assign):
            assignments.append(statement)
        else:
            raise ValueError("answer.py must contain only a docstring and ANSWER assignment")
    if len(assignments) != 1 or len(assignments[0].targets) != 1:
        raise ValueError("answer.py must contain exactly one ANSWER assignment")
    target = assignments[0].targets[0]
    if not isinstance(target, ast.Name) or target.id != "ANSWER":
        raise ValueError("the only assignment target must be ANSWER")
    answer = ast.literal_eval(assignments[0].value)
    if type(answer) is not dict:
        raise ValueError("ANSWER must be a dictionary literal")
    return answer


def _canonical_fraction(value: object) -> bool:
    if type(value) is not str or "/" not in value:
        return False
    numerator, denominator, *extra = value.split("/")
    if extra or not numerator or not denominator:
        return False
    try:
        exact = Fraction(int(numerator), int(denominator))
    except (ValueError, ZeroDivisionError):
        return False
    return f"{exact.numerator}/{exact.denominator}" == value


def _world_list(value: object, world_ids: set[str]) -> bool:
    return (
        type(value) is list
        and all(type(world) is str for world in value)
        and len(value) == len(set(value))
        and set(value) <= world_ids
    )


def test_answer_shape() -> None:
    task = _load_task()
    answer = _load_answer()
    variant = task["variant"]
    posterior_variants = {
        "event_sparse",
        "event_strict",
        "policy_sparse",
        "policy_strict",
        "deterministic_silence",
        "silence_empty_protocol",
    }
    truth_variants = {
        "relational_modal",
        "s5_knowledge",
        "common_knowledge",
        "common_knowledge_empty_group",
    }
    if variant in posterior_variants:
        assert set(answer) == {"posterior"}
        assert type(answer["posterior"]) is dict
        assert set(answer["posterior"]) == set(task["prior"])
        assert all(_canonical_fraction(p) for p in answer["posterior"].values())
    elif variant in truth_variants:
        assert set(answer) == {"truth"}
        assert type(answer["truth"]) is bool
    elif variant == "announcement_unpointed":
        assert set(answer) == {"worlds"}
        assert _world_list(answer["worlds"], {item["id"] for item in task["worlds"]})
    elif variant == "announcement_checked":
        assert set(answer) == {"accepted", "worlds"}
        assert type(answer["accepted"]) is bool
        world_ids = {item["id"] for item in task["worlds"]}
        if answer["accepted"]:
            assert _world_list(answer["worlds"], world_ids)
            assert task["actual_world"] in answer["worlds"]
        else:
            assert answer["worlds"] is None
    elif variant in {"information_pool", "information_empty_group"}:
        assert set(answer) == {"individual", "pooled"}
        world_ids = {item["id"] for item in task["worlds"]}
        assert _world_list(answer["individual"], world_ids)
        assert _world_list(answer["pooled"], world_ids)
    elif variant == "pure_bne":
        assert set(answer) == {"equilibria"}
        assert type(answer["equilibria"]) is list
        agents = task["agents"]
        seen_profiles = set()
        for equilibrium in answer["equilibria"]:
            assert type(equilibrium) is dict
            assert set(equilibrium) == set(agents)
            signature = []
            for agent in agents:
                strategy = equilibrium[agent]
                assert type(strategy) is dict
                assert set(strategy) == set(task["types"][agent])
                actions_for_types = tuple(
                    strategy[player_type] for player_type in task["types"][agent]
                )
                assert all(
                    type(action) is str and action in task["actions"][agent]
                    for action in actions_for_types
                )
                signature.append((agent, actions_for_types))
            profile = tuple(signature)
            assert profile not in seen_profiles
            seen_profiles.add(profile)
    else:
        raise AssertionError(f"unsupported task variant {variant!r}")


def main() -> None:
    test_answer_shape()
    print("Visible answer-format checks passed")


if __name__ == "__main__":
    main()
