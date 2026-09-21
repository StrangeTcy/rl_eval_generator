"""Visible (non-authoritative) format checks for the answer file.

The judge grades far more than this (calibration against the true posterior,
verdict band, direction, internal consistency, and a structured failure-mode
diagnosis). This file only validates the answer FORMAT so you can iterate
locally:

    python -m pytest visible_tests.py -q
"""
import ast
import json
from pathlib import Path

REQUIRED_KEYS = {"posterior_world1", "verdict", "most_supported", "justification"}
VERDICTS = {"indistinguishable", "weakly_distinguishable", "distinguishable"}
SUPPORT = {"world1", "world2", "neither"}

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
    assert p is None or (
        isinstance(p, (int, float))
        and not isinstance(p, bool)
        and 0.0 <= float(p) <= 1.0
    ), f"posterior_world1 must be None or a number in [0, 1], got {p!r}"
    assert a["verdict"] is None or a["verdict"] in VERDICTS, f"bad verdict {a['verdict']!r}"
    assert a["most_supported"] is None or a["most_supported"] in SUPPORT, (
        f"bad most_supported {a['most_supported']!r}"
    )
    j = a["justification"]
    assert j is None or (isinstance(j, str) and len(j) <= 600), (
        f"justification must be None or a string of at most 600 chars (got {type(j).__name__})"
    )


def test_answer_consistency():
    a = _load_answer_literal()
    p = a["posterior_world1"]
    s = a["most_supported"]
    if p is None or s is None:
        return
    if not isinstance(p, (int, float)) or isinstance(p, bool):
        return
    if s not in SUPPORT:
        return
    # internal consistency: posterior vs support
    if s == "world1":
        assert float(p) > 0.5, f"most_supported world1 requires posterior >0.5, got {p}"
    elif s == "world2":
        assert float(p) < 0.5, f"most_supported world2 requires posterior <0.5, got {p}"
    else:
        assert abs(float(p) - 0.5) <= 1e-9, f"most_supported neither requires posterior ==0.5, got {p}"

    # JSON-serializable and size-bounded
    data = json.dumps(a).encode("utf-8")
    assert len(data) <= 5000, f"ANSWER JSON too large: {len(data)} bytes"

