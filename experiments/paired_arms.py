"""Pure S1 arm-construction and reproducible per-arm seed utilities.

This module assembles caller-supplied prompt supplements only. It does not
choose or endorse generic-advice content, invoke a model, score outcomes, or
claim that the arms isolate a causal effect.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

ARM_NAMES = ("card", "generic_advice", "none")


def _require_text(value: object, *, label: str, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise ValueError(f"{label} must be text")
    if not allow_empty and not value.strip():
        raise ValueError(f"{label} must be nonempty")
    return value


@dataclass(frozen=True)
class Arm:
    """One prompt condition paired to a frozen underlying instance ID."""

    instance_id: str
    name: str
    prompt_supplement: str

    def __post_init__(self) -> None:
        _require_text(self.instance_id, label="instance_id")
        if type(self.name) is not str or self.name not in ARM_NAMES:
            raise ValueError(f"unknown S1 arm name {self.name!r}")
        if self.name == "none":
            _require_text(self.prompt_supplement, label="prompt_supplement", allow_empty=True)
            if self.prompt_supplement != "":
                raise ValueError("the no-advice arm must have an empty prompt supplement")
        else:
            _require_text(self.prompt_supplement, label="prompt_supplement")


def build_paired_arms(instance_id: str, card_text: str, generic_advice_text: str) -> list[Arm]:
    """Build three S1 arms tied to the same frozen instance identifier.

    The card and generic-advice strings are required caller inputs. This helper
    does not define their content or assert that they are length/format matched.
    """
    instance_id = _require_text(instance_id, label="instance_id")
    card_text = _require_text(card_text, label="card_text")
    generic_advice_text = _require_text(generic_advice_text, label="generic_advice_text")
    return [
        Arm(instance_id, "card", card_text),
        Arm(instance_id, "generic_advice", generic_advice_text),
        Arm(instance_id, "none", ""),
    ]


def arm_seed(instance_id: str, arm_name: str) -> int:
    """Return a reproducible arm-specific run seed for a shared instance ID.

    This seed is for per-arm run randomness only; it must not be used to
    regenerate a different underlying instance for each arm.
    """
    instance_id = _require_text(instance_id, label="instance_id")
    if type(arm_name) is not str or arm_name not in ARM_NAMES:
        raise ValueError(f"unknown S1 arm name {arm_name!r}")
    digest = hashlib.sha256(f"{instance_id}:{arm_name}".encode()).hexdigest()
    return int(digest, 16) % (2**31)


__all__ = ["ARM_NAMES", "Arm", "arm_seed", "build_paired_arms"]
