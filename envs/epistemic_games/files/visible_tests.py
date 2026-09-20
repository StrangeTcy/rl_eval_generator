"""Visible (non-authoritative) format checks for the answer file.

The judge grades far more than this (calibration against the true posterior,
verdict band, direction, and a structured failure-mode diagnosis). This file
only validates the answer FORMAT so you can iterate locally:

    python -m pytest visible_tests.py -q
"""
import answer

REQUIRED_KEYS = {"posterior_world1", "verdict", "most_supported", "justification"}
VERDICTS = {"indistinguishable", "weakly_distinguishable", "distinguishable"}
SUPPORT = {"world1", "world2", "neither"}


def test_answer_present():
    assert isinstance(getattr(answer, "ANSWER", None), dict), "ANSWER must be a dict"


def test_answer_keys():
    assert set(answer.ANSWER) == REQUIRED_KEYS, f"keys must be exactly {sorted(REQUIRED_KEYS)}"


def test_answer_types():
    a = answer.ANSWER
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
