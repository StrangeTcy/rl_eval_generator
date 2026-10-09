"""Paired-arm construction primitive for S-line experiments (offline).

Source grounding (epistemic-compiler corpus, Mission 02):

* ``code snippets critique.md``, shared primitives #4: "Paired-arm /
  deterministic-seed construction (Arm, arm_seed): reusable across S1, S4,
  and T1 - all three are 'same instance, varied one thing' designs."
* S1 section replacement code: ``Arm(name, prompt_supplement)`` with "" for
  the no-advice arm; ``build_paired_arms`` returning card / generic_advice
  / none arms; ``arm_seed`` deterministic so re-running a campaign
  reproduces identical samples per arm without per-arm seed files.
* S-line assessment (epistemic_program/S_LINE_ASSESSMENT.md, user decision
  2026-10-08 option c): build this primitive offline, explicitly UNUSED
  until model-call authorization exists.

Contract rules:

* This module is data construction only: no model calls, no network, no
  scoring, no statistics. It must stay importable and testable offline.
* Arms share EVERYTHING except ``prompt_supplement``: the instance identity
  is the pairing key, and any arm-specific variation beyond the supplement
  would break the matched design.
* ``arm_seed`` is a pure function of ``(instance_id, arm_name)``; it never
  consults clocks, counters, or external state.
* UNUSED-BY-DESIGN guard: no environment, judge, renderer, or tool may
  import this module while model calls are unauthorized; a test enforces
  the boundary.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import List

__all__ = ["Arm", "build_paired_arms", "arm_seed", "ARM_NAMES"]

ARM_NAMES = ("card", "generic_advice", "none")


@dataclass(frozen=True)
class Arm:
    """One experimental arm: a name plus the prompt supplement it adds.

    ``prompt_supplement`` is "" for the no-advice arm. The supplement is
    the ONLY thing that varies between arms of the same instance.
    """

    name: str
    prompt_supplement: str


def build_paired_arms(instance_id: str, card_text: str,
                      generic_advice_text: str) -> List[Arm]:
    """Build the S1 matched arms: card vs generic advice vs none.

    Length/format matching between the card and the generic advice is an
    experimental-design obligation checked upstream; this primitive
    validates types and non-emptiness only.
    """
    if not isinstance(instance_id, str) or not instance_id:
        raise ValueError("instance_id must be a non-empty string")
    if not isinstance(card_text, str) or not card_text:
        raise ValueError("card_text must be a non-empty string")
    if not isinstance(generic_advice_text, str) or not generic_advice_text:
        raise ValueError("generic_advice_text must be a non-empty string")
    return [
        Arm("card", card_text),
        Arm("generic_advice", generic_advice_text),
        Arm("none", ""),
    ]


def arm_seed(instance_id: str, arm_name: str) -> int:
    """Deterministic per-arm seed: identical across campaign re-runs.

    Derived from a hash of ``instance_id:arm_name`` so re-running a
    campaign reproduces identical samples per arm without persisting a
    separate seed file per arm. Distinct arms of one instance get distinct
    seeds; the same arm of distinct instances gets distinct seeds.
    """
    if not isinstance(instance_id, str) or not instance_id:
        raise ValueError("instance_id must be a non-empty string")
    if arm_name not in ARM_NAMES:
        raise ValueError(f"unknown arm {arm_name!r}; options: {ARM_NAMES}")
    digest = hashlib.sha256(f"{instance_id}:{arm_name}".encode("utf-8")).hexdigest()
    return int(digest, 16) % (2**31)
