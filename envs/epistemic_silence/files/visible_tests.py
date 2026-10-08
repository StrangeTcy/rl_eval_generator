"""Visible (non-authoritative) format checks for the answer file.

The judge grades exact posterior classification against the accepted
silence/supplied-policy substrate plus a structured failure-mode diagnosis.
This file only validates the answer FORMAT so you can iterate locally:

    python -m pytest visible_tests.py -q
"""
import ast
import json
from fractions import Fraction
from pathlib import Path

REQUIRED_KEYS = {"posterior_world1", "direction", "justification"}

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


def test_answer_types():
    a = _load_answer_literal()
    p = a["posterior_world1"]
    assert p is None or isinstance(p, str), (
        f"posterior_world1 must be None or a string rational, got {p!r}"
    )
    if isinstance(p, str) and p:
        value = Fraction(p)
        assert Fraction(0) <= value <= Fraction(1), "posterior_world1 must lie in [0, 1]"
        assert value.denominator <= 10000, "posterior_world1 denominator too large"
    d = a["direction"]
    assert d is None or d in ("increased", "decreased", "unchanged"), (
        "direction must be None or increased/decreased/unchanged"
    )
    j = a["justification"]
    assert j is None or (isinstance(j, str) and 0 < len(j) <= 600), (
        "justification must be None or a non-empty string of at most 600 chars"
    )

    # JSON-serializable and size-bounded
    data = json.dumps(a).encode("utf-8")
    assert len(data) <= 5000, f"ANSWER JSON too large: {len(data)} bytes"
