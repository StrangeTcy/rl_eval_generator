"""Visible (non-authoritative) format checks for the answer file.

The judge grades the exact pure Bayesian-Nash equilibrium against the
independently enumerated ground truth plus a structured failure-mode
diagnosis. This file only validates the answer FORMAT so you can iterate
locally:

    python -m pytest visible_tests.py -q
"""
import ast
import json
from pathlib import Path

REQUIRED_KEYS = {"player_a", "player_b", "justification"}
ACTIONS = ("X", "Y")

ANSWER_PATH = Path(__file__).parent / "answer.py"


def _load_answer_literal() -> dict:
    text = ANSWER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(text, filename="answer.py")
    assigns = [n for n in tree.body if isinstance(n, ast.Assign)]
    assert len(assigns) == 1, "answer.py must contain exactly one ANSWER assignment"
    return ast.literal_eval(assigns[0].value)


def test_answer_present():
    ans = _load_answer_literal()
    assert isinstance(ans, dict), "ANSWER must be a dict"


def test_answer_keys():
    ans = _load_answer_literal()
    assert set(ans) == REQUIRED_KEYS, f"keys must be exactly {sorted(REQUIRED_KEYS)}"


def test_strategies_well_formed():
    a = _load_answer_literal()
    for player in ("player_a", "player_b"):
        strategy = a[player]
        assert strategy is None or isinstance(strategy, dict), (
            f"{player} must be None or a dict from type ids to actions"
        )
        if isinstance(strategy, dict):
            assert strategy, f"{player} strategy must not be empty"
            for type_id, action in strategy.items():
                assert isinstance(type_id, str) and type_id.startswith("t"), (
                    f"{player}: type ids look like 't1', got {type_id!r}"
                )
                assert action in ACTIONS, (
                    f"{player}: actions must be 'X' or 'Y', got {action!r}"
                )
    j = a["justification"]
    assert j is None or (isinstance(j, str) and 0 < len(j) <= 600), (
        "justification must be None or a non-empty string of at most 600 chars"
    )
    data = json.dumps(a).encode("utf-8")
    assert len(data) <= 5000, f"ANSWER JSON too large: {len(data)} bytes"
