"""Direct-answer trajectory benchmark primitives.

This module intentionally treats the relay as a controlled behavioral probe.  It
never labels a horizon as a model-side depth measurement.
"""
from __future__ import annotations

import re
from typing import Any

from shared.trajectory_semantics.certify import Certification, certify_system_pair
from shared.trajectory_semantics.generate_case import (
    QUERY_ALIASES,
    TrajectoryCase,
)
from shared.trajectory_semantics.generate_case import (
    make_case as _make_case,
)

SYSTEM_ANSWER_ONLY = """You are answering a controlled benchmark question about a small transition system.
Return only the final answer, with no reasoning, Markdown, or code fence.
Use the requested answer format exactly.
"""

SYSTEM_SCRATCHPAD = """You are answering a controlled benchmark question about a small transition system.
You may use a scratchpad in your response. Put the final answer on the last line as:
FINAL: <answer>
"""


def certification(seed: int = 0) -> Certification:
    return certify_system_pair(seed)


def make_case(**kwargs: Any) -> TrajectoryCase:
    return _make_case(**kwargs)


def make_messages(case: TrajectoryCase, protocol: str) -> list[dict[str, str]]:
    if protocol not in {"answer_only", "external_scratchpad"}:
        raise ValueError(f"unknown resource protocol: {protocol}")
    system = SYSTEM_SCRATCHPAD if protocol == "external_scratchpad" else SYSTEM_ANSWER_ONLY
    user = (
        "Specification:\n\n"
        f"{case.spec_text}\n\n"
        "Question:\n"
        f"{case.question}\n\n"
        "Answer format:\n"
        f"{case.answer_format}\n"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def normalize_answer(raw: str) -> str:
    value = raw.strip()
    final_match = re.search(r"(?:^|\n)FINAL\s*:\s*(.+)$", value, flags=re.IGNORECASE | re.DOTALL)
    if final_match:
        value = final_match.group(1).strip()
    value = re.sub(r"^```[A-Za-z0-9_-]*\s*", "", value).strip()
    value = re.sub(r"\s*```$", "", value).strip()
    if "\n" in value:
        value = value.splitlines()[-1].strip()
    value = value.strip(" .`\"'")
    return re.sub(r"\s+", "", value).lower()


def answer_format_valid(case: TrajectoryCase, normalized: str) -> bool:
    if case.query_type == "parse_only":
        return normalized in {
            "same",
            "flip",
            normalize_answer(case.expected_answer),
            normalize_answer(case.initial_state["payload"]),
            "0",
            "1",
        }
    if case.query_type in {"template_at_T", "complete_return"}:
        return normalized in {"yes", "no"}
    return bool(re.fullmatch(r"[^()]+\([^()]+\)", normalized))


def score_answer(case: TrajectoryCase, raw: str) -> dict[str, Any]:
    parsed = normalize_answer(raw)
    expected = normalize_answer(case.expected_answer)
    correct = parsed == expected
    stale = case.stale_witness_prediction
    return {
        "format_valid": answer_format_valid(case, parsed),
        "correct": correct,
        "parsed_answer": parsed,
        "expected_normalized": expected,
        "matched_stale_witness_prediction": (
            stale is not None and parsed == normalize_answer(stale) and not correct
        ),
    }


def public_case(case: TrajectoryCase) -> dict[str, object]:
    """The case fields safe to send to a model; expected answers stay private."""

    value = case.as_dict(include_answer=False)
    for key in ("stale_witness_prediction", "certification"):
        value.pop(key, None)
    return value


__all__ = [
    "QUERY_ALIASES",
    "SYSTEM_ANSWER_ONLY",
    "SYSTEM_SCRATCHPAD",
    "TrajectoryCase",
    "answer_format_valid",
    "certification",
    "make_case",
    "make_messages",
    "normalize_answer",
    "public_case",
    "score_answer",
]
